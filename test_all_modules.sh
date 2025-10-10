#!/bin/bash
# Comprehensive test of all module device detection improvements

echo "=========================================="
echo "MODULE DEVICE DETECTION TEST"
echo "=========================================="
echo
echo "This script tests both camera and eye tracker modules"
echo "to verify proper device detection and graceful handling."
echo

cd /home/rs-pi-2/Development/RPi_Logger

echo "1. Testing Camera Module (5s timeout)..."
echo "----------------------------------------"
echo '{"command":"get_status"}' | timeout 8 /home/rs-pi-2/.local/bin/uv run Modules/Cameras/main_camera.py --mode slave --discovery-timeout 5 --discovery-retry 1 --log-level warning 2>/dev/null | grep -E "status|cameras" | head -5
echo

echo "2. Testing Eye Tracker Module (5s retry delay)..."
echo "------------------------------------------------"
timeout 8 /home/rs-pi-2/.local/bin/uv run Modules/EyeTracker/main_eye_tracker.py --retry-delay 5 --reconnect-interval 5 --log-level warning 2>&1 | grep -E "status|device|verif" | head -10
echo

echo "3. Testing Unified Master Controller..."
echo "----------------------------------------"
echo "quit" | timeout 15 /home/rs-pi-2/.local/bin/uv run unified_master.py --camera-discovery-timeout 3 --camera-discovery-retry 1 --tracker-retry-delay 5 --tracker-reconnect-interval 5 --allow-partial --log-level warning 2>&1 | grep -E "Starting|found|initialized|SUMMARY" | head -20

echo
echo "=========================================="
echo "TEST COMPLETE"
echo "=========================================="
echo
echo "Summary of improvements:"
echo "- Cameras: Detection with configurable timeout"
echo "- Eye Tracker: Phantom device detection and verification"
echo "- Both modules: Graceful exit when devices not found"
echo "- Master controller: Continues with available devices only"
