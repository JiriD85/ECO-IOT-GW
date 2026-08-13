"""
ECO-IOT-GW Authentication API
Login, logout, token refresh
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..models.schemas import (
    ErrorResponse,
    LoginRequest,
    RefreshTokenRequest,
    SuccessResponse,
    TokenResponse,
    UserInfo
)
from fastapi.security import HTTPAuthorizationCredentials

from ..security.auth import (
    authenticate_user,
    blacklist_token,
    create_tokens,
    get_current_user,
    invalidate_refresh_token,
    resolve_user,
    security,
    verify_refresh_token
)
from ..security.tailscale_identity import identity_for_request
from ..security.rate_limiter import login_rate_limiter

router = APIRouter()


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Invalid credentials"},
        429: {"model": ErrorResponse, "description": "Too many attempts"}
    }
)
async def login(request: Request, login_data: LoginRequest):
    """
    Authenticate user and return JWT tokens.

    - **username**: User's username
    - **password**: User's password

    Returns access token (15 min) and refresh token (7 days).
    """
    # Check rate limit
    if not login_rate_limiter.check_allowed(request, login_data.username):
        lockout = login_rate_limiter.get_lockout_remaining(request, login_data.username)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Try again in {lockout} seconds.",
            headers={"Retry-After": str(lockout)}
        )

    # Authenticate
    user = authenticate_user(login_data.username, login_data.password)

    if not user:
        # Record failed attempt
        login_rate_limiter.record_attempt(request, login_data.username, success=False)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )

    # Record successful attempt
    login_rate_limiter.record_attempt(request, login_data.username, success=True)

    # Create tokens
    tokens = create_tokens(login_data.username)

    # Log audit event
    try:
        from ..services.audit_service import audit_service
        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not client_ip:
            client_ip = request.client.host if request.client else "unknown"

        audit_service.log(
            username=login_data.username,
            action="login",
            resource="auth",
            details={"method": "password"},
            ip_address=client_ip,
            success=True
        )
    except Exception:
        pass

    return tokens


@router.post(
    "/logout",
    response_model=SuccessResponse,
    responses={401: {"model": ErrorResponse}}
)
async def logout(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """
    Logout user and invalidate current token.

    Requires valid access token in Authorization header.
    """
    # Get the token from header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        blacklist_token(token)

    # Log audit event
    try:
        from ..services.audit_service import audit_service
        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not client_ip:
            client_ip = request.client.host if request.client else "unknown"

        audit_service.log(
            username=user.username,
            action="logout",
            resource="auth",
            ip_address=client_ip,
            success=True
        )
    except Exception:
        pass

    return SuccessResponse(message="Logged out successfully")


@router.post(
    "/refresh",
    response_model=TokenResponse,
    responses={401: {"model": ErrorResponse}}
)
async def refresh_token(data: RefreshTokenRequest):
    """
    Refresh access token using refresh token.

    - **refresh_token**: Valid refresh token from login

    Returns new access and refresh tokens.
    """
    username = verify_refresh_token(data.refresh_token)

    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )

    # Invalidate old refresh token
    invalidate_refresh_token(data.refresh_token)

    # Create new tokens
    return create_tokens(username)


@router.get("/whoami")
async def whoami(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
):
    """
    Report the caller's auth state without requiring authentication.

    Open endpoint — used by the frontend to decide whether to show anything
    locked or prompt for the on-site password. Over Tailscale the caller is
    already identified by their SSO login (no prompt needed).
    """
    user = resolve_user(request, credentials)
    if user is None:
        return {"authenticated": False, "identity": None, "method": None, "role": None}
    method = "tailscale" if identity_for_request(request) else "password"
    return {
        "authenticated": True,
        "identity": user.username,
        "method": method,
        "role": user.role,
    }


@router.get(
    "/me",
    response_model=UserInfo,
    responses={401: {"model": ErrorResponse}}
)
async def get_me(user: UserInfo = Depends(get_current_user)):
    """
    Get current user information.

    Requires valid access token.
    """
    return user


@router.post(
    "/change-password",
    response_model=SuccessResponse,
    responses={401: {"model": ErrorResponse}, 400: {"model": ErrorResponse}}
)
async def change_password(
    request: Request,
    current_password: str,
    new_password: str,
    user: UserInfo = Depends(get_current_user)
):
    """
    Change user password.

    - **current_password**: Current password
    - **new_password**: New password (min 8 characters)

    Requires valid access token.
    """
    from ..security.auth import authenticate_user, change_password as do_change_password
    from ..security.validators import validate_password

    # Validate new password
    validate_password(new_password)

    # Verify current password
    if not authenticate_user(user.username, current_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )

    # Change password
    if not do_change_password(user.username, new_password):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to change password"
        )

    # Log audit event
    try:
        from ..services.audit_service import audit_service
        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not client_ip:
            client_ip = request.client.host if request.client else "unknown"

        audit_service.log(
            username=user.username,
            action="change_password",
            resource="auth",
            ip_address=client_ip,
            success=True
        )
    except Exception:
        pass

    return SuccessResponse(message="Password changed successfully")
