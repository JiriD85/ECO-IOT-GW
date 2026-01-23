#!/bin/bash
#
# ECO-IOT-GW Uninstall Script
#
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

INSTALL_DIR="/opt/eco-iot-gw"
CONFIG_DIR="/etc/eco-iot-gw"
LOG_DIR="/var/log/eco-iot-gw"
DATA_DIR="/var/lib/eco-iot-gw"
BACKEND_USER="eco-iot-gw"

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root"
        exit 1
    fi
}

confirm() {
    read -p "Are you sure you want to uninstall ECO-IOT-GW? This will remove all data. (y/N): " response
    case "$response" in
        [yY][eE][sS]|[yY])
            return 0
            ;;
        *)
            log_info "Uninstall cancelled"
            exit 0
            ;;
    esac
}

stop_services() {
    log_info "Stopping services..."
    systemctl stop eco-iot-gw-backend || true
    systemctl stop eco-iot-gw-wifi-ap || true
    systemctl disable eco-iot-gw-backend || true
    systemctl disable eco-iot-gw-wifi-ap || true
}

remove_services() {
    log_info "Removing systemd services..."
    rm -f /etc/systemd/system/eco-iot-gw-*.service
    systemctl daemon-reload
}

remove_files() {
    log_info "Removing files..."
    rm -rf "$INSTALL_DIR"
    rm -rf "$CONFIG_DIR"
    rm -rf "$LOG_DIR"
    rm -rf "$DATA_DIR"
    rm -rf /var/www/eco-iot-gw
    rm -f /etc/nginx/sites-enabled/eco-iot-gw.conf
    rm -f /etc/nginx/sites-available/eco-iot-gw.conf
    rm -rf /etc/ssl/eco-iot-gw
}

remove_user() {
    log_info "Removing user..."
    userdel "$BACKEND_USER" 2>/dev/null || true
}

reload_nginx() {
    log_info "Reloading nginx..."
    # Restore default site
    ln -sf /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default 2>/dev/null || true
    nginx -t && systemctl reload nginx || log_warn "Failed to reload nginx"
}

main() {
    log_info "ECO-IOT-GW Uninstall Script"

    check_root
    confirm

    stop_services
    remove_services
    remove_files
    remove_user
    reload_nginx

    echo ""
    echo -e "${GREEN}ECO-IOT-GW has been uninstalled.${NC}"
    echo ""
    log_warn "Note: Docker, nginx, and other system packages were not removed."
    log_warn "To remove them, run: apt remove docker-ce nginx"
}

main "$@"
