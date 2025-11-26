#!/usr/bin/env python3
"""
Test script to run CamerasRuntime directly with verbose logging.

This bypasses the vmc supervisor and runs the runtime with a mock context.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Setup verbose logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)


@dataclass
class MockPreferences:
    """Mock preferences for config loading."""
    def get(self, key: str, default: Any = None) -> Any:
        return default

    def snapshot(self) -> dict:
        return {}


@dataclass
class MockModel:
    """Mock model for runtime context."""
    preferences: MockPreferences = field(default_factory=MockPreferences)
    trial_number: int = 1
    trial_label: str = ""


@dataclass
class MockView:
    """Mock view (headless mode)."""
    root: Any = None

    def set_preview_title(self, title: str) -> None:
        print(f"[MOCK VIEW] Preview title: {title}")

    def build_stub_content(self, builder) -> None:
        print("[MOCK VIEW] build_stub_content called (headless)")

    def add_menu(self, name: str) -> None:
        return None


@dataclass
class MockContext:
    """Mock RuntimeContext for standalone testing."""
    module_dir: Path = MODULE_DIR
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("Cameras"))
    model: MockModel = field(default_factory=MockModel)
    view: Optional[MockView] = None  # Set to None for headless


async def main():
    print("=" * 60)
    print("CAMERAS RUNTIME TEST - Direct Launch")
    print("=" * 60)

    from rpi_logger.modules.Cameras.bridge import CamerasRuntime

    ctx = MockContext()
    print(f"Module dir: {ctx.module_dir}")
    print(f"View: {ctx.view}")

    runtime = CamerasRuntime(ctx)

    try:
        print("\n>>> Starting runtime...")
        await runtime.start()

        print("\n>>> Runtime started! Workers should be spawning...")
        print(f">>> Active workers: {list(runtime.worker_manager.workers.keys())}")
        print(f">>> Camera states: {list(runtime.camera_states.keys())}")

        # Let it run for a while to see preview frames
        print("\n>>> Running for 15 seconds (watching for preview frames)...")
        for i in range(15):
            await asyncio.sleep(1)
            workers = runtime.worker_manager.workers
            print(f"[{i+1}s] Workers: {len(workers)}", end="")
            for key, handle in workers.items():
                print(f" | {key}: state={handle.state.name} preview={handle.is_previewing} fps={handle.fps_capture:.1f}", end="")
            print()

        print("\n>>> Test complete!")

    except KeyboardInterrupt:
        print("\n>>> Interrupted by user")
    except Exception as e:
        print(f"\n>>> ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n>>> Shutting down runtime...")
        await runtime.shutdown()
        print(">>> Runtime shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
