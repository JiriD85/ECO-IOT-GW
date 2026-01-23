"""
ECO-IOT-GW Update Service
OTA updates with rollback capability
"""
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import settings
from ..models.schemas import UpdateStatus

logger = logging.getLogger(__name__)


class UpdateService:
    """Service for OTA updates and rollback."""

    def __init__(self):
        self._backup_dir = settings.DATA_DIR / "backups"
        self._version_file = settings.BASE_DIR / "version.json"
        self._update_script = settings.BASE_DIR / "updates" / "update-manager.py"
        self._rollback_script = settings.BASE_DIR / "updates" / "rollback.sh"

    def check_updates(self) -> UpdateStatus:
        """Check for available updates."""
        current_version = self._get_current_version()

        # In a real implementation, this would check a remote server
        # For now, just return current status
        return UpdateStatus(
            update_available=False,
            current_version=current_version,
            latest_version=current_version
        )

    def _get_current_version(self) -> str:
        """Get current installed version."""
        if self._version_file.exists():
            try:
                with open(self._version_file) as f:
                    data = json.load(f)
                    return data.get("version", settings.APP_VERSION)
            except Exception:
                pass
        return settings.APP_VERSION

    def start_update(self, version: Optional[str] = None):
        """
        Start the update process.

        Args:
            version: Specific version to update to (None = latest)
        """
        # Create backup first
        self._create_backup()

        if self._update_script.exists():
            # Run update script
            cmd = ["python3", str(self._update_script)]
            if version:
                cmd.extend(["--version", version])

            try:
                subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                logger.info(f"Update started (version: {version or 'latest'})")

            except Exception as e:
                raise RuntimeError(f"Failed to start update: {e}")
        else:
            raise FileNotFoundError("Update script not found")

    def _create_backup(self):
        """Create a backup before update."""
        self._backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self._backup_dir / f"backup_{timestamp}"

        try:
            # Backup important directories
            dirs_to_backup = [
                settings.CONFIG_DIR,
                settings.DATA_DIR / "docker-compose",
                settings.DATA_DIR / "vpn"
            ]

            backup_path.mkdir()

            for src_dir in dirs_to_backup:
                if src_dir.exists():
                    dest = backup_path / src_dir.name
                    shutil.copytree(src_dir, dest, dirs_exist_ok=True)

            # Save version info
            with open(backup_path / "version.txt", 'w') as f:
                f.write(self._get_current_version())

            logger.info(f"Backup created: {backup_path}")

            # Clean old backups (keep last 5)
            self._cleanup_old_backups()

        except Exception as e:
            logger.error(f"Backup failed: {e}")
            raise RuntimeError(f"Failed to create backup: {e}")

    def _cleanup_old_backups(self, keep: int = 5):
        """Remove old backups."""
        if not self._backup_dir.exists():
            return

        backups = sorted(
            self._backup_dir.glob("backup_*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        for old_backup in backups[keep:]:
            try:
                shutil.rmtree(old_backup)
                logger.info(f"Removed old backup: {old_backup}")
            except Exception as e:
                logger.warning(f"Failed to remove backup {old_backup}: {e}")

    def rollback(self):
        """Rollback to previous version."""
        # Find latest backup
        if not self._backup_dir.exists():
            raise FileNotFoundError("No backups available for rollback")

        backups = sorted(
            self._backup_dir.glob("backup_*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        if not backups:
            raise FileNotFoundError("No backups available for rollback")

        latest_backup = backups[0]

        if self._rollback_script.exists():
            # Run rollback script
            try:
                subprocess.run(
                    ["/bin/bash", str(self._rollback_script), str(latest_backup)],
                    check=True,
                    capture_output=True,
                    timeout=300
                )
                logger.info(f"Rollback completed from {latest_backup}")

            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"Rollback failed: {e.stderr.decode()}")
        else:
            # Manual rollback
            self._manual_rollback(latest_backup)

    def _manual_rollback(self, backup_path: Path):
        """Perform manual rollback from backup."""
        try:
            # Restore config
            config_backup = backup_path / "eco-iot-gw"
            if config_backup.exists():
                shutil.copytree(config_backup, settings.CONFIG_DIR, dirs_exist_ok=True)

            # Restore data
            for subdir in ["docker-compose", "vpn"]:
                src = backup_path / subdir
                if src.exists():
                    dest = settings.DATA_DIR / subdir
                    shutil.copytree(src, dest, dirs_exist_ok=True)

            logger.info(f"Manual rollback completed from {backup_path}")

            # Restart services
            subprocess.run(["systemctl", "restart", "eco-iot-gw-backend"], check=False)

        except Exception as e:
            raise RuntimeError(f"Manual rollback failed: {e}")

    def get_backup_list(self) -> list:
        """Get list of available backups."""
        if not self._backup_dir.exists():
            return []

        backups = []
        for backup in sorted(self._backup_dir.glob("backup_*"), reverse=True):
            version_file = backup / "version.txt"
            version = "unknown"
            if version_file.exists():
                version = version_file.read_text().strip()

            backups.append({
                "name": backup.name,
                "path": str(backup),
                "version": version,
                "created": datetime.fromtimestamp(backup.stat().st_mtime).isoformat()
            })

        return backups


# Global update service instance
update_service = UpdateService()
