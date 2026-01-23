"""
Pytest configuration and fixtures
"""
import os
import pytest
from fastapi.testclient import TestClient

# Set test environment
os.environ["TESTING"] = "1"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-testing-only"
os.environ["AES_KEY"] = "test-aes-key-for-testing-only"

from app.main import app


@pytest.fixture
def client():
    """Create test client."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client):
    """Get authentication headers for protected endpoints."""
    # This would normally login and get a token
    # For testing, we might want to create a test user
    return {"Authorization": "Bearer test-token"}
