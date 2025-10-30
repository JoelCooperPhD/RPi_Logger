#!/bin/bash
################################################################################
# RPi Logger Auto-Start Installation Script
#
# Installs systemd service for automatic startup on boot.
################################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Determine project directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

SERVICE_NAME="rpi-logger.service"
SERVICE_FILE="$SCRIPT_DIR/$SERVICE_NAME"
SYSTEMD_DIR="/etc/systemd/system"
SYSTEMD_SERVICE="$SYSTEMD_DIR/$SERVICE_NAME"

echo "================================================"
echo "RPi Logger Auto-Start Installation"
echo "================================================"
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo -e "${RED}ERROR: Do not run this script as root/sudo${NC}"
    echo "The script will prompt for sudo password when needed"
    exit 1
fi

# Check if service file exists
if [ ! -f "$SERVICE_FILE" ]; then
    echo -e "${RED}ERROR: Service file not found: $SERVICE_FILE${NC}"
    exit 1
fi

# Check if wrapper script exists
if [ ! -f "$SCRIPT_DIR/start_logger.sh" ]; then
    echo -e "${RED}ERROR: Wrapper script not found: $SCRIPT_DIR/start_logger.sh${NC}"
    exit 1
fi

# Make wrapper script executable
chmod +x "$SCRIPT_DIR/start_logger.sh"

echo "1. Copying service file to systemd..."
sudo cp "$SERVICE_FILE" "$SYSTEMD_SERVICE"
echo -e "${GREEN}✓${NC} Service file copied"

echo ""
echo "2. Reloading systemd daemon..."
sudo systemctl daemon-reload
echo -e "${GREEN}✓${NC} Systemd reloaded"

echo ""
echo "3. Enabling service for auto-start on boot..."
sudo systemctl enable $SERVICE_NAME
echo -e "${GREEN}✓${NC} Service enabled"

echo ""
echo "================================================"
echo -e "${GREEN}Installation Complete!${NC}"
echo "================================================"
echo ""
echo "Service status:"
systemctl status $SERVICE_NAME --no-pager || true

echo ""
echo "================================================"
echo "Next Steps:"
echo "================================================"
echo ""
echo "1. Configure auto-start mode in config.txt:"
echo "   auto_start_mode = gui          # or 'interactive'"
echo ""
echo "2. Enable modules you want to auto-start:"
echo "   Edit Modules/*/config.txt and set: enabled = true"
echo ""
echo "3. Start the service now (or reboot):"
echo "   sudo systemctl start $SERVICE_NAME"
echo ""
echo "4. Check service status:"
echo "   systemctl status $SERVICE_NAME"
echo ""
echo "5. View logs:"
echo "   journalctl -u $SERVICE_NAME -f"
echo ""
echo "To disable auto-start:"
echo "   sudo systemctl disable $SERVICE_NAME"
echo ""
echo "To uninstall completely:"
echo "   ./uninstall_autostart.sh"
echo ""
echo "================================================"
