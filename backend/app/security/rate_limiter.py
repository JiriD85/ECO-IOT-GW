"""
ECO-IOT-GW Rate Limiter Module
Brute-force protection and rate limiting
"""
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional

from fastapi import HTTPException, Request, status

from ..config import settings


@dataclass
class RateLimitEntry:
    """Rate limit entry for tracking requests."""
    requests: int = 0
    window_start: float = field(default_factory=time.time)


@dataclass
class LoginAttempt:
    """Login attempt tracking."""
    attempts: int = 0
    first_attempt: datetime = field(default_factory=datetime.now)
    locked_until: Optional[datetime] = None


class RateLimiter:
    """Rate limiter for API endpoints."""

    def __init__(
        self,
        requests_limit: int = None,
        window_seconds: int = None
    ):
        self.requests_limit = requests_limit or settings.RATE_LIMIT_REQUESTS
        self.window_seconds = window_seconds or settings.RATE_LIMIT_WINDOW_SECONDS
        self._entries: Dict[str, RateLimitEntry] = defaultdict(RateLimitEntry)

    def _get_client_id(self, request: Request) -> str:
        """Get client identifier from request."""
        # Use X-Forwarded-For if behind proxy, otherwise client host
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _cleanup_old_entries(self):
        """Remove expired entries."""
        current_time = time.time()
        expired = [
            key for key, entry in self._entries.items()
            if current_time - entry.window_start > self.window_seconds
        ]
        for key in expired:
            del self._entries[key]

    def check_rate_limit(self, request: Request) -> bool:
        """Check if request is within rate limit."""
        self._cleanup_old_entries()

        client_id = self._get_client_id(request)
        current_time = time.time()
        entry = self._entries[client_id]

        # Reset window if expired
        if current_time - entry.window_start > self.window_seconds:
            entry.requests = 0
            entry.window_start = current_time

        entry.requests += 1

        if entry.requests > self.requests_limit:
            return False
        return True

    def get_remaining(self, request: Request) -> int:
        """Get remaining requests for client."""
        client_id = self._get_client_id(request)
        entry = self._entries.get(client_id)
        if not entry:
            return self.requests_limit
        return max(0, self.requests_limit - entry.requests)


class LoginRateLimiter:
    """Rate limiter specifically for login attempts."""

    def __init__(
        self,
        max_attempts: int = None,
        lockout_minutes: int = None
    ):
        self.max_attempts = max_attempts or settings.LOGIN_MAX_ATTEMPTS
        self.lockout_minutes = lockout_minutes or settings.LOGIN_LOCKOUT_MINUTES
        self._attempts: Dict[str, LoginAttempt] = defaultdict(LoginAttempt)

    def _get_key(self, request: Request, username: str) -> str:
        """Get key combining IP and username."""
        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not client_ip:
            client_ip = request.client.host if request.client else "unknown"
        return f"{client_ip}:{username}"

    def check_allowed(self, request: Request, username: str) -> bool:
        """Check if login attempt is allowed."""
        key = self._get_key(request, username)
        attempt = self._attempts[key]

        # Check if locked
        if attempt.locked_until:
            if datetime.now() < attempt.locked_until:
                return False
            else:
                # Lock expired, reset
                self._attempts[key] = LoginAttempt()
                return True

        return True

    def record_attempt(self, request: Request, username: str, success: bool):
        """Record a login attempt."""
        key = self._get_key(request, username)

        if success:
            # Reset on successful login
            if key in self._attempts:
                del self._attempts[key]
            return

        attempt = self._attempts[key]
        attempt.attempts += 1

        if attempt.attempts >= self.max_attempts:
            attempt.locked_until = datetime.now() + timedelta(minutes=self.lockout_minutes)

    def get_lockout_remaining(self, request: Request, username: str) -> Optional[int]:
        """Get remaining lockout time in seconds."""
        key = self._get_key(request, username)
        attempt = self._attempts.get(key)

        if not attempt or not attempt.locked_until:
            return None

        remaining = (attempt.locked_until - datetime.now()).total_seconds()
        return max(0, int(remaining))

    def reset(self, request: Request, username: str):
        """Reset attempts for a user."""
        key = self._get_key(request, username)
        if key in self._attempts:
            del self._attempts[key]


# Global instances
api_rate_limiter = RateLimiter()
login_rate_limiter = LoginRateLimiter()


async def rate_limit_dependency(request: Request):
    """FastAPI dependency for rate limiting."""
    if not api_rate_limiter.check_rate_limit(request):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
            headers={
                "Retry-After": str(settings.RATE_LIMIT_WINDOW_SECONDS),
                "X-RateLimit-Limit": str(settings.RATE_LIMIT_REQUESTS),
                "X-RateLimit-Remaining": "0"
            }
        )
    return True
