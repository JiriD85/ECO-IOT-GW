"""
ECO-IOT-GW Authentication Module
JWT-based authentication with session management
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from ..config import settings
from ..models.schemas import TokenResponse, UserInfo


# Security scheme
security = HTTPBearer()

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


def authenticate_user(username: str, password: str) -> Optional[dict]:
    """Authenticate a user and return user data if valid."""
    user = _users_db.get(username)
    if not user:
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


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> UserInfo:
    """Get the current authenticated user from the token."""
    token = credentials.credentials

    if is_token_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been invalidated"
        )

    payload = decode_token(token)

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type"
        )

    username = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )

    user = _users_db.get(username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    return UserInfo(
        username=username,
        role=user["role"],
        last_login=user.get("last_login")
    )


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
    """Change a user's password."""
    if username not in _users_db:
        return False
    _users_db[username]["password_hash"] = hash_password(new_password)
    return True


def load_users_from_secrets():
    """Load user credentials from secrets file."""
    import os
    admin_password = os.getenv("ADMIN_PASSWORD")
    if admin_password:
        _users_db["admin"]["password_hash"] = hash_password(admin_password)


# Initialize users from secrets on module load
load_users_from_secrets()
