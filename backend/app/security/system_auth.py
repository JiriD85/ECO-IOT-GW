"""
Verify a webUI login against the device's local Linux account (/etc/shadow).

The on-site login IS a real Linux user (per-device `ecoadmin`), so we check the
typed password against the system's shadow hash instead of keeping a separate
password store on the box -- one fewer credential to leak.

Reading /etc/shadow requires the backend to run privileged. A non-root
deployment should instead verify via a setuid PAM helper (`unix_chkpwd`);
verify_system_password() raises PermissionError in that case so the caller can
tell "wrong password" apart from "backend can't read shadow".

Unix-only stdlib (`crypt`, `spwd`) -- guarded so this module still imports on a
Windows dev box, where system_user_exists() simply returns False.
"""
from hmac import compare_digest

try:  # POSIX only; absent on Windows and removed in Python 3.13+
    import crypt
    import pwd
    import spwd
    _POSIX = True
except ImportError:  # pragma: no cover - dev on non-POSIX
    crypt = pwd = spwd = None
    _POSIX = False


def system_user_exists(username: str) -> bool:
    """True if `username` is a real account in the passwd database."""
    if not _POSIX or not username:
        return False
    try:
        pwd.getpwnam(username)
        return True
    except KeyError:
        return False


def verify_system_password(username: str, password: str) -> bool:
    """True iff `password` matches the Linux user's shadow hash.

    Returns False for unknown users, locked/passwordless accounts, and
    mismatches. Raises PermissionError if /etc/shadow is unreadable, so the
    caller can surface "backend not privileged" rather than silently failing
    every login.
    """
    if not _POSIX or not username or not password:
        return False
    try:
        entry = spwd.getspnam(username)  # PermissionError if not privileged
    except KeyError:
        return False

    stored = entry.sp_pwdp or ""
    # Locked ("!"/"!!"), disabled ("*"), or empty-hash accounts never
    # authenticate with a password.
    if not stored or stored[0] in "!*":
        return False

    calculated = crypt.crypt(password, stored)
    return compare_digest(calculated, stored)
