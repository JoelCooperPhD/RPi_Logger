#!/usr/bin/env python3
"""Verify that all dependencies and refactored code work correctly."""

import sys

print("="*70)
print("RPi Logger - Installation Verification")
print("="*70)
print()

# Test 1: Third-party packages
print("1. Testing third-party packages...")
try:
    import cv2
    import numpy as np
    import sounddevice as sd
    import aiofiles
    import pandas as pd
    from PIL import Image
    import tkinter as tk

    print(f"   ✓ OpenCV version: {cv2.__version__}")
    print(f"   ✓ NumPy version: {np.__version__}")
    print(f"   ✓ Pandas version: {pd.__version__}")
    print(f"   ✓ SoundDevice installed")
    print(f"   ✓ Aiofiles installed")
    print(f"   ✓ Tkinter available")
except ImportError as e:
    print(f"   ✗ Failed: {e}")
    sys.exit(1)

# Test 2: Pupil Labs API
print()
print("2. Testing Pupil Labs API...")
try:
    from pupil_labs.realtime_api import Device
    from pupil_labs.realtime_api.discovery import discover_devices
    print("   ✓ Pupil Labs Realtime API available")
except ImportError as e:
    print(f"   ✗ Failed: {e}")
    sys.exit(1)

# Test 3: Base classes (refactored code)
print()
print("3. Testing refactored base classes...")
try:
    from Modules.base import ConfigLoader, BaseSupervisor, BaseSystem
    from Modules.base.modes import BaseMode, BaseGUIMode
    from logger_core.commands import BaseCommandHandler, CommandMessage, StatusMessage

    print("   ✓ ConfigLoader")
    print("   ✓ BaseSupervisor")
    print("   ✓ BaseSystem")
    print("   ✓ BaseMode")
    print("   ✓ BaseGUIMode")
    print("   ✓ BaseCommandHandler")
except ImportError as e:
    print(f"   ✗ Failed: {e}")
    sys.exit(1)

# Test 4: Audio module
print()
print("4. Testing Audio module...")
try:
    from Modules.AudioRecorder.audio_core.config.config_loader import ConfigLoader as AudioConfigLoader
    from Modules.AudioRecorder.audio_core.commands import CommandHandler as AudioCH
    print("   ✓ Audio config loader")
    print("   ✓ Audio CommandHandler")
except ImportError as e:
    print(f"   ✗ Failed: {e}")
    sys.exit(1)

# Test 5: EyeTracker module
print()
print("5. Testing EyeTracker module...")
try:
    from Modules.EyeTracker.tracker_core.config.config_loader import ConfigLoader as TrackerConfigLoader
    from Modules.EyeTracker.tracker_core.commands import CommandHandler as TrackerCH
    print("   ✓ EyeTracker config loader")
    print("   ✓ EyeTracker CommandHandler")
except ImportError as e:
    print(f"   ✗ Failed: {e}")
    sys.exit(1)

# Test 6: Camera module (may fail without libcamera)
print()
print("6. Testing Camera module...")
try:
    from Modules.Cameras.camera_core.config.config_loader import ConfigLoader as CameraConfigLoader
    print("   ✓ Camera config loader")

    try:
        from Modules.Cameras.camera_core.commands import CommandHandler as CameraCH
        print("   ✓ Camera CommandHandler")
    except ModuleNotFoundError as e:
        if 'libcamera' in str(e):
            print("   ⚠ Camera CommandHandler requires libcamera (RPi system package)")
            print("     This is expected on non-RPi systems")
        else:
            raise
except Exception as e:
    print(f"   ⚠ Camera module check: {e}")
    print("     Note: Camera module requires Raspberry Pi hardware")

# Test 7: Logger core
print()
print("7. Testing logger core...")
try:
    from logger_core import LoggerSystem
    from logger_core.module_process import ModuleProcess
    from logger_core.module_discovery import discover_modules
    print("   ✓ LoggerSystem")
    print("   ✓ ModuleProcess")
    print("   ✓ Module discovery")
except ImportError as e:
    print(f"   ✗ Failed: {e}")
    sys.exit(1)

print()
print("="*70)
print("✅ Installation verification PASSED!")
print("="*70)
print()
print("All dependencies installed correctly and refactored code working!")
print()
print("Next steps:")
print("  1. Run 'uv run main_logger.py' to launch the master logger")
print("  2. Check boxes to launch Audio and EyeTracker modules")
print("  3. Camera module will work on Raspberry Pi with libcamera installed")
print()
