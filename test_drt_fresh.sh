#!/bin/bash
# Force fresh start of DRT module with no cache

# Kill any existing DRT processes
echo "Killing existing DRT processes..."
pkill -9 -f "main_DRT.py" 2>/dev/null
sleep 1

# Clear Python cache
echo "Clearing Python cache..."
find /home/rs-pi-2/Development/RPi_Logger -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find /home/rs-pi-2/Development/RPi_Logger -type f -name "*.pyc" -delete 2>/dev/null

# Clear log
echo "Clearing log..."
rm -f /home/rs-pi-2/Development/RPi_Logger/Modules/DRT/logs/drt.log

# Start DRT with Python -B flag (no bytecode)
echo "Starting DRT module..."
cd /home/rs-pi-2/Development/RPi_Logger
PYTHONDONTWRITEBYTECODE=1 DISPLAY=:0 uv run python -B Modules/DRT/main_DRT.py --session-dir data &

echo "DRT started. Check logs in a few seconds:"
echo "  tail -f Modules/DRT/logs/drt.log"
