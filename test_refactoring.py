#!/usr/bin/env python3
"""Test script to diagnose refactoring issues."""

import sys
import traceback

def test_import(module_path, description):
    """Test importing a module."""
    try:
        parts = module_path.split('.')
        if len(parts) > 1:
            exec(f"from {'.'.join(parts[:-1])} import {parts[-1]}")
        else:
            exec(f"import {module_path}")
        print(f"✓ {description}: OK")
        return True
    except Exception as e:
        print(f"✗ {description}: FAILED")
        print(f"  Error: {e}")
        traceback.print_exc()
        return False

print("="*60)
print("REFACTORING DIAGNOSTIC TEST")
print("="*60)
print()

print("Testing base classes...")
test_import("Modules.base.ConfigLoader", "Base ConfigLoader")
test_import("Modules.base.modes.BaseGUIMode", "Base GUI Mode")
test_import("logger_core.commands.base_handler.BaseCommandHandler", "Base Command Handler")
print()

print("Testing module config loaders...")
test_import("Modules.Cameras.camera_core.config.config_loader.ConfigLoader", "Camera ConfigLoader")
test_import("Modules.AudioRecorder.audio_core.config.config_loader.ConfigLoader", "Audio ConfigLoader")
test_import("Modules.EyeTracker.tracker_core.config.config_loader.ConfigLoader", "EyeTracker ConfigLoader")
print()

print("Testing command handlers (requires cv2, sounddevice, etc)...")
camera_ok = test_import("Modules.Cameras.camera_core.commands.CommandHandler", "Camera CommandHandler")
audio_ok = test_import("Modules.AudioRecorder.audio_core.commands.CommandHandler", "Audio CommandHandler")
eye_ok = test_import("Modules.EyeTracker.tracker_core.commands.CommandHandler", "EyeTracker CommandHandler")
print()

if not (camera_ok and audio_ok and eye_ok):
    print("⚠️  Some command handlers failed to import.")
    print("    This may be due to missing dependencies (cv2, sounddevice, etc.)")
    print("    This is normal if dependencies aren't installed in base python.")
    print()

print("Testing with uv environment...")
import subprocess
result = subprocess.run(
    ["uv", "run", "python3", "-c",
     "from Modules.base import ConfigLoader; print('ConfigLoader:', ConfigLoader)"],
    capture_output=True,
    text=True
)
if result.returncode == 0:
    print("✓ ConfigLoader imports in uv environment: OK")
else:
    print("✗ ConfigLoader imports in uv environment: FAILED")
    print(f"  Error: {result.stderr}")
print()

print("="*60)
print("Diagnostic complete!")
print("="*60)
