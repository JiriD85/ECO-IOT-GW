"""
ECO-IOT-GW Terminal API
WebSocket-based interactive shell
"""
import asyncio
import fcntl
import logging
import os
import pty
import select
import signal
import struct
import subprocess
import termios
import time
from typing import Optional

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status

from ..models.schemas import UserInfo
from ..security.auth import decode_token

logger = logging.getLogger(__name__)
router = APIRouter()


class TerminalSession:
    """Manages a PTY terminal session."""

    def __init__(self, websocket: WebSocket, username: str):
        self.websocket = websocket
        self.username = username
        self.master_fd: Optional[int] = None
        self.slave_fd: Optional[int] = None
        self.pid: Optional[int] = None
        self.running = False

    async def start(self):
        """Start the terminal session."""
        # Create pseudo-terminal
        self.master_fd, self.slave_fd = pty.openpty()

        # Fork process
        self.pid = os.fork()

        if self.pid == 0:
            # Child process
            os.close(self.master_fd)
            os.setsid()

            # Claim the slave PTY as this session's controlling terminal, so the
            # shell gets job control (Ctrl-C, fg/bg, vim/less). Without this bash
            # warns "cannot set terminal process group / no job control".
            try:
                fcntl.ioctl(self.slave_fd, termios.TIOCSCTTY, 0)
            except OSError:
                pass

            # Wire stdin/stdout/stderr to the PTY.
            os.dup2(self.slave_fd, 0)
            os.dup2(self.slave_fd, 1)
            os.dup2(self.slave_fd, 2)

            if self.slave_fd > 2:
                os.close(self.slave_fd)

            # Drop to the per-device operator account so the shell is NOT root.
            # The backend runs as root (needed to read the tb-gateway container's
            # sockets, docker, etc.), but the interactive host shell must run as
            # the local `ecoadmin` account -- the same one used to log in on-site,
            # regardless of whether this session authenticated via Tailscale or a
            # password. Returns the target's home/shell for the env below.
            home, shell, target_user = self._drop_privileges()

            # Execute shell
            env = os.environ.copy()
            env['TERM'] = 'xterm-256color'
            env['USER'] = target_user
            env['LOGNAME'] = target_user
            if home:
                env['HOME'] = home
                try:
                    os.chdir(home)
                except OSError:
                    pass

            shell = shell or '/bin/bash'
            try:
                os.execvpe(shell, [shell, '-l'], env)
            except Exception:
                os.execvpe('/bin/sh', ['/bin/sh'], env)
        else:
            # Parent process
            os.close(self.slave_fd)
            self.running = True

    def _drop_privileges(self):
        """If running as root, drop the forked child to the local operator
        account (settings.LOCAL_ADMIN_USER, e.g. ``ecoadmin``) so the terminal is
        not a root shell. No-op when already unprivileged, on a non-POSIX/dev box,
        or if the account doesn't exist. Returns (home, shell, effective_user).

        Runs in the child after setsid()/dup2() and before exec. If dropping is
        attempted but fails, the child exits rather than fall through as root.
        """
        fallback = self.username or 'root'
        try:
            import pwd
            from ..config import settings
        except Exception:
            return None, None, fallback

        try:
            info = pwd.getpwnam(settings.LOCAL_ADMIN_USER)
        except KeyError:
            # e.g. a dev box without the ecoadmin account -- keep current user.
            return None, None, fallback

        target = settings.LOCAL_ADMIN_USER
        try:
            # Only drop when we are actually root and the target is not root.
            if os.geteuid() == 0 and info.pw_uid != 0:
                os.setgid(info.pw_gid)
                try:
                    os.initgroups(target, info.pw_gid)
                except Exception:
                    pass
                os.setuid(info.pw_uid)
        except Exception:
            # Never hand out a root shell if the drop failed.
            os._exit(1)

        return info.pw_dir, info.pw_shell, target

    async def read_output(self):
        """Read output from PTY and send to WebSocket."""
        loop = asyncio.get_event_loop()
        while self.running:
            try:
                # Run blocking select in thread pool to avoid blocking the event loop
                r, _, _ = await loop.run_in_executor(
                    None,
                    lambda: select.select([self.master_fd], [], [], 0.1)
                )

                if self.master_fd in r:
                    # Also run the blocking read in thread pool
                    output = await loop.run_in_executor(
                        None,
                        lambda: os.read(self.master_fd, 4096)
                    )
                    if output:
                        await self.websocket.send_bytes(output)
                    else:
                        # EOF
                        break
                else:
                    await asyncio.sleep(0.01)

            except OSError:
                break
            except WebSocketDisconnect:
                break

    async def write_input(self, data: bytes):
        """Write input to PTY."""
        if self.master_fd and self.running:
            try:
                os.write(self.master_fd, data)
            except OSError as e:
                logger.error(f"Failed to write to PTY: {e}")

    def resize(self, rows: int, cols: int):
        """Resize the terminal."""
        if self.master_fd and self.running:
            try:
                winsize = struct.pack('HHHH', rows, cols, 0, 0)
                import fcntl
                fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
            except Exception as e:
                logger.error(f"Failed to resize terminal: {e}")

    def stop(self):
        """Stop the terminal session."""
        self.running = False

        if self.pid:
            try:
                os.kill(self.pid, signal.SIGTERM)
                # Non-blocking wait with timeout (1 second total)
                for _ in range(10):
                    pid, status = os.waitpid(self.pid, os.WNOHANG)
                    if pid != 0:
                        break
                    time.sleep(0.1)
                else:
                    # Force kill if still running after timeout
                    try:
                        os.kill(self.pid, signal.SIGKILL)
                        os.waitpid(self.pid, os.WNOHANG)
                    except Exception:
                        pass
            except ChildProcessError:
                # Process already exited
                pass
            except Exception:
                pass

        if self.master_fd:
            try:
                os.close(self.master_fd)
            except Exception:
                pass


async def authenticate_websocket(websocket: WebSocket) -> Optional[str]:
    """Authenticate WebSocket connection.

    Over the tailnet the caller is identified by their Tailscale login (no token);
    otherwise a valid bearer token is required via the ?token= query param.
    """
    from ..security.tailscale_identity import identity_for_request

    identity = identity_for_request(websocket)
    if identity:
        return identity

    token = websocket.query_params.get("token")

    if not token or token in ("null", "undefined"):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return None

        username = payload.get("sub")
        if not username:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return None

        return username

    except Exception as e:
        logger.warning(f"WebSocket authentication failed: {e}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None


@router.websocket("/ws")
async def terminal_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for interactive terminal.

    Connect with: ws://host/api/terminal/ws?token=<jwt_token>

    Protocol:
    - Binary messages: Input to shell
    - Text messages: Control commands (JSON)
        - {"type": "resize", "rows": 24, "cols": 80}

    Output is sent as binary messages (raw terminal output).
    """
    await websocket.accept()

    # Authenticate
    username = await authenticate_websocket(websocket)
    if not username:
        return

    logger.info(f"Terminal session started for user {username}")

    # Log audit event
    try:
        from ..services.audit_service import audit_service
        client_ip = websocket.client.host if websocket.client else "unknown"
        audit_service.log(
            username=username,
            action="terminal_connect",
            resource="terminal",
            ip_address=client_ip,
            success=True
        )
    except Exception:
        pass

    session = TerminalSession(websocket, username)

    try:
        await session.start()

        # Start reading output in background
        read_task = asyncio.create_task(session.read_output())

        # Handle incoming messages
        while session.running:
            try:
                message = await asyncio.wait_for(
                    websocket.receive(),
                    timeout=1.0
                )

                if message["type"] == "websocket.disconnect":
                    break

                if "bytes" in message:
                    # Binary data - input to shell
                    await session.write_input(message["bytes"])

                elif "text" in message:
                    # Text message - control command
                    import json
                    try:
                        cmd = json.loads(message["text"])
                        if cmd.get("type") == "resize":
                            session.resize(
                                cmd.get("rows", 24),
                                cmd.get("cols", 80)
                            )
                    except json.JSONDecodeError:
                        # Treat as text input
                        await session.write_input(message["text"].encode())

            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break

        read_task.cancel()

    except Exception as e:
        logger.error(f"Terminal error: {e}")

    finally:
        session.stop()
        logger.info(f"Terminal session ended for user {username}")

        # Log audit event
        try:
            from ..services.audit_service import audit_service
            client_ip = websocket.client.host if websocket.client else "unknown"
            audit_service.log(
                username=username,
                action="terminal_disconnect",
                resource="terminal",
                ip_address=client_ip,
                success=True
            )
        except Exception:
            pass
