#!/bin/bash
#
# ECO-IOT-GW Installation Script
# IoT Gateway for Raspberry Pi (Pi4, Pi5, CM4)
#
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
INSTALL_DIR="/opt/eco-iot-gw"
CONFIG_DIR="/etc/eco-iot-gw"
LOG_DIR="/var/log/eco-iot-gw"
DATA_DIR="/var/lib/eco-iot-gw"
BACKEND_USER="eco-iot-gw"
FRONTEND_PORT=443
BACKEND_PORT=8000

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# Check if running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root"
        exit 1
    fi
}

# Detect Raspberry Pi model
detect_pi_model() {
    log_step "Detecting Raspberry Pi model..."

    if [ -f /proc/device-tree/model ]; then
        PI_MODEL=$(cat /proc/device-tree/model)
        log_info "Detected: $PI_MODEL"

        if echo "$PI_MODEL" | grep -q "Raspberry Pi 5"; then
            PI_TYPE="pi5"
        elif echo "$PI_MODEL" | grep -q "Raspberry Pi 4"; then
            PI_TYPE="pi4"
        elif echo "$PI_MODEL" | grep -q "Compute Module 4"; then
            PI_TYPE="cm4"
        else
            log_warn "Unknown model, assuming Pi4 compatibility"
            PI_TYPE="pi4"
        fi
    else
        log_warn "Not running on Raspberry Pi, continuing anyway..."
        PI_TYPE="generic"
    fi
}

# Update system packages
update_system() {
    log_step "Updating system packages..."
    apt-get update
    apt-get upgrade -y
}

# Install base dependencies
install_base_packages() {
    log_step "Installing base packages..."
    apt-get install -y \
        curl \
        wget \
        git \
        vim \
        htop \
        tmux \
        ufw \
        fail2ban \
        ca-certificates \
        gnupg \
        lsb-release \
        apt-transport-https \
        build-essential \
        libffi-dev \
        libssl-dev \
        sqlite3
}

# Install Python 3.11+
install_python() {
    log_step "Installing Python 3.11+..."

    # Debian 13 (trixie) uses Python 3.12, Debian 12 uses Python 3.11
    # Just use system Python 3 which is >= 3.11 on modern systems
    if command -v python3 &> /dev/null; then
        PY_VERSION=$(python3 --version | cut -d' ' -f2)
        log_info "Found Python $PY_VERSION"
        PYTHON_CMD="python3"
    else
        log_error "Python 3 not found"
        exit 1
    fi

    # Install Python development packages and pip
    apt-get install -y python3-pip python3-venv python3-dev

    log_info "Python configured: $PYTHON_CMD"
}

# Install Node.js 20 LTS
install_nodejs() {
    log_step "Installing Node.js 20 LTS..."

    if command -v node &> /dev/null; then
        NODE_VERSION=$(node --version | cut -d'v' -f2 | cut -d'.' -f1)
        if [ "$NODE_VERSION" -ge 20 ]; then
            log_info "Node.js $NODE_VERSION already installed"
            return
        fi
    fi

    # Add NodeSource repository
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs

    log_info "Node.js $(node --version) installed"
}

# Install Docker
install_docker() {
    log_step "Installing Docker..."

    if command -v docker &> /dev/null; then
        log_info "Docker already installed"
    else
        # Add Docker's official GPG key
        install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        chmod a+r /etc/apt/keyrings/docker.gpg

        # Add the repository
        echo \
            "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
            $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
            tee /etc/apt/sources.list.d/docker.list > /dev/null

        apt-get update
        apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    fi

    # Enable and start Docker
    systemctl enable docker
    systemctl start docker

    log_info "Docker $(docker --version) installed"
}

# Install Nginx
install_nginx() {
    log_step "Installing Nginx..."
    apt-get install -y nginx
    systemctl enable nginx
}

# Install VPN tools
install_vpn_tools() {
    log_step "Installing VPN tools..."

    # OpenVPN
    apt-get install -y openvpn

    # WireGuard
    apt-get install -y wireguard wireguard-tools

    # Tailscale
    curl -fsSL https://tailscale.com/install.sh | sh

    log_info "VPN tools installed (OpenVPN, WireGuard, Tailscale)"
}

# Install Modem tools (Quectel)
install_modem_tools() {
    log_step "Installing Modem tools..."
    apt-get install -y \
        modemmanager \
        network-manager \
        libqmi-utils \
        libmbim-utils \
        usb-modeswitch \
        minicom \
        picocom

    # Enable NetworkManager
    systemctl enable NetworkManager
    systemctl start NetworkManager

    log_info "Modem tools installed"
}

# Setup Hardware Watchdog
setup_watchdog() {
    log_step "Setting up Hardware Watchdog..."

    # Install watchdog
    apt-get install -y watchdog

    # Enable bcm2835_wdt module
    if ! grep -q "bcm2835_wdt" /etc/modules; then
        echo "bcm2835_wdt" >> /etc/modules
    fi

    # Configure watchdog
    cat > /etc/watchdog.conf << 'EOF'
watchdog-device = /dev/watchdog
watchdog-timeout = 15
max-load-1 = 24
min-memory = 1
EOF

    systemctl enable watchdog

    log_info "Hardware Watchdog configured"
}

# Create system user
create_user() {
    log_step "Creating system user..."

    if id "$BACKEND_USER" &>/dev/null; then
        log_info "User $BACKEND_USER already exists"
    else
        useradd -r -s /bin/false -d "$INSTALL_DIR" "$BACKEND_USER"
        log_info "User $BACKEND_USER created"
    fi

    # Add user to docker group
    usermod -aG docker "$BACKEND_USER"
}

# Create directories
create_directories() {
    log_step "Creating directories..."

    mkdir -p "$INSTALL_DIR"
    mkdir -p "$CONFIG_DIR"
    mkdir -p "$LOG_DIR"
    mkdir -p "$DATA_DIR"
    mkdir -p "$DATA_DIR/docker-compose"
    mkdir -p "$DATA_DIR/vpn"
    mkdir -p "$DATA_DIR/audit"

    chown -R "$BACKEND_USER:$BACKEND_USER" "$INSTALL_DIR"
    chown -R "$BACKEND_USER:$BACKEND_USER" "$LOG_DIR"
    chown -R "$BACKEND_USER:$BACKEND_USER" "$DATA_DIR"

    log_info "Directories created"
}

# Generate SSL certificate
generate_ssl_cert() {
    log_step "Generating self-signed SSL certificate..."

    SSL_DIR="/etc/ssl/eco-iot-gw"
    mkdir -p "$SSL_DIR"

    if [ ! -f "$SSL_DIR/server.crt" ]; then
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout "$SSL_DIR/server.key" \
            -out "$SSL_DIR/server.crt" \
            -subj "/C=DE/ST=Bavaria/L=Munich/O=ECO-IOT/CN=eco-iot-gw.local"

        chmod 600 "$SSL_DIR/server.key"
        log_info "SSL certificate generated"
    else
        log_info "SSL certificate already exists"
    fi
}

# Configure Nginx
configure_nginx() {
    log_step "Configuring Nginx..."

    # Copy nginx configuration
    cp "$INSTALL_DIR/config/nginx/eco-iot-gw.conf" /etc/nginx/sites-available/

    # Enable site
    ln -sf /etc/nginx/sites-available/eco-iot-gw.conf /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default

    # Test and reload
    nginx -t
    systemctl reload nginx

    log_info "Nginx configured"
}

# Configure Firewall
configure_firewall() {
    log_step "Configuring Firewall..."

    # Reset UFW
    ufw --force reset

    # Default policies
    ufw default deny incoming
    ufw default allow outgoing

    # Allow SSH (with rate limiting)
    ufw limit 22/tcp

    # Allow HTTPS
    ufw allow 443/tcp

    # Allow HTTP (redirect to HTTPS)
    ufw allow 80/tcp

    # Enable UFW
    ufw --force enable

    log_info "Firewall configured"
}

# Configure Fail2ban
configure_fail2ban() {
    log_step "Configuring Fail2ban..."

    cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime = 900
findtime = 600
maxretry = 5

[sshd]
enabled = true

[nginx-http-auth]
enabled = true

[eco-iot-gw]
enabled = true
port = https
filter = eco-iot-gw
logpath = /var/log/eco-iot-gw/access.log
maxretry = 5
EOF

    cat > /etc/fail2ban/filter.d/eco-iot-gw.conf << 'EOF'
[Definition]
failregex = ^<HOST> .* "POST /api/auth/login.*" 401
ignoreregex =
EOF

    systemctl enable fail2ban
    systemctl restart fail2ban

    log_info "Fail2ban configured"
}

# Install Backend
install_backend() {
    log_step "Installing Backend..."

    # Copy backend files
    cp -r "$SCRIPT_DIR/../backend" "$INSTALL_DIR/"

    # Create virtual environment
    cd "$INSTALL_DIR/backend"
    $PYTHON_CMD -m venv venv
    source venv/bin/activate

    # Install dependencies
    pip install --upgrade pip
    pip install -r requirements.txt

    deactivate

    chown -R "$BACKEND_USER:$BACKEND_USER" "$INSTALL_DIR/backend"

    log_info "Backend installed"
}

# Install Frontend
install_frontend() {
    log_step "Installing Frontend..."

    # Copy frontend files
    cp -r "$SCRIPT_DIR/../frontend" "$INSTALL_DIR/"

    cd "$INSTALL_DIR/frontend"

    # Install dependencies and build
    npm install
    npm run build

    # Copy built files to nginx serve directory
    mkdir -p /var/www/eco-iot-gw
    cp -r dist/* /var/www/eco-iot-gw/

    chown -R www-data:www-data /var/www/eco-iot-gw

    log_info "Frontend installed"
}

# Install systemd services
install_services() {
    log_step "Installing systemd services..."

    cp "$SCRIPT_DIR/../systemd/"*.service /etc/systemd/system/

    systemctl daemon-reload
    systemctl enable eco-iot-gw-backend.service
    systemctl start eco-iot-gw-backend.service

    # Install failover daemon service
    log_info "Installing failover daemon service..."
    systemctl enable eco-iot-gw-failover.service
    systemctl start eco-iot-gw-failover.service

    log_info "Systemd services installed"
}

# Copy configuration files
copy_configs() {
    log_step "Copying configuration files..."

    cp -r "$SCRIPT_DIR/../config/"* "$CONFIG_DIR/"

    log_info "Configuration files copied"
}

# Generate initial secrets
generate_secrets() {
    log_step "Generating secrets..."

    SECRET_FILE="$CONFIG_DIR/secrets.env"

    if [ ! -f "$SECRET_FILE" ]; then
        JWT_SECRET=$(openssl rand -hex 32)
        AES_KEY=$(openssl rand -hex 32)
        ADMIN_PASSWORD=$(openssl rand -base64 12)

        cat > "$SECRET_FILE" << EOF
JWT_SECRET=$JWT_SECRET
AES_KEY=$AES_KEY
ADMIN_PASSWORD=$ADMIN_PASSWORD
EOF

        chmod 600 "$SECRET_FILE"
        chown "$BACKEND_USER:$BACKEND_USER" "$SECRET_FILE"

        log_info "Secrets generated"
        log_warn "Initial admin password: $ADMIN_PASSWORD"
        log_warn "Please save this password and change it after first login!"
    else
        log_info "Secrets file already exists"
    fi
}

# Print completion message
print_completion() {
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  ECO-IOT-GW Installation Complete!    ${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo "Access the web interface at:"
    echo "  https://$(hostname -I | awk '{print $1}')"
    echo ""
    echo "Default credentials:"
    echo "  Username: admin"
    echo "  Password: See $CONFIG_DIR/secrets.env"
    echo ""
    echo "Services running:"
    echo "  - eco-iot-gw-backend (API server)"
    echo "  - eco-iot-gw-failover (Network failover daemon)"
    echo ""
    echo "Checking service status..."
    systemctl status eco-iot-gw-backend.service --no-pager | head -3
    systemctl status eco-iot-gw-failover.service --no-pager | head -3
    echo ""
    echo "WLAN AP will be available as:"
    echo "  SSID: ECO-IOT-GW-$(cat /sys/class/net/wlan0/address 2>/dev/null | tr -d ':' | tail -c 5 || echo 'XXXX')"
    echo ""
    log_warn "Please change the default password after first login!"
}

# Main installation
main() {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    log_info "Starting ECO-IOT-GW installation..."

    check_root
    detect_pi_model
    update_system
    install_base_packages
    install_python
    install_nodejs
    install_docker
    install_nginx
    install_vpn_tools
    install_modem_tools
    setup_watchdog
    create_user
    create_directories
    generate_ssl_cert
    copy_configs
    configure_nginx
    configure_firewall
    configure_fail2ban
    install_backend
    install_frontend
    install_services
    generate_secrets

    print_completion
}

# Run main
main "$@"
