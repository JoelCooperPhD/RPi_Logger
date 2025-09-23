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
echo '{"command":"get_status"}' | timeout 8 /home/rs-pi-2/.local/bin/uv run Modules/Cameras/camera_module.py --slave --timeout 5 2>/dev/null | grep -E "status|cameras" | head -5
echo

echo "2. Testing Eye Tracker Module (5s timeout)..."
echo "----------------------------------------------"
timeout 8 /home/rs-pi-2/.local/bin/uv run Modules/EyeTracker/fixation_recorder.py --slave --timeout 5 2>&1 | grep -E "status|device|verif" | head -10
echo

echo "3. Testing Unified Master Controller..."
echo "----------------------------------------"
echo "quit" | timeout 15 /home/rs-pi-2/.local/bin/uv run unified_master.py --camera-timeout 3 --tracker-timeout 5 2>&1 | grep -E "Starting|found|initialized|SUMMARY" | head -20

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