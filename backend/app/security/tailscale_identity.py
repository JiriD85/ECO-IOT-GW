"""
Tailscale identity resolution.

When a request reaches the gateway over the tailnet, the local tailscaled can
tell us *who* is connecting (their Tailscale SSO login). We reuse that as the
web console's identity on the remote path -- no password, per-user audit.

Trust boundary: only requests whose real peer IP is in the Tailscale CGNAT range
are treated as tailnet requests. The peer IP comes from nginx's X-Real-IP
(set to $remote_addr, not client-controllable) or, when hitting uvicorn directly
on 127.0.0.1, from the socket. Client-supplied X-Forwarded-For is deliberately
ignored for auth decisions.
"""
import ipaddress
import json
import logging
import subprocess
import time
from typing import Optional

logger = logging.getLogger(__name__)

_TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
_TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")

# cache whois results so we don't spawn a subprocess per request
_CACHE: dict[str, tuple[Optional[str], float]] = {}
_CACHE_TTL = 60.0


def client_ip(request) -> str:
    """Real peer IP. Prefer nginx's X-Real-IP; never trust X-Forwarded-For here."""
    xreal = request.headers.get("X-Real-IP")
    if xreal:
        return xreal.strip()
    if getattr(request, "client", None):
        return request.client.host or ""
    return ""


def is_tailnet_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr in _TAILNET_V4 or addr in _TAILNET_V6


def whois(ip: str) -> Optional[str]:
    """Return the Tailscale login (email) for a tailnet peer IP, or None."""
    now = time.monotonic()
    cached = _CACHE.get(ip)
    if cached and cached[1] > now:
        return cached[0]

    login: Optional[str] = None
    try:
        out = subprocess.run(
            ["tailscale", "whois", "--json", ip],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0 and out.stdout:
            data = json.loads(out.stdout)
            login = (data.get("UserProfile") or {}).get("LoginName") or None
    except Exception as e:  # tailscale missing, timeout, bad json
        logger.debug(f"tailscale whois failed for {ip}: {e}")

    _CACHE[ip] = (login, now + _CACHE_TTL)
    return login


def identity_for_request(request) -> Optional[str]:
    """If the request came over the tailnet, return the caller's login (or a
    generic marker when whois can't resolve it). None if not a tailnet request."""
    ip = client_ip(request)
    if not is_tailnet_ip(ip):
        return None
    return whois(ip) or "tailnet user"
