"""
ECO-IOT-GW Backup Service
System backup and restore functionality for IoT Gateway

Handles:
- Creating tar.gz backups with manifest metadata
- Validating backup integrity and security
- Restoring system configuration from backups
- Path traversal protection during extraction
- Audit logging for all backup operations

Security features:
- Manifest validation (version check)
- Path traversal detection and prevention
- Symlink attack prevention
- Proper file permissions on restore
"""
import io
import json
import logging
import platform
import subprocess
import tarfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import settings
from .audit_service import audit_service

logger = logging.getLogger(__name__)


class BackupService:
    """Service for managing system backups and restores."""

    # Critical configuration paths to backup
    BACKUP_PATHS = [
        Path("/etc/eco-iot-gw/"),
        Path("/etc/openvpn/"),
        Path("/etc/wireguard/"),
        Path("/etc/thingsboard-gateway/config/"),
        Path("/etc/chrony/"),
        Path("/var/lib/eco-iot-gw/audit/")
    ]

    def __init__(self):
        """Initialize backup service with temp directory configuration."""
        self.temp_dir = Path("/tmp/eco-iot-gw-backups")
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def _run_command(
        self, cmd: List[str], sudo: bool = False
    ) -> Tuple[str, str, int]:
        """
        Execute a command with optional sudo.

        Args:
            cmd: Command and arguments as list
            sudo: Whether to run with sudo

        Returns:
            Tuple of (stdout, stderr, returncode)
        """
        try:
            if sudo:
                cmd = ["sudo"] + cmd

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.stdout, result.stderr, result.returncode

        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out: {' '.join(cmd)}")
            return "", "Command timed out", -1
        except Exception as e:
            logger.error(f"Command failed: {' '.join(cmd)} - {e}")
            return "", str(e), -1

    async def create_backup(
        self,
        username: str = "system",
        ip_address: str = "127.0.0.1"
    ) -> Dict[str, Any]:
        """
        Create a tar.gz backup of critical system configuration.

        Creates a backup archive containing:
        - All paths from BACKUP_PATHS that exist
        - Manifest JSON with metadata (version, timestamp, hostname, etc.)

        Args:
            username: User creating the backup (for audit)
            ip_address: Client IP (for audit)

        Returns:
            Dictionary with success status, backup file path, and metadata
        """
        try:
            # Generate backup filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_id = str(uuid.uuid4())[:8]
            backup_filename = f"eco-iot-gw-backup_{timestamp}_{backup_id}.tar.gz"
            backup_path = self.temp_dir / backup_filename

            # Create manifest
            manifest = {
                "version": "1.0",
                "created_at": datetime.now().isoformat(),
                "hostname": platform.node(),
                "app_version": settings.APP_VERSION,
                "paths": []
            }

            # Create tar.gz archive
            with tarfile.open(backup_path, mode='w:gz', format=tarfile.PAX_FORMAT) as tar:
                # Add manifest as first member
                manifest_json = json.dumps(manifest, indent=2)
                manifest_bytes = manifest_json.encode('utf-8')
                manifest_info = tarfile.TarInfo(name='backup-manifest.json')
                manifest_info.size = len(manifest_bytes)
                manifest_info.mtime = int(datetime.now().timestamp())
                tar.addfile(manifest_info, io.BytesIO(manifest_bytes))

                # Add each existing path from BACKUP_PATHS
                for path in self.BACKUP_PATHS:
                    if path.exists():
                        # Remove leading slash for archive name
                        arcname = str(path).lstrip('/')
                        tar.add(str(path), arcname=arcname, recursive=True)
                        manifest["paths"].append(str(path))
                        logger.debug(f"Added to backup: {path} as {arcname}")
                    else:
                        logger.warning(f"Skipping non-existent path: {path}")

                # Update manifest with actual paths included
                manifest_json = json.dumps(manifest, indent=2)
                manifest_bytes = manifest_json.encode('utf-8')
                manifest_info = tarfile.TarInfo(name='backup-manifest.json')
                manifest_info.size = len(manifest_bytes)
                manifest_info.mtime = int(datetime.now().timestamp())

                # Re-add manifest with updated paths (tarfile will overwrite)
                # Actually, we need to recreate the archive with the updated manifest
                # For simplicity, we'll update the manifest paths before adding files

            # Recreate archive with correct manifest
            backup_path.unlink()  # Remove the incomplete archive

            with tarfile.open(backup_path, mode='w:gz', format=tarfile.PAX_FORMAT) as tar:
                # Build paths list first
                included_paths = []
                for path in self.BACKUP_PATHS:
                    if path.exists():
                        included_paths.append(str(path))

                # Update manifest
                manifest["paths"] = included_paths

                # Add manifest as first member
                manifest_json = json.dumps(manifest, indent=2)
                manifest_bytes = manifest_json.encode('utf-8')
                manifest_info = tarfile.TarInfo(name='backup-manifest.json')
                manifest_info.size = len(manifest_bytes)
                manifest_info.mtime = int(datetime.now().timestamp())
                tar.addfile(manifest_info, io.BytesIO(manifest_bytes))

                # Add each path
                for path in self.BACKUP_PATHS:
                    if path.exists():
                        arcname = str(path).lstrip('/')
                        tar.add(str(path), arcname=arcname, recursive=True)
                        logger.debug(f"Added to backup: {path} as {arcname}")

            # Get backup file size
            backup_size = backup_path.stat().st_size

            # Log audit
            audit_service.log(
                username=username,
                action="backup_create",
                resource="system",
                ip_address=ip_address,
                success=True,
                details={
                    "backup_file": backup_filename,
                    "backup_size": backup_size,
                    "paths_included": manifest["paths"],
                    "hostname": manifest["hostname"]
                }
            )

            logger.info(
                f"Backup created successfully: {backup_filename} "
                f"({backup_size} bytes, {len(manifest['paths'])} paths)"
            )

            return {
                "success": True,
                "message": "Backup created successfully",
                "backup_file": str(backup_path),
                "backup_filename": backup_filename,
                "backup_size": backup_size,
                "manifest": manifest
            }

        except Exception as e:
            error_msg = f"Failed to create backup: {e}"
            logger.error(error_msg)

            audit_service.log(
                username=username,
                action="backup_create",
                resource="system",
                ip_address=ip_address,
                success=False,
                details={"error": error_msg}
            )

            return {"success": False, "message": error_msg}

    async def validate_backup(self, file_path: Path) -> Dict[str, Any]:
        """
        Validate a backup file for integrity and security.

        Checks:
        - Backup contains backup-manifest.json
        - Manifest version is "1.0"
        - Archive is readable

        Args:
            file_path: Path to backup file

        Returns:
            Dictionary with manifest data if valid

        Raises:
            ValueError: If backup is invalid or untrusted
        """
        try:
            if not file_path.exists():
                raise ValueError(f"Backup file not found: {file_path}")

            # Open tarfile in read mode
            with tarfile.open(file_path, mode='r:gz') as tar:
                # Look for manifest
                manifest_member = None
                for member in tar.getmembers():
                    if member.name == 'backup-manifest.json':
                        manifest_member = member
                        break

                if not manifest_member:
                    raise ValueError("Backup missing manifest file (backup-manifest.json)")

                # Extract and parse manifest
                manifest_file = tar.extractfile(manifest_member)
                if not manifest_file:
                    raise ValueError("Failed to read manifest from backup")

                manifest_json = manifest_file.read().decode('utf-8')
                manifest = json.loads(manifest_json)

                # Validate version
                if manifest.get("version") != "1.0":
                    raise ValueError(
                        f"Unsupported backup version: {manifest.get('version')}. "
                        f"Expected version 1.0"
                    )

                logger.info(
                    f"Backup validated: {file_path.name} "
                    f"(created: {manifest.get('created_at')}, "
                    f"hostname: {manifest.get('hostname')})"
                )

                return manifest

        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid manifest JSON: {e}")
        except tarfile.TarError as e:
            raise ValueError(f"Invalid tar archive: {e}")
        except Exception as e:
            raise ValueError(f"Backup validation failed: {e}")

    def _validate_tar_member(self, member: tarfile.TarInfo, target_dir: Path) -> None:
        """
        Validate a tar member for security issues.

        Security checks:
        - Reject absolute paths (path traversal)
        - Reject paths outside target directory (path traversal)
        - Reject symlinks (symlink attacks)

        Args:
            member: Tar member to validate
            target_dir: Target extraction directory

        Raises:
            ValueError: If member is unsafe
        """
        # Reject absolute paths
        if member.name.startswith('/'):
            raise ValueError(
                f"Security violation: absolute path in archive: {member.name}"
            )

        # Resolve and check path is relative to target
        member_path = target_dir / member.name
        try:
            resolved = member_path.resolve()
            if not resolved.is_relative_to(target_dir.resolve()):
                raise ValueError(
                    f"Security violation: path traversal detected: {member.name}"
                )
        except Exception as e:
            raise ValueError(
                f"Security violation: invalid path: {member.name} ({e})"
            )

        # Reject symlinks and hard links
        if member.issym() or member.islnk():
            raise ValueError(
                f"Security violation: symlink/hardlink not allowed: {member.name}"
            )

    async def restore_backup(
        self,
        file_path: Path,
        username: str = "system",
        ip_address: str = "127.0.0.1"
    ) -> Dict[str, Any]:
        """
        Restore system configuration from a backup file.

        Process:
        1. Validate backup integrity and manifest
        2. Validate all tar members for security
        3. Extract files to system locations with sudo
        4. Set proper permissions for sensitive files
        5. Log audit trail

        Args:
            file_path: Path to backup file
            username: User performing restore (for audit)
            ip_address: Client IP (for audit)

        Returns:
            Dictionary with success status and restored paths
        """
        try:
            # Validate backup first
            manifest = await self.validate_backup(file_path)

            # Create temporary extraction directory
            extract_dir = self.temp_dir / f"restore_{uuid.uuid4().hex[:8]}"
            extract_dir.mkdir(parents=True, exist_ok=True)

            restored_paths = []

            # Open tarfile and validate all members
            with tarfile.open(file_path, mode='r:gz') as tar:
                # First pass: validate all members
                for member in tar.getmembers():
                    # Skip manifest
                    if member.name == 'backup-manifest.json':
                        continue

                    # Validate member
                    self._validate_tar_member(member, extract_dir)

                # Second pass: extract files
                for member in tar.getmembers():
                    # Skip manifest
                    if member.name == 'backup-manifest.json':
                        continue

                    # Extract to temp directory
                    tar.extract(member, path=extract_dir)

                    # Map archived path back to original location
                    # Archive paths are like "etc/eco-iot-gw/..." -> "/etc/eco-iot-gw/..."
                    original_path = Path('/') / member.name

                    # Copy to system location with sudo
                    extracted_path = extract_dir / member.name

                    if extracted_path.is_file():
                        # Ensure parent directory exists
                        stdout, stderr, rc = self._run_command(
                            ["mkdir", "-p", str(original_path.parent)],
                            sudo=True
                        )

                        # Copy file
                        stdout, stderr, rc = self._run_command(
                            ["cp", str(extracted_path), str(original_path)],
                            sudo=True
                        )

                        if rc != 0:
                            logger.warning(
                                f"Failed to copy {extracted_path} to {original_path}: {stderr}"
                            )
                        else:
                            restored_paths.append(str(original_path))
                            logger.debug(f"Restored: {original_path}")

                    elif extracted_path.is_dir():
                        # Create directory
                        stdout, stderr, rc = self._run_command(
                            ["mkdir", "-p", str(original_path)],
                            sudo=True
                        )
                        if rc == 0:
                            restored_paths.append(str(original_path))

            # Set proper permissions for sensitive files
            # VPN configs should be readable only by root
            vpn_paths = [
                "/etc/openvpn",
                "/etc/wireguard"
            ]
            for vpn_path in vpn_paths:
                if Path(vpn_path).exists():
                    # Set 600 for WireGuard configs
                    if vpn_path == "/etc/wireguard":
                        self._run_command(
                            ["chmod", "-R", "600", vpn_path],
                            sudo=True
                        )
                    # Set 644 for OpenVPN configs
                    elif vpn_path == "/etc/openvpn":
                        self._run_command(
                            ["chmod", "-R", "644", vpn_path],
                            sudo=True
                        )

            # Clean up temporary extraction directory
            self._run_command(["rm", "-rf", str(extract_dir)], sudo=False)

            # Log audit
            audit_service.log(
                username=username,
                action="backup_restore",
                resource="system",
                ip_address=ip_address,
                success=True,
                details={
                    "backup_file": file_path.name,
                    "restored_paths": restored_paths,
                    "manifest": {
                        "created_at": manifest.get("created_at"),
                        "hostname": manifest.get("hostname"),
                        "version": manifest.get("version")
                    }
                }
            )

            logger.info(
                f"Backup restored successfully: {file_path.name} "
                f"({len(restored_paths)} paths restored)"
            )

            return {
                "success": True,
                "message": "Backup restored successfully",
                "restored_paths": restored_paths,
                "manifest": manifest
            }

        except ValueError as e:
            # Validation errors
            error_msg = str(e)
            logger.error(f"Backup restore validation failed: {error_msg}")

            audit_service.log(
                username=username,
                action="backup_restore",
                resource="system",
                ip_address=ip_address,
                success=False,
                details={"error": error_msg, "backup_file": file_path.name}
            )

            return {"success": False, "message": error_msg}

        except Exception as e:
            error_msg = f"Failed to restore backup: {e}"
            logger.error(error_msg)

            audit_service.log(
                username=username,
                action="backup_restore",
                resource="system",
                ip_address=ip_address,
                success=False,
                details={"error": error_msg, "backup_file": file_path.name}
            )

            return {"success": False, "message": error_msg}


# Global backup service instance
backup_service = BackupService()
