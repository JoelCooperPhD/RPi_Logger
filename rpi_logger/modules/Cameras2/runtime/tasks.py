"""
Task management specification.

- Purpose: wrap BackgroundTaskManager/ShutdownGuard-like behavior for Cameras2 to own asyncio tasks (discovery, preview, record) with clean cancellation.
- Responsibilities: central place to create tasks with naming/logging, track them per camera, and enforce shutdown timeouts; detect leaked tasks.
- Logging: task creation, completion, cancellation, exceptions; shutdown timing.
- Constraints: asyncio-only, never blocks; integrates with controller and supervisor. Should watch supervisor/model `shutdown_event` (from StubCodexModel) to cancel promptly when the module is asked to quit.
"""
