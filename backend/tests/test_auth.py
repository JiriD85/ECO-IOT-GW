"""
Tests for authentication module
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security.auth import hash_password, verify_password, create_access_token


client = TestClient(app)


class TestPasswordHashing:
    """Tests for password hashing functions."""

    def test_hash_password(self):
        """Test password hashing produces different hash each time."""
        password = "test_password_123"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        assert hash1 != hash2  # Each hash should be unique (different salt)
        assert hash1.startswith("$2b$")  # bcrypt format

    def test_verify_password_correct(self):
        """Test verifying correct password."""
        password = "test_password_123"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Test verifying incorrect password."""
        password = "test_password_123"
        hashed = hash_password(password)

        assert verify_password("wrong_password", hashed) is False


class TestJWT:
    """Tests for JWT token functions."""

    def test_create_access_token(self):
        """Test creating access token."""
        token = create_access_token({"sub": "testuser"})

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0


class TestLoginEndpoint:
    """Tests for login endpoint."""

    def test_login_invalid_credentials(self):
        """Test login with invalid credentials."""
        response = client.post(
            "/api/auth/login",
            json={"username": "invalid", "password": "invalid"}
        )

        assert response.status_code == 401

    def test_login_missing_fields(self):
        """Test login with missing fields."""
        response = client.post(
            "/api/auth/login",
            json={"username": "testuser"}
        )

        assert response.status_code == 422  # Validation error


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_check(self):
        """Test health check returns ok."""
        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
