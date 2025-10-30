#!/bin/bash
################################################################################
# RPi Logger Auto-Start Uninstallation Script
#
# Removes systemd service and disables automatic startup.
################################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

SERVICE_NAME="rpi-logger.service"
SYSTEMD_DIR="/etc/systemd/system"
SYSTEMD_SERVICE="$SYSTEMD_DIR/$SERVICE_NAME"

echo "================================================"
echo "RPi Logger Auto-Start Uninstallation"
echo "================================================"
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo -e "${RED}ERROR: Do not run this script as root/sudo${NC}"
    echo "The script will prompt for sudo password when needed"
    exit 1
fi

# Check if service is installed
if [ ! -f "$SYSTEMD_SERVICE" ]; then
    echo -e "${YELLOW}Service not installed. Nothing to uninstall.${NC}"
    exit 0
fi

echo "This will:"
echo "  - Stop the rpi-logger service"
echo "  - Disable auto-start on boot"
echo "  - Remove the systemd service file"
echo ""
read -p "Continue? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Uninstall cancelled."
    exit 1
fi

echo ""
echo "1. Stopping service..."
sudo systemctl stop $SERVICE_NAME 2>/dev/null || echo "Service not running"
echo -e "${GREEN}✓${NC} Service stopped"

echo ""
echo "2. Disabling auto-start..."
sudo systemctl disable $SERVICE_NAME 2>/dev/null || echo "Service not enabled"
echo -e "${GREEN}✓${NC} Auto-start disabled"

echo ""
echo "3. Removing service file..."
sudo rm -f "$SYSTEMD_SERVICE"
echo -e "${GREEN}✓${NC} Service file removed"

echo ""
echo "4. Reloading systemd daemon..."
sudo systemctl daemon-reload
echo -e "${GREEN}✓${NC} Systemd reloaded"

echo ""
echo "================================================"
echo -e "${GREEN}Uninstallation Complete!${NC}"
echo "================================================"
echo ""
echo "The RPi Logger will no longer start automatically on boot."
echo ""
echo "You can still run it manually:"
echo "  python3 main_logger.py --mode gui"
echo "  python3 main_logger.py --mode interactive"
echo ""
echo "To re-install auto-start:"
echo "  ./install_autostart.sh"
echo ""
echo "================================================"
