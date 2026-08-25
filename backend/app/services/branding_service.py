"""
ECO-IOT-GW Branding Service
Kit identification and branding asset management
"""
import json
import logging
import os
from pathlib import Path
from typing import Optional, Tuple

from ..config import settings
from ..models.schemas import BrandingConfig, BrandingStatus

logger = logging.getLogger(__name__)


class BrandingService:
    """Service for kit branding and identification."""

    # File size limits
    MAX_LOGO_SIZE = 1 * 1024 * 1024  # 1MB
    MAX_FAVICON_SIZE = 100 * 1024  # 100KB

    # Allowed content types
    LOGO_CONTENT_TYPES = {"image/png", "image/jpeg", "image/svg+xml"}
    FAVICON_CONTENT_TYPES = {"image/x-icon", "image/png"}

    def __init__(self):
        """Initialize branding service."""
        # Development mode fallback paths
        if os.getenv("DEBUG") or not settings.CONFIG_DIR.exists():
            self._config_path = Path.home() / ".eco-iot-gw" / "branding.json"
            self._assets_dir = Path.home() / ".eco-iot-gw" / "branding"
        else:
            self._config_path = settings.CONFIG_DIR / "branding.json"
            self._assets_dir = settings.DATA_DIR / "branding"

        # Ensure assets directory exists
        self._assets_dir.mkdir(parents=True, exist_ok=True)

    def _load_config(self) -> dict:
        """Load branding config from file."""
        if not self._config_path.exists():
            return {
                "kit_name": "ECO-IOT-GW",
                "theme": "light"
            }

        try:
            with open(self._config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load branding config: {e}")
            return {
                "kit_name": "ECO-IOT-GW",
                "theme": "light"
            }

    def _save_config(self, config_data: dict):
        """Save branding config with atomic write."""
        try:
            # Ensure parent directory exists
            self._config_path.parent.mkdir(parents=True, exist_ok=True)

            # Atomic write: write to temp file, then rename
            temp_path = self._config_path.with_suffix('.json.tmp')
            with open(temp_path, 'w') as f:
                json.dump(config_data, f, indent=2)

            # Atomic rename
            temp_path.rename(self._config_path)
            logger.info("Branding config saved")

        except Exception as e:
            logger.error(f"Failed to save branding config: {e}")
            raise RuntimeError(f"Failed to save branding config: {e}")

    def get_config(self) -> BrandingStatus:
        """Get current branding configuration and status."""
        config_data = self._load_config()

        # Check if assets exist
        logo_path = self._assets_dir / "logo"
        favicon_path = self._assets_dir / "favicon"

        return BrandingStatus(
            kit_name=config_data.get("kit_name", "ECO-IOT-GW"),
            theme=config_data.get("theme", "light"),
            has_logo=logo_path.exists(),
            has_favicon=favicon_path.exists()
        )

    def set_config(self, config: BrandingConfig) -> BrandingStatus:
        """Update branding configuration."""
        # Load current config
        current_config = self._load_config()

        # Update config
        current_config["kit_name"] = config.kit_name
        current_config["theme"] = config.theme

        # Save updated config
        self._save_config(current_config)

        # Return updated status
        return self.get_config()

    def save_logo(self, content: bytes, content_type: str):
        """Save logo file."""
        # Validate content type
        if content_type not in self.LOGO_CONTENT_TYPES:
            raise ValueError(
                f"Invalid logo content type. Allowed: {', '.join(self.LOGO_CONTENT_TYPES)}"
            )

        # Validate file size
        if len(content) > self.MAX_LOGO_SIZE:
            raise ValueError(
                f"Logo file too large. Maximum size: {self.MAX_LOGO_SIZE / 1024 / 1024:.1f}MB"
            )

        # Save file
        logo_path = self._assets_dir / "logo"
        try:
            logo_path.write_bytes(content)
            logger.info(f"Logo saved ({len(content)} bytes)")
        except Exception as e:
            logger.error(f"Failed to save logo: {e}")
            raise RuntimeError(f"Failed to save logo: {e}")

        # Save content type metadata
        meta_path = self._assets_dir / "logo.meta"
        try:
            meta_path.write_text(content_type)
        except Exception as e:
            logger.warning(f"Failed to save logo metadata: {e}")

    def get_logo(self) -> Optional[Tuple[bytes, str]]:
        """Get logo file and content type."""
        logo_path = self._assets_dir / "logo"
        meta_path = self._assets_dir / "logo.meta"

        if not logo_path.exists():
            return None

        try:
            content = logo_path.read_bytes()
            content_type = "image/png"  # Default

            if meta_path.exists():
                content_type = meta_path.read_text().strip()

            return (content, content_type)
        except Exception as e:
            logger.error(f"Failed to read logo: {e}")
            return None

    def delete_logo(self):
        """Delete logo file."""
        logo_path = self._assets_dir / "logo"
        meta_path = self._assets_dir / "logo.meta"

        try:
            if logo_path.exists():
                logo_path.unlink()
            if meta_path.exists():
                meta_path.unlink()
            logger.info("Logo deleted")
        except Exception as e:
            logger.error(f"Failed to delete logo: {e}")
            raise RuntimeError(f"Failed to delete logo: {e}")

    def save_favicon(self, content: bytes, content_type: str):
        """Save favicon file."""
        # Validate content type
        if content_type not in self.FAVICON_CONTENT_TYPES:
            raise ValueError(
                f"Invalid favicon content type. Allowed: {', '.join(self.FAVICON_CONTENT_TYPES)}"
            )

        # Validate file size
        if len(content) > self.MAX_FAVICON_SIZE:
            raise ValueError(
                f"Favicon file too large. Maximum size: {self.MAX_FAVICON_SIZE / 1024:.1f}KB"
            )

        # Save file
        favicon_path = self._assets_dir / "favicon"
        try:
            favicon_path.write_bytes(content)
            logger.info(f"Favicon saved ({len(content)} bytes)")
        except Exception as e:
            logger.error(f"Failed to save favicon: {e}")
            raise RuntimeError(f"Failed to save favicon: {e}")

        # Save content type metadata
        meta_path = self._assets_dir / "favicon.meta"
        try:
            meta_path.write_text(content_type)
        except Exception as e:
            logger.warning(f"Failed to save favicon metadata: {e}")

    def get_favicon(self) -> Optional[Tuple[bytes, str]]:
        """Get favicon file and content type."""
        favicon_path = self._assets_dir / "favicon"
        meta_path = self._assets_dir / "favicon.meta"

        if not favicon_path.exists():
            return None

        try:
            content = favicon_path.read_bytes()
            content_type = "image/x-icon"  # Default

            if meta_path.exists():
                content_type = meta_path.read_text().strip()

            return (content, content_type)
        except Exception as e:
            logger.error(f"Failed to read favicon: {e}")
            return None

    def delete_favicon(self):
        """Delete favicon file."""
        favicon_path = self._assets_dir / "favicon"
        meta_path = self._assets_dir / "favicon.meta"

        try:
            if favicon_path.exists():
                favicon_path.unlink()
            if meta_path.exists():
                meta_path.unlink()
            logger.info("Favicon deleted")
        except Exception as e:
            logger.error(f"Failed to delete favicon: {e}")
            raise RuntimeError(f"Failed to delete favicon: {e}")


# Global branding service instance
branding_service = BrandingService()
