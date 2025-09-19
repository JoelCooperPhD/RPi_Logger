#!/usr/bin/env python3
"""
Test only the slave mode subset of tests
"""

import asyncio
import subprocess
import json
import time
import select

def cleanup_camera_processes():
    """Kill any remaining camera processes"""
    try:
        result = subprocess.run(["pgrep", "-f", "dual_camera"], capture_output=True, text=True)
        if result.returncode == 0:
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                if pid:
                    subprocess.run(["kill", pid])
                    print(f"Cleaned up process {pid}")
    except Exception:
        pass  # Ignore cleanup errors

async def test_slave_mode_basic():
    """Test slave mode initialization"""
    print("Running slave mode basic test...")

    cmd = ["uv", "run", "dual_camera_module.py", "--slave", "--output", "slave_test"]

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        # Wait for initialization message
        start_time = time.time()
        init_received = False

        while time.time() - start_time < 10.0:
            if select.select([proc.stdout], [], [], 0.1)[0]:
                line = proc.stdout.readline()
                if line:
                    try:
                        message = json.loads(line.strip())
                        if message.get("status") == "initialized":
                            print("✓ Slave mode initialized successfully")
                            init_received = True
                            break
                    except json.JSONDecodeError:
                        continue

        if not init_received:
            print("✗ Failed to receive initialization message")
            proc.terminate()
            return False

        # Send quit command
        quit_cmd = json.dumps({"command": "quit"}) + "\n"
        proc.stdin.write(quit_cmd)
        proc.stdin.flush()

        try:
            proc.wait(timeout=3.0)
            print("✓ Graceful shutdown successful")
        except subprocess.TimeoutExpired:
            proc.terminate()
            print("✗ Shutdown timeout")
            return False

        return True

    except Exception as e:
        print(f"✗ Test failed: {e}")
        if 'proc' in locals():
            proc.terminate()
        return False

async def main():
    print("=== SLAVE MODE SUBSET TESTS ===")

    # Cleanup first
    cleanup_camera_processes()
    await asyncio.sleep(1)

    # Test 1
    result1 = await test_slave_mode_basic()
    print(f"Test 1 result: {'PASSED' if result1 else 'FAILED'}")

    cleanup_camera_processes()
    await asyncio.sleep(1)

    # Test 2
    result2 = await test_slave_mode_basic()
    print(f"Test 2 result: {'PASSED' if result2 else 'FAILED'}")

    cleanup_camera_processes()

    print(f"Overall: {'ALL PASSED' if result1 and result2 else 'SOME FAILED'}")

if __name__ == "__main__":
    asyncio.run(main())