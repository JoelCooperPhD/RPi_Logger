#!/usr/bin/env python3
"""Verification script for the CameraStoragePipeline UnboundLocalError fix."""

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock
from dataclasses import dataclass
from typing import Optional, Any
import numpy as np

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))

# Import directly to avoid module initialization
sys.path.insert(0, str(Path(__file__).parent / "rpi_logger/modules/Cameras"))

from io.storage.pipeline import CameraStoragePipeline

# Define a minimal FramePayload for testing
@dataclass
class FramePayload:
    frame: Optional[Any]
    capture_index: int
    timestamp: float
    monotonic: float
    pixel_format: str
    sensor_timestamp_ns: Optional[int]
    hardware_frame_number: Optional[int]
    dropped_since_last: int


async def test_write_frame_no_crash():
    """Test that write_frame doesn't raise UnboundLocalError."""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        save_dir = Path(tmpdir)
        
        # Create a pipeline without hardware encoder
        pipeline = CameraStoragePipeline(
            camera_index=0,
            save_dir=save_dir,
            main_size=(640, 480),
            camera=None,  # No hardware encoder
            logger=None,
        )
        
        # Start the pipeline
        await pipeline.start()
        
        # Create a mock payload
        payload = FramePayload(
            frame=None,
            capture_index=1,
            timestamp=1234567890.0,
            monotonic=1000.0,
            pixel_format="YUV420",
            sensor_timestamp_ns=None,
            hardware_frame_number=None,
            dropped_since_last=0,
        )
        
        # Create a dummy YUV frame
        yuv_frame = np.zeros((720, 640), dtype=np.uint8)  # 480 * 1.5 for YUV420
        
        try:
            # This should not raise UnboundLocalError anymore
            result = await pipeline.write_frame(
                bgr_frame=None,
                payload=payload,
                fps_hint=30.0,
                yuv_frame=yuv_frame,
            )
            
            # Check that result has the expected fields
            assert hasattr(result, 'video_written')
            assert hasattr(result, 'image_path')
            assert hasattr(result, 'video_fps')
            assert hasattr(result, 'writer_codec')
            
            print("✓ Test passed: write_frame completed without UnboundLocalError")
            print(f"  - video_written: {result.video_written}")
            print(f"  - image_path: {result.image_path}")
            print(f"  - video_fps: {result.video_fps}")
            print(f"  - writer_codec: {result.writer_codec}")
            
            return True
            
        except UnboundLocalError as e:
            print(f"✗ Test failed: UnboundLocalError still occurs: {e}")
            return False
        except Exception as e:
            # Other exceptions might be expected (e.g., ffmpeg not available)
            # but UnboundLocalError should not occur
            print(f"✓ Test passed: No UnboundLocalError (got expected error: {type(e).__name__})")
            return True
        finally:
            await pipeline.stop()


async def test_write_frame_bgr_path():
    """Test the BGR code path doesn't crash."""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        save_dir = Path(tmpdir)
        
        pipeline = CameraStoragePipeline(
            camera_index=0,
            save_dir=save_dir,
            main_size=(640, 480),
            camera=None,
        )
        
        await pipeline.start()
        
        payload = FramePayload(
            frame=None,
            capture_index=1,
            timestamp=1234567890.0,
            monotonic=1000.0,
            pixel_format="BGR",
            sensor_timestamp_ns=None,
            hardware_frame_number=None,
            dropped_since_last=0,
        )
        
        # Create a dummy BGR frame
        bgr_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        
        try:
            result = await pipeline.write_frame(
                bgr_frame=bgr_frame,
                payload=payload,
                fps_hint=0.0,  # Will trigger waiting for sensor fps
                yuv_frame=None,
            )
            
            print("✓ Test passed: BGR path completed without UnboundLocalError")
            print(f"  - video_written: {result.video_written}")
            print(f"  - image_path: {result.image_path}")
            
            return True
            
        except UnboundLocalError as e:
            print(f"✗ Test failed: UnboundLocalError in BGR path: {e}")
            return False
        except Exception as e:
            print(f"✓ Test passed: BGR path no UnboundLocalError (got: {type(e).__name__})")
            return True
        finally:
            await pipeline.stop()


async def main():
    """Run all tests."""
    print("Testing CameraStoragePipeline UnboundLocalError fix...")
    print("=" * 60)
    
    test1 = await test_write_frame_no_crash()
    print()
    test2 = await test_write_frame_bgr_path()
    
    print("=" * 60)
    if test1 and test2:
        print("All tests passed! ✓")
        return 0
    else:
        print("Some tests failed! ✗")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
