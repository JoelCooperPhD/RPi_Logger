#!/usr/bin/env python3
"""
Test script to verify quit command functionality.

This script tests that modules can properly receive and parse quit commands
from the master logger during shutdown.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from logger_core.logger_system import LoggerSystem

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("QuitTest")


async def test_quit_command():
    """Test quit command functionality."""

    logger.info("=" * 60)
    logger.info("Starting quit command test")
    logger.info("=" * 60)

    # Create logger system
    session_dir = project_root / "data" / "test_quit_command"
    session_dir.mkdir(parents=True, exist_ok=True)

    system = LoggerSystem(
        session_dir=session_dir,
        session_prefix="test"
    )

    available_modules = system.get_available_modules()
    logger.info(f"Found {len(available_modules)} module(s)")

    # Start Camera module
    logger.info("Starting Camera module...")
    success = await system.start_module("Camera")

    if not success:
        logger.error("Failed to start Camera module")
        return False

    logger.info("Camera module started successfully")

    # Wait for module to initialize
    await asyncio.sleep(3)

    # Check module status
    camera_module = system.module_processes.get("Camera")
    if not camera_module:
        logger.error("Camera module not found in system")
        return False

    logger.info(f"Camera module state: {camera_module.get_state()}")

    # Now stop the module (this will send quit command)
    logger.info("Sending quit command to Camera module...")
    await system.stop_module("Camera")

    logger.info("Waiting for module to stop...")
    await asyncio.sleep(3)

    # Check final state
    final_state = camera_module.get_state()
    logger.info(f"Camera module final state: {final_state}")

    # Cleanup
    await system.cleanup()

    # Check for success
    if final_state.value == "stopped":
        logger.info("=" * 60)
        logger.info("TEST PASSED: Module stopped cleanly via quit command")
        logger.info("=" * 60)
        return True
    else:
        logger.error("=" * 60)
        logger.error(f"TEST FAILED: Module in unexpected state: {final_state}")
        logger.error("=" * 60)
        return False


async def main():
    """Main entry point."""
    try:
        success = await test_quit_command()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"Test failed with exception: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
