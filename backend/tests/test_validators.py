"""
Tests for input validation module
"""
import pytest
from fastapi import HTTPException

from app.security.validators import (
    validate_filename,
    validate_ip_address,
    validate_apn,
    validate_ssid,
    validate_password,
    validate_shell_input
)


class TestFilenameValidation:
    """Tests for filename validation."""

    def test_valid_filename(self):
        """Test valid filename passes."""
        assert validate_filename("test.txt") == "test.txt"
        assert validate_filename("my_file-name.yaml") == "my_file-name.yaml"

    def test_path_traversal_blocked(self):
        """Test path traversal is blocked."""
        with pytest.raises(HTTPException) as exc:
            validate_filename("../etc/passwd")
        assert exc.value.status_code == 400

    def test_extension_validation(self):
        """Test file extension validation."""
        assert validate_filename("config.yaml", ["yaml", "yml"]) == "config.yaml"

        with pytest.raises(HTTPException):
            validate_filename("config.exe", ["yaml", "yml"])


class TestIPValidation:
    """Tests for IP address validation."""

    def test_valid_ipv4(self):
        """Test valid IPv4 addresses."""
        assert validate_ip_address("192.168.1.1") == "192.168.1.1"
        assert validate_ip_address("10.0.0.1") == "10.0.0.1"
        assert validate_ip_address("255.255.255.255") == "255.255.255.255"

    def test_invalid_ipv4(self):
        """Test invalid IPv4 addresses are rejected."""
        with pytest.raises(HTTPException):
            validate_ip_address("256.1.1.1")

        with pytest.raises(HTTPException):
            validate_ip_address("not.an.ip")

        with pytest.raises(HTTPException):
            validate_ip_address("192.168.1")


class TestAPNValidation:
    """Tests for APN validation."""

    def test_valid_apn(self):
        """Test valid APN names."""
        assert validate_apn("internet") == "internet"
        assert validate_apn("web.provider.com") == "web.provider.com"

    def test_invalid_apn(self):
        """Test invalid APN names are rejected."""
        with pytest.raises(HTTPException):
            validate_apn("")

        with pytest.raises(HTTPException):
            validate_apn("a" * 101)  # Too long


class TestSSIDValidation:
    """Tests for SSID validation."""

    def test_valid_ssid(self):
        """Test valid SSIDs."""
        assert validate_ssid("MyNetwork") == "MyNetwork"
        assert validate_ssid("ECO-IOT-GW") == "ECO-IOT-GW"

    def test_invalid_ssid(self):
        """Test invalid SSIDs are rejected."""
        with pytest.raises(HTTPException):
            validate_ssid("")

        with pytest.raises(HTTPException):
            validate_ssid("a" * 33)  # Too long


class TestPasswordValidation:
    """Tests for password validation."""

    def test_valid_password(self):
        """Test valid passwords."""
        assert validate_password("password123") == "password123"
        assert validate_password("a" * 63) == "a" * 63

    def test_invalid_password(self):
        """Test invalid passwords are rejected."""
        with pytest.raises(HTTPException):
            validate_password("")

        with pytest.raises(HTTPException):
            validate_password("short", min_length=8)


class TestShellInputValidation:
    """Tests for shell input validation."""

    def test_safe_input(self):
        """Test safe inputs pass."""
        assert validate_shell_input("hello") == "hello"
        assert validate_shell_input("test123") == "test123"

    def test_dangerous_input_blocked(self):
        """Test dangerous shell characters are blocked."""
        with pytest.raises(HTTPException):
            validate_shell_input("test; rm -rf /")

        with pytest.raises(HTTPException):
            validate_shell_input("test | cat /etc/passwd")

        with pytest.raises(HTTPException):
            validate_shell_input("$(whoami)")
