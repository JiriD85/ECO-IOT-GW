"""
ECO-IOT-GW Authentication Module
JWT-based authentication with session management
"""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from ..config import settings
from ..models.schemas import TokenResponse, UserInfo
from .system_auth import system_user_exists, verify_system_password
from .tailscale_identity import identity_for_request

logger = logging.getLogger(__name__)


# Security scheme. auto_error=False so a missing token is not an instant 403 --
# the request may instead be authenticated by its Tailscale identity.
security = HTTPBearer(auto_error=False)

# In-memory storage for demo (replace with database in production)
# Password hash for "admin" - change in production
_users_db = {
    "admin": {
        "password_hash": bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode(),
        "role": "admin",
        "last_login": None
    }
}

# Refresh tokens storage
_refresh_tokens: dict[str, dict] = {}

# Invalid tokens (blacklist)
_blacklisted_tokens: set[str] = set()


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access"
    })
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(username: str) -> str:
    """Create a refresh token."""
    token = secrets.token_urlsafe(32)
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    _refresh_tokens[token] = {
        "username": username,
        "expires": expire
    }
    return token


def verify_refresh_token(token: str) -> Optional[str]:
    """Verify a refresh token and return username if valid."""
    if token not in _refresh_tokens:
        return None

    token_data = _refresh_tokens[token]
    if datetime.now(timezone.utc) > token_data["expires"]:
        del _refresh_tokens[token]
        return None

    return token_data["username"]


def invalidate_refresh_token(token: str) -> None:
    """Invalidate a refresh token."""
    _refresh_tokens.pop(token, None)


def blacklist_token(token: str) -> None:
    """Add a token to the blacklist."""
    _blacklisted_tokens.add(token)


def is_token_blacklisted(token: str) -> bool:
    """Check if a token is blacklisted."""
    return token in _blacklisted_tokens


def _ensure_system_user(username: str) -> dict:
    """Register a verified local Linux user in the in-memory table so token
    creation/validation can look up its role. No password is stored -- the
    Linux account (/etc/shadow) remains the source of truth."""
    entry = _users_db.get(username)
    if entry is None:
        entry = {
            "password_hash": None,
            "role": "admin",
            "last_login": None,
            "source": "system",
        }
        _users_db[username] = entry
    return entry


def authenticate_user(username: str, password: str) -> Optional[dict]:
    """Authenticate a user and return user data if valid.

    The on-site login is the device's local Linux account (LOCAL_ADMIN_USER,
    e.g. `ecoadmin`): verify it against /etc/shadow, not a stored hash. Any
    other username falls back to the in-memory table (dev/admin only)."""
    if username == settings.LOCAL_ADMIN_USER and system_user_exists(username):
        try:
            if not verify_system_password(username, password):
                return None
        except PermissionError:
            logger.error(
                "Cannot read /etc/shadow to verify %s -- backend needs "
                "privilege or a setuid PAM helper.", username
            )
            return None
        user = _ensure_system_user(username)
        user["last_login"] = datetime.now(timezone.utc)
        return user

    user = _users_db.get(username)
    if not user or not user.get("password_hash"):
        return None
    if not verify_password(password, user["password_hash"]):
        return None

    # Update last login
    user["last_login"] = datetime.now(timezone.utc)
    return user


def create_tokens(username: str) -> TokenResponse:
    """Create access and refresh tokens for a user."""
    user = _users_db.get(username)
    if not user:
        raise ValueError("User not found")

    access_token = create_access_token(
        data={"sub": username, "role": user["role"]}
    )
    refresh_token = create_refresh_token(username)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )


def _user_from_token(token: str) -> Optional[UserInfo]:
    """Validate a bearer token and return the user, or None if invalid."""
    if is_token_blacklisted(token):
        return None
    try:
        payload = decode_token(token)
    except HTTPException:
        return None
    if payload.get("type") != "access":
        return None
    username = payload.get("sub")
    if not username:
        return None
    user = _users_db.get(username)
    if not user:
        # A token issued to the local Linux user before a backend restart is
        # still valid -- rebuild its entry rather than forcing a re-login.
        if username == settings.LOCAL_ADMIN_USER and system_user_exists(username):
            user = _ensure_system_user(username)
        else:
            return None
    return UserInfo(username=username, role=user["role"], last_login=user.get("last_login"))


def resolve_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials],
) -> Optional[UserInfo]:
    """Identify the caller without raising.

    Priority:
      1. Tailscale identity (request arrived over the tailnet) -> that SSO login.
      2. A valid bearer token (local / password session).
      3. None (anonymous).
    """
    identity = identity_for_request(request)
    if identity:
        return UserInfo(username=identity, role="admin", last_login=None)

    if credentials and credentials.credentials:
        return _user_from_token(credentials.credentials)

    return None


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> UserInfo:
    """Require an authenticated caller (Tailscale identity or bearer token)."""
    user = resolve_user(request, credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user


async def get_optional_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[UserInfo]:
    """Open endpoints: return the caller if known, else None (never raises)."""
    return resolve_user(request, credentials)


def require_role(required_role: str):
    """Dependency to require a specific role."""
    async def role_checker(user: UserInfo = Depends(get_current_user)):
        if user.role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {required_role} role"
            )
        return user
    return role_checker


def change_password(username: str, new_password: str) -> bool:
    """Change an in-memory user's password.

    Not applicable to the local Linux account -- its password lives in
    /etc/shadow and is changed with `passwd`, not here."""
    entry = _users_db.get(username)
    if entry is None or entry.get("source") == "system":
        return False
    entry["password_hash"] = hash_password(new_password)
    return True


def load_users_from_secrets():
    """Load user credentials from secrets file."""
    import os
    admin_password = os.getenv("ADMIN_PASSWORD")
    if admin_password and "admin" in _users_db:
        _users_db["admin"]["password_hash"] = hash_password(admin_password)


def _init_local_admin():
    """On a provisioned device the local Linux account is the login. Register
    it and remove the insecure in-memory admin/admin default so it can never be
    used in production. On a dev box (no such user) admin/admin stays."""
    local_user = settings.LOCAL_ADMIN_USER
    if local_user and system_user_exists(local_user):
        _ensure_system_user(local_user)
        _users_db.pop("admin", None)
        logger.info("Local admin login bound to system user '%s'; "
                    "in-memory admin disabled.", local_user)


# Initialize users on module load
load_users_from_secrets()
_init_local_admin()
