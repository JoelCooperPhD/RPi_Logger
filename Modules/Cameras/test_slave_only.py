#!/usr/bin/env python3
"""
Test only the slave mode functionality
"""

import asyncio
import subprocess
import json
import time
import select

async def test_slave_mode_basic():
    """Test slave mode initialization"""
    print("Testing slave mode initialization and basic commands")

    cmd = ["uv", "run", "dual_camera_module.py", "--slave", "--output", "slave_test"]

    print(f"Running: {' '.join(cmd)}")

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
            # Use select to check if stdout has data available
            if select.select([proc.stdout], [], [], 0.1)[0]:
                line = proc.stdout.readline()
                if line:
                    try:
                        message = json.loads(line.strip())
                        print(f"Received: {message}")
                        if message.get("status") == "initialized":
                            print("✓ Slave mode initialized successfully")
                            init_received = True
                            break
                    except json.JSONDecodeError:
                        print(f"Non-JSON line: {line.strip()}")
                        continue

        if not init_received:
            print("✗ Failed to receive initialization message")
            proc.terminate()
            return False

        # Send quit command
        quit_cmd = json.dumps({"command": "quit"}) + "\n"
        proc.stdin.write(quit_cmd)
        proc.stdin.flush()

        # Wait for shutdown
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
    result = await test_slave_mode_basic()
    print(f"Test result: {'PASSED' if result else 'FAILED'}")

if __name__ == "__main__":
    asyncio.run(main())