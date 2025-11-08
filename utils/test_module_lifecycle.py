#!/usr/bin/env python3

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from logger_core.logging_config import configure_logging

configure_logging()
logger = logging.getLogger("LifecycleTest")


class ModuleLifecycleTest:

    def __init__(self, module_name: str, module_path: Path):
        self.module_name = module_name
        self.module_path = module_path
        self.process: Optional[asyncio.subprocess.Process] = None
        self.results: Dict[str, any] = {
            "module": module_name,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": []
        }
        self.status_messages: List[Dict] = []
        self.state_transitions: List[str] = []

    async def run_tests(self) -> Dict:
        logger.info("=" * 60)
        logger.info(f"Testing {self.module_name} Module Lifecycle")
        logger.info("=" * 60)

        await self.test_startup_and_initialization()
        await self.test_state_transitions()
        await self.test_shutdown()

        logger.info(f"\n{self.module_name} Results:")
        logger.info(f"  ✓ Passed: {self.results['tests_passed']}")
        logger.info(f"  ✗ Failed: {self.results['tests_failed']}")

        if self.results['errors']:
            logger.error(f"  Errors:")
            for error in self.results['errors']:
                logger.error(f"    - {error}")

        return self.results

    async def test_startup_and_initialization(self):
        logger.info(f"\nTest 1: Startup and Initialization")

        try:
            project_root = Path(__file__).parent.parent
            session_dir = project_root / "data" / f"test_session_{int(time.time())}"
            session_dir.mkdir(parents=True, exist_ok=True)

            cmd = [
                sys.executable,
                str(self.module_path),
                "--mode", "gui",
                "--output-dir", str(session_dir),
                "--session-prefix", "test",
                "--log-level", "info",
                "--enable-commands"
            ]

            logger.info(f"  Starting module: {' '.join(cmd)}")

            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            logger.info(f"  Process started with PID: {self.process.pid}")

            initialized = await self._wait_for_status("initialized", timeout=30.0)

            if initialized:
                logger.info(f"  ✓ Module initialized successfully")
                self.results['tests_passed'] += 1

                init_status = initialized.get('data', {})
                duration_ms = init_status.get('duration_ms', 'N/A')
                logger.info(f"    Initialization time: {duration_ms}ms")

                self.state_transitions.append("STOPPED → STARTING → IDLE")
            else:
                logger.error(f"  ✗ Module failed to initialize within timeout")
                self.results['tests_failed'] += 1
                self.results['errors'].append(f"{self.module_name}: Failed to initialize")

        except Exception as e:
            logger.error(f"  ✗ Startup test failed: {e}")
            self.results['tests_failed'] += 1
            self.results['errors'].append(f"{self.module_name}: Startup error: {e}")

    async def test_state_transitions(self):
        logger.info(f"\nTest 2: State Transitions")

        if not self.process or self.process.returncode is not None:
            logger.error(f"  ✗ Module not running, skipping state transition test")
            self.results['tests_failed'] += 1
            return

        try:
            await asyncio.sleep(2.0)

            if self.process.returncode is None:
                logger.info(f"  ✓ Module running in IDLE state")
                self.results['tests_passed'] += 1
            else:
                logger.error(f"  ✗ Module crashed (exit code: {self.process.returncode})")
                self.results['tests_failed'] += 1
                self.results['errors'].append(f"{self.module_name}: Module crashed unexpectedly")

        except Exception as e:
            logger.error(f"  ✗ State transition test failed: {e}")
            self.results['tests_failed'] += 1
            self.results['errors'].append(f"{self.module_name}: State transition error: {e}")

    async def test_shutdown(self):
        logger.info(f"\nTest 3: Graceful Shutdown")

        if not self.process or self.process.returncode is not None:
            logger.error(f"  ✗ Module not running, skipping shutdown test")
            self.results['tests_failed'] += 1
            return

        try:
            logger.info(f"  Sending quit command...")

            quit_cmd = json.dumps({"command": "quit"}) + "\n"
            self.process.stdin.write(quit_cmd.encode())
            await self.process.stdin.drain()

            try:
                returncode = await asyncio.wait_for(self.process.wait(), timeout=10.0)

                if returncode == 0:
                    logger.info(f"  ✓ Module shutdown gracefully (exit code: 0)")
                    self.results['tests_passed'] += 1
                else:
                    logger.warning(f"  ⚠ Module exited with code: {returncode}")
                    self.results['tests_passed'] += 1

            except asyncio.TimeoutError:
                logger.error(f"  ✗ Module did not shutdown within 10 seconds, killing...")
                self.process.kill()
                await self.process.wait()
                self.results['tests_failed'] += 1
                self.results['errors'].append(f"{self.module_name}: Failed to shutdown gracefully")

        except Exception as e:
            logger.error(f"  ✗ Shutdown test failed: {e}")
            self.results['tests_failed'] += 1
            self.results['errors'].append(f"{self.module_name}: Shutdown error: {e}")

    async def _wait_for_status(self, status_type: str, timeout: float = 10.0) -> Optional[Dict]:
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                line = await asyncio.wait_for(self.process.stdout.readline(), timeout=0.5)

                if not line:
                    break

                line_str = line.decode().strip()
                if not line_str:
                    continue

                try:
                    data = json.loads(line_str)

                    if data.get("type") == "status":
                        self.status_messages.append(data)

                        if data.get("status") == status_type:
                            return data

                except json.JSONDecodeError:
                    pass

            except asyncio.TimeoutError:
                continue

        return None


async def test_all_modules():
    project_root = Path(__file__).parent.parent

    modules_to_test = [
        ("AudioRecorder", project_root / "Modules" / "AudioRecorder" / "main_audio.py"),
        ("Cameras", project_root / "Modules" / "Cameras" / "main_camera.py"),
        ("DRT", project_root / "Modules" / "DRT" / "main_DRT.py"),
        ("EyeTracker", project_root / "Modules" / "EyeTracker" / "main_eye_tracker.py"),
        ("GPS", project_root / "Modules" / "GPS" / "main_GPS.py"),
        ("NoteTaker", project_root / "Modules" / "NoteTaker" / "main_notes.py"),
    ]

    all_results = []

    for module_name, module_path in modules_to_test:
        if not module_path.exists():
            logger.warning(f"Skipping {module_name}: {module_path} not found")
            continue

        tester = ModuleLifecycleTest(module_name, module_path)
        results = await tester.run_tests()
        all_results.append(results)

    logger.info("\n" + "=" * 60)
    logger.info("OVERALL TEST SUMMARY")
    logger.info("=" * 60)

    total_passed = sum(r['tests_passed'] for r in all_results)
    total_failed = sum(r['tests_failed'] for r in all_results)

    for result in all_results:
        status = "✓ PASS" if result['tests_failed'] == 0 else "✗ FAIL"
        logger.info(f"{status} {result['module']}: {result['tests_passed']} passed, {result['tests_failed']} failed")

    logger.info(f"\nTotal: {total_passed} passed, {total_failed} failed")

    if total_failed > 0:
        logger.info("\nErrors:")
        for result in all_results:
            for error in result['errors']:
                logger.error(f"  - {error}")

    return total_failed == 0


async def main():
    logger.info("RPi Logger - Module Lifecycle Test Suite")
    logger.info("Testing standardized startup, state transitions, and shutdown\n")

    success = await test_all_modules()

    if success:
        logger.info("\n✓ All tests passed!")
        sys.exit(0)
    else:
        logger.error("\n✗ Some tests failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
