"""Test spec for preview pipeline.

- Verify: honors preview FPS cap, drops/queues appropriately, converts frames safely, and stops cleanly on cancellation or device loss.
- Ensure: UI worker receives frames in order with coalescing; timing metrics recorded.
- Cases: shared router feed vs direct backend, slow UI causes drop-oldest behavior, color_convert failures surface warnings not crashes, and cancellation propagates to worker/task manager.
"""
