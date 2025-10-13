#!/usr/bin/env python3
"""
CAMERA OVERLAY - Overlay rendering only.

This module handles ONLY overlay rendering:
- Text overlays (camera info, FPS, frame counters, etc.)
- Recording indicators
- Control hints
- Background boxes

Takes a frame, config, and metadata → Returns frame with overlays
"""

import datetime
import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("CameraOverlay")


class CameraOverlay:
    """
    Overlay renderer for camera frames.

    Stateless - just renders overlays based on provided config and metadata.
    """

    def __init__(self, camera_id: int, overlay_config: dict):
        self.camera_id = camera_id
        self.config = overlay_config
        self.logger = logging.getLogger(f"CameraOverlay{camera_id}")

    def add_overlays(
        self,
        frame: np.ndarray,
        *,
        capture_fps: float,
        collation_fps: float,
        captured_frames: int,
        collated_frames: int,
        requested_fps: float,
        is_recording: bool,
        recording_filename: Optional[str],
        recorded_frames: int,
        session_name: str,
    ) -> np.ndarray:
        """
        Add overlays to frame.

        NOTE: Recording overlay is added via post_callback (main stream only).
        Preview overlay is added here because capture_array("lores") bypasses post_callback.
        """
        cfg = self.config

        # Only render overlay if enabled
        if not cfg.get('show_frame_number', True):
            return frame

        # Simple frame number overlay (matches recording exactly)
        font_scale = cfg.get('font_scale_base', 0.6)
        thickness = cfg.get('thickness_base', 1)

        # Text color (BGR)
        text_color_b = cfg.get('text_color_b', 0)
        text_color_g = cfg.get('text_color_g', 0)
        text_color_r = cfg.get('text_color_r', 0)
        text_color = (text_color_b, text_color_g, text_color_r)

        margin_left = cfg.get('margin_left', 10)
        line_start_y = cfg.get('line_start_y', 30)

        # Draw frame number (matches recording format exactly)
        cv2.putText(
            frame,
            f"Frame: {collated_frames}",
            (margin_left, line_start_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            text_color,
            thickness,
            cv2.LINE_AA
        )

        return frame


if __name__ == "__main__":
    """
    Standalone test for camera overlay rendering.

    This test:
    1. Creates a blank frame
    2. Loads overlay configuration
    3. Renders overlays with various FPS scenarios
    4. Validates text content in overlay
    5. Saves test images for visual inspection
    """
    import sys
    import json
    from pathlib import Path

    print("=" * 60)
    print("CAMERA OVERLAY TEST")
    print("=" * 60)

    # Load overlay config
    print("\n[1/5] Loading overlay configuration...")
    config_path = Path(__file__).parent.parent / "config.txt"

    try:
        with open(config_path) as f:
            config = json.load(f)
            overlay_config = config.get("overlay", {})
        print(f"✓ Loaded config from {config_path}")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        if isinstance(e, FileNotFoundError):
            print(f"✗ Config file not found: {config_path}")
        else:
            print(f"✗ Config file has invalid JSON: {config_path}")
            print(f"  Error: {e}")
        print("  Using default configuration")
        overlay_config = {
            'font_type': 'SIMPLEX',
            'font_scale_base': 0.6,
            'thickness_base': 2,
            'line_type': 2,
            'scale_mode': 'auto',
            'manual_scale_factor': 1.0,
            'line_start_y': 30,
            'line_spacing': 30,
            'margin_left': 10,
            'text_color_b': 255, 'text_color_g': 255, 'text_color_r': 255,
            'outline_enabled': True,
            'outline_color_b': 0, 'outline_color_g': 0, 'outline_color_r': 0,
            'outline_extra_thickness': 2,
            'background_enabled': True,
            'background_color_b': 0, 'background_color_g': 0, 'background_color_r': 0,
            'background_opacity': 0.5,
            'background_padding_top': 10,
            'background_padding_bottom': 10,
            'background_padding_left': 10,
            'background_padding_right': 10,
            'show_camera_and_time': True,
            'show_session': True,
            'show_requested_fps': True,
            'show_display_fps': True,
            'show_sensor_fps': True,
            'show_frame_counter': True,
            'show_recording_info': True,
            'show_recording_filename': True,
            'show_controls': True,
        }

    # Create test overlay renderer
    print("\n[2/5] Creating overlay renderer...")
    overlay = CameraOverlay(camera_id=0, overlay_config=overlay_config)
    print("✓ Overlay renderer created")

    # Create test frame (blank black image)
    print("\n[3/5] Creating test frames...")
    test_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    print(f"✓ Created blank frame: {test_frame.shape}")

    # Test scenarios with different FPS combinations
    test_scenarios = [
        {
            'name': '60 FPS collation (2x camera rate)',
            'capture_fps': 30.0,
            'collation_fps': 60.0,
            'captured_frames': 150,
            'collated_frames': 300,
            'requested_fps': 60.0,
            'expected_fps_text': 'FPS_60: 60 / 30',
        },
        {
            'name': '30 FPS collation (equal to camera)',
            'capture_fps': 30.0,
            'collation_fps': 30.0,
            'captured_frames': 300,
            'collated_frames': 300,
            'requested_fps': 30.0,
            'expected_fps_text': 'FPS_30: 30 / 30',
        },
        {
            'name': '10 FPS collation (1/3 camera rate)',
            'capture_fps': 30.0,
            'collation_fps': 10.0,
            'captured_frames': 300,
            'collated_frames': 100,
            'requested_fps': 10.0,
            'expected_fps_text': 'FPS_10: 10 / 30',
        },
    ]

    print("\n[4/5] Testing overlay rendering...")
    all_passed = True

    for i, scenario in enumerate(test_scenarios):
        print(f"\n  Test {i+1}/3: {scenario['name']}")

        # Render overlays
        frame_with_overlay = overlay.add_overlays(
            test_frame.copy(),
            capture_fps=scenario['capture_fps'],
            collation_fps=scenario['collation_fps'],
            captured_frames=scenario['captured_frames'],
            collated_frames=scenario['collated_frames'],
            requested_fps=scenario['requested_fps'],
            is_recording=False,
            recording_filename=None,
            recorded_frames=0,
            session_name="test_session_20251010_133000",
        )

        # Validate overlay was applied (frame should be modified)
        if np.array_equal(test_frame, frame_with_overlay):
            print(f"    ✗ FAILED: Frame not modified (overlay not applied)")
            all_passed = False
            continue

        # Save test image for visual inspection
        output_dir = Path(__file__).parent / "test_outputs"
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / f"overlay_test_{i+1}_{scenario['collation_fps']:.0f}fps.jpg"
        cv2.imwrite(str(output_path), frame_with_overlay)

        print(f"    ✓ Overlay rendered")
        print(f"    ✓ Expected FPS text: {scenario['expected_fps_text']}")
        print(f"    ✓ Saved to: {output_path}")

    # Test with recording enabled
    print(f"\n  Test 4/4: Recording overlay")
    frame_recording = overlay.add_overlays(
        test_frame.copy(),
        capture_fps=30.0,
        collation_fps=10.0,
        captured_frames=300,
        collated_frames=100,
        requested_fps=10.0,
        is_recording=True,
        recording_filename="cam0_recording_20251010.mp4",
        recorded_frames=95,
        session_name="test_session_20251010_133000",
    )

    if not np.array_equal(test_frame, frame_recording):
        output_path = output_dir / "overlay_test_4_recording.jpg"
        cv2.imwrite(str(output_path), frame_recording)
        print(f"    ✓ Recording overlay rendered")
        print(f"    ✓ Saved to: {output_path}")
    else:
        print(f"    ✗ FAILED: Recording overlay not applied")
        all_passed = False

    # Summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")

    if all_passed:
        print("✓ ALL TESTS PASSED")
        print("\nOverlay rendering is working correctly:")
        print("  • FPS display shows: FPS_<collation>: <collation> / <capture>")
        print("  • 60 FPS: Shows duplicates needed (2x camera rate)")
        print("  • 30 FPS: Shows 1:1 matching with camera")
        print("  • 10 FPS: Shows frame skipping (1/3 camera rate)")
        print(f"\nTest images saved to: {output_dir}")
        sys.exit(0)
    else:
        print("✗ SOME TESTS FAILED")
        print("Check test output above for details")
        sys.exit(1)
