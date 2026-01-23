#!/usr/bin/env python3
"""
ECO-IOT-GW Update Manager
OTA update handling with rollback support
"""
import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

INSTALL_DIR = Path("/opt/eco-iot-gw")
BACKUP_DIR = Path("/var/lib/eco-iot-gw/backups")
CONFIG_DIR = Path("/etc/eco-iot-gw")
VERSION_FILE = INSTALL_DIR / "version.json"


def get_current_version():
    """Get current installed version."""
    if VERSION_FILE.exists():
        with open(VERSION_FILE) as f:
            return json.load(f).get("version", "unknown")
    return "unknown"


def create_backup():
    """Create backup before update."""
    logger.info("Creating backup...")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"backup_{timestamp}"
    backup_path.mkdir()

    # Backup directories
    dirs_to_backup = [
        (CONFIG_DIR, "config"),
        (INSTALL_DIR / "backend", "backend"),
        (INSTALL_DIR / "frontend", "frontend")
    ]

    for src, name in dirs_to_backup:
        if src.exists():
            dest = backup_path / name
            shutil.copytree(src, dest)
            logger.info(f"Backed up {src} -> {dest}")

    # Save version info
    with open(backup_path / "version.txt", 'w') as f:
        f.write(get_current_version())

    logger.info(f"Backup created: {backup_path}")
    return backup_path


def cleanup_old_backups(keep=5):
    """Remove old backups, keeping the most recent ones."""
    if not BACKUP_DIR.exists():
        return

    backups = sorted(
        BACKUP_DIR.glob("backup_*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    for old_backup in backups[keep:]:
        shutil.rmtree(old_backup)
        logger.info(f"Removed old backup: {old_backup}")


def download_update(version=None):
    """Download update package."""
    # In a real implementation, this would download from a server
    logger.info(f"Downloading update (version: {version or 'latest'})...")
    # Placeholder - implement actual download logic
    return None


def apply_update(update_path):
    """Apply the downloaded update."""
    logger.info("Applying update...")

    # Stop services
    subprocess.run(["systemctl", "stop", "eco-iot-gw-backend"], check=False)

    try:
        # Apply update (placeholder)
        # In real implementation, extract and copy files

        # Restart services
        subprocess.run(["systemctl", "start", "eco-iot-gw-backend"], check=True)

        logger.info("Update applied successfully")
        return True

    except Exception as e:
        logger.error(f"Update failed: {e}")
        return False


def health_check():
    """Verify system is healthy after update."""
    logger.info("Running health check...")

    try:
        # Check backend is responding
        import urllib.request
        req = urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=10)
        if req.status != 200:
            return False

        # Check Docker
        result = subprocess.run(["docker", "ps"], capture_output=True)
        if result.returncode != 0:
            return False

        logger.info("Health check passed")
        return True

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return False


def rollback(backup_path=None):
    """Rollback to previous version."""
    logger.info("Starting rollback...")

    if not backup_path:
        # Find latest backup
        backups = sorted(
            BACKUP_DIR.glob("backup_*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        if not backups:
            logger.error("No backup found for rollback")
            return False
        backup_path = backups[0]

    logger.info(f"Rolling back from: {backup_path}")

    # Stop services
    subprocess.run(["systemctl", "stop", "eco-iot-gw-backend"], check=False)

    try:
        # Restore config
        config_backup = backup_path / "config"
        if config_backup.exists():
            if CONFIG_DIR.exists():
                shutil.rmtree(CONFIG_DIR)
            shutil.copytree(config_backup, CONFIG_DIR)

        # Restore backend
        backend_backup = backup_path / "backend"
        if backend_backup.exists():
            backend_dest = INSTALL_DIR / "backend"
            if backend_dest.exists():
                shutil.rmtree(backend_dest)
            shutil.copytree(backend_backup, backend_dest)

        # Restart services
        subprocess.run(["systemctl", "start", "eco-iot-gw-backend"], check=True)

        logger.info("Rollback completed successfully")
        return True

    except Exception as e:
        logger.error(f"Rollback failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="ECO-IOT-GW Update Manager")
    parser.add_argument("--version", help="Specific version to update to")
    parser.add_argument("--rollback", action="store_true", help="Rollback to previous version")
    parser.add_argument("--backup-only", action="store_true", help="Only create backup")
    args = parser.parse_args()

    if args.rollback:
        if rollback():
            sys.exit(0)
        else:
            sys.exit(1)

    if args.backup_only:
        create_backup()
        sys.exit(0)

    # Normal update flow
    logger.info(f"Current version: {get_current_version()}")

    # Create backup
    backup_path = create_backup()

    # Download update
    update_path = download_update(args.version)
    if not update_path:
        logger.warning("No update available")
        sys.exit(0)

    # Apply update
    if not apply_update(update_path):
        logger.error("Update failed, rolling back...")
        rollback(backup_path)
        sys.exit(1)

    # Health check
    if not health_check():
        logger.error("Health check failed, rolling back...")
        rollback(backup_path)
        sys.exit(1)

    # Cleanup old backups
    cleanup_old_backups()

    logger.info("Update completed successfully")


if __name__ == "__main__":
    main()
