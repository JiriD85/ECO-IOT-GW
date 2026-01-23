"""
ECO-IOT-GW Cryptography Module
AES-256 encryption for sensitive data
"""
import base64
import hashlib
import secrets
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from ..config import settings


class CryptoService:
    """Service for encrypting/decrypting sensitive data."""

    def __init__(self, key: Optional[str] = None):
        """Initialize with encryption key."""
        self._key = key or settings.AES_KEY
        self._fernet = self._create_fernet()

    def _create_fernet(self) -> Fernet:
        """Create Fernet instance from key."""
        # Derive a proper Fernet key from our key using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"eco-iot-gw-salt",  # Fixed salt for consistent encryption
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(self._key.encode()))
        return Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext and return base64-encoded ciphertext."""
        if not plaintext:
            return ""
        ciphertext = self._fernet.encrypt(plaintext.encode())
        return base64.urlsafe_b64encode(ciphertext).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt base64-encoded ciphertext and return plaintext."""
        if not ciphertext:
            return ""
        try:
            decoded = base64.urlsafe_b64decode(ciphertext.encode())
            plaintext = self._fernet.decrypt(decoded)
            return plaintext.decode()
        except Exception:
            raise ValueError("Failed to decrypt data")

    def encrypt_file(self, data: bytes) -> bytes:
        """Encrypt file data."""
        return self._fernet.encrypt(data)

    def decrypt_file(self, data: bytes) -> bytes:
        """Decrypt file data."""
        return self._fernet.decrypt(data)


# Global crypto service instance
crypto_service = CryptoService()


def encrypt_sensitive_data(data: str) -> str:
    """Encrypt sensitive data like passwords, keys, etc."""
    return crypto_service.encrypt(data)


def decrypt_sensitive_data(data: str) -> str:
    """Decrypt sensitive data."""
    return crypto_service.decrypt(data)


def generate_secure_token(length: int = 32) -> str:
    """Generate a cryptographically secure random token."""
    return secrets.token_urlsafe(length)


def hash_data(data: str) -> str:
    """Create a SHA-256 hash of data."""
    return hashlib.sha256(data.encode()).hexdigest()
