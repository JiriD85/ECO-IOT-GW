#!/bin/bash
#
# ECO-IOT-GW Rollback Script
# Restores system from backup
#

set -e

BACKUP_DIR="/var/lib/eco-iot-gw/backups"
INSTALL_DIR="/opt/eco-iot-gw"
CONFIG_DIR="/etc/eco-iot-gw"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" >&2
}

# Check if backup path provided
if [ -z "$1" ]; then
    # Find latest backup
    BACKUP_PATH=$(ls -td ${BACKUP_DIR}/backup_* 2>/dev/null | head -1)
    if [ -z "$BACKUP_PATH" ]; then
        error "No backup found"
        exit 1
    fi
else
    BACKUP_PATH="$1"
fi

if [ ! -d "$BACKUP_PATH" ]; then
    error "Backup directory not found: $BACKUP_PATH"
    exit 1
fi

log "Rolling back from: $BACKUP_PATH"

# Stop services
log "Stopping services..."
systemctl stop eco-iot-gw-backend || true

# Restore configuration
if [ -d "${BACKUP_PATH}/config" ]; then
    log "Restoring configuration..."
    rm -rf "$CONFIG_DIR"
    cp -r "${BACKUP_PATH}/config" "$CONFIG_DIR"
    chown -R eco-iot-gw:eco-iot-gw "$CONFIG_DIR"
fi

# Restore backend
if [ -d "${BACKUP_PATH}/backend" ]; then
    log "Restoring backend..."
    rm -rf "${INSTALL_DIR}/backend"
    cp -r "${BACKUP_PATH}/backend" "${INSTALL_DIR}/backend"
    chown -R eco-iot-gw:eco-iot-gw "${INSTALL_DIR}/backend"
fi

# Restore frontend
if [ -d "${BACKUP_PATH}/frontend" ]; then
    log "Restoring frontend..."
    rm -rf /var/www/eco-iot-gw
    cp -r "${BACKUP_PATH}/frontend/dist" /var/www/eco-iot-gw || true
    chown -R www-data:www-data /var/www/eco-iot-gw
fi

# Start services
log "Starting services..."
systemctl start eco-iot-gw-backend

# Reload nginx
systemctl reload nginx

log "Rollback completed"

# Show restored version
if [ -f "${BACKUP_PATH}/version.txt" ]; then
    VERSION=$(cat "${BACKUP_PATH}/version.txt")
    log "Restored version: $VERSION"
fi

exit 0
