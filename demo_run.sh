#!/bin/bash
# Demo script to show graceful device handling

echo "=========================================="
echo "DEMONSTRATION: Graceful Device Handling"
echo "=========================================="
echo
echo "This demo shows how the system handles:"
echo "1. Missing devices (eye tracker not connected)"
echo "2. Available devices (cameras connected)"
echo "3. Graceful timeouts and error handling"
echo
echo "Press Enter to start..."
read

cd /home/rs-pi-2/Development/RPi_Logger

echo
echo "Starting unified master controller..."
echo "(Camera timeout: 5s, Eye tracker timeout: 5s)"
echo

# Run in demo mode with updated CLI options
/home/rs-pi-2/.local/bin/uv run unified_master.py --demo \
  --camera-discovery-timeout 5 \
  --camera-discovery-retry 3 \
  --tracker-retry-delay 5 \
  --tracker-reconnect-interval 5 \
  --allow-partial
