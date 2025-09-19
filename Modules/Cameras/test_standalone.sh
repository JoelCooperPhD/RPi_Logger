#!/bin/bash
# Test script for camera_module.py in standalone mode

echo "Camera Module Standalone Tests"
echo "=============================="

# Make recordings directory
mkdir -p test_recordings

echo ""
echo "Test 1: Basic 10-second recording at 1080p30"
echo "--------------------------------------------"
python3 camera_module.py --resolution 1920x1080 --fps 30 --save-location ./test_recordings --duration 10

echo ""
echo "Test 2: High resolution recording at 4K"
echo "----------------------------------------"
python3 camera_module.py --resolution 3840x2160 --fps 30 --save-location ./test_recordings --duration 5

echo ""
echo "Test 3: Low framerate for long recording"
echo "-----------------------------------------"
python3 camera_module.py --resolution 1920x1080 --fps 15 --save-location ./test_recordings --duration 5

echo ""
echo "Test 4: Using camera 1 (if available)"
echo "--------------------------------------"
python3 camera_module.py --resolution 1920x1080 --fps 30 --camera-id 1 --save-location ./test_recordings --duration 5 2>/dev/null || echo "Camera 1 not available"

echo ""
echo "Tests completed! Check ./test_recordings for output files"
ls -la ./test_recordings/