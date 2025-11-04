#!/usr/bin/env python3
"""
Test to understand actual blocking behavior during shutdown.
This will help us understand what's REALLY happening without timeouts.
"""

import asyncio
import threading
import time
import tkinter as tk
from typing import Optional


class ShutdownTest:
    def __init__(self):
        self.root: Optional[tk.Tk] = None
        self.async_loop: Optional[asyncio.AbstractEventLoop] = None
        self.async_thread: Optional[threading.Thread] = None
        self.shutdown_log = []

    def log(self, msg: str):
        timestamp = time.perf_counter()
        thread_id = threading.get_ident()
        self.shutdown_log.append((timestamp, thread_id, msg))
        print(f"[{timestamp:.3f}] [Thread {thread_id}] {msg}")

    def run_test(self):
        """Run the test scenario."""
        print("=" * 80)
        print("SHUTDOWN BEHAVIOR TEST")
        print("=" * 80)

        # Create tkinter window
        self.log("Creating Tkinter window")
        self.root = tk.Tk()
        self.root.title("Shutdown Test")
        self.root.geometry("400x300")

        # Start async event loop in background thread
        self.log("Starting async event loop in daemon thread")
        self.async_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.async_thread.start()

        # Wait for loop to start
        while self.async_loop is None:
            time.sleep(0.01)

        self.log("Async loop started")

        # Schedule some async work
        self.log("Scheduling async tasks")
        asyncio.run_coroutine_threadsafe(self._long_running_task("Task1", 3.0), self.async_loop)
        asyncio.run_coroutine_threadsafe(self._long_running_task("Task2", 5.0), self.async_loop)

        # Set up close handler
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Add button to trigger close
        btn = tk.Button(self.root, text="Close Window", command=self.on_close)
        btn.pack(pady=20)

        # Auto-close after 2 seconds
        self.root.after(2000, self.on_close)

        self.log("Starting mainloop (BLOCKING)")
        start_mainloop = time.perf_counter()
        self.root.mainloop()
        mainloop_duration = time.perf_counter() - start_mainloop

        self.log(f"Mainloop exited after {mainloop_duration:.3f}s")

        # What happens to daemon thread?
        self.log("Checking daemon thread state...")
        if self.async_thread.is_alive():
            self.log("WARNING: Daemon thread still alive!")
        else:
            self.log("Daemon thread terminated")

        print("\n" + "=" * 80)
        print("SHUTDOWN SEQUENCE:")
        print("=" * 80)
        base_time = self.shutdown_log[0][0]
        for timestamp, thread_id, msg in self.shutdown_log:
            relative = timestamp - base_time
            print(f"+{relative:6.3f}s [Thread {thread_id}] {msg}")

    def _run_async_loop(self):
        """Run async event loop in background thread."""
        self.log("Async thread started")
        self.async_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.async_loop)

        self.log("Running event loop forever")
        self.async_loop.run_forever()

        self.log("Event loop stopped")

    async def _long_running_task(self, name: str, duration: float):
        """Simulate long-running async task."""
        self.log(f"{name}: Started (will run for {duration}s)")
        try:
            await asyncio.sleep(duration)
            self.log(f"{name}: Completed normally")
        except asyncio.CancelledError:
            self.log(f"{name}: CANCELLED")

    def on_close(self):
        """Handle window close - test different approaches."""
        self.log(">>> on_close() called")

        print("\n" + "=" * 80)
        print("TEST 1: What happens with immediate window.destroy()?")
        print("=" * 80)

        start = time.perf_counter()

        # Test 1: Direct destroy (what happens?)
        self.log("Calling window.destroy() directly")
        self.root.destroy()
        destroy_duration = time.perf_counter() - start

        self.log(f"window.destroy() returned after {destroy_duration:.6f}s")

        # Does mainloop exit immediately?
        self.log("Returned from on_close()")


class ShutdownTest2:
    """Test what happens when we schedule destroy via after()"""

    def __init__(self):
        self.root: Optional[tk.Tk] = None
        self.shutdown_log = []

    def log(self, msg: str):
        timestamp = time.perf_counter()
        thread_id = threading.get_ident()
        self.shutdown_log.append((timestamp, thread_id, msg))
        print(f"[{timestamp:.3f}] [Thread {thread_id}] {msg}")

    def run_test(self):
        print("\n" + "=" * 80)
        print("TEST 2: What happens with scheduled destroy via after()?")
        print("=" * 80)

        self.log("Creating window")
        self.root = tk.Tk()
        self.root.title("After Test")
        self.root.geometry("400x300")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close_scheduled)

        # Auto-close after 1 second
        self.root.after(1000, self.on_close_scheduled)

        self.log("Starting mainloop")
        start_mainloop = time.perf_counter()
        self.root.mainloop()
        mainloop_duration = time.perf_counter() - start_mainloop

        self.log(f"Mainloop exited after {mainloop_duration:.3f}s")

        print("\n" + "=" * 80)
        print("SHUTDOWN SEQUENCE:")
        print("=" * 80)
        base_time = self.shutdown_log[0][0]
        for timestamp, thread_id, msg in self.shutdown_log:
            relative = timestamp - base_time
            print(f"+{relative:6.3f}s [Thread {thread_id}] {msg}")

    def on_close_scheduled(self):
        self.log(">>> on_close_scheduled() called")

        # Schedule destroy instead of calling directly
        self.log("Scheduling window.destroy() via after(0, ...)")
        self.root.after(0, self._do_destroy)

        self.log("Returned from on_close_scheduled()")

    def _do_destroy(self):
        self.log(">>> _do_destroy() called (from after callback)")

        start = time.perf_counter()
        self.root.destroy()
        duration = time.perf_counter() - start

        self.log(f"window.destroy() completed in {duration:.6f}s")


if __name__ == "__main__":
    # Test 1: Direct destroy
    test1 = ShutdownTest()
    test1.run_test()

    # Wait a bit
    time.sleep(1)

    # Test 2: Scheduled destroy
    test2 = ShutdownTest2()
    test2.run_test()

    print("\n" + "=" * 80)
    print("CONCLUSIONS:")
    print("=" * 80)
    print("1. Is window.destroy() blocking or instant?")
    print("2. Does scheduled destroy behave differently?")
    print("3. What happens to daemon thread when mainloop exits?")
    print("4. Does mainloop exit immediately after destroy()?")
