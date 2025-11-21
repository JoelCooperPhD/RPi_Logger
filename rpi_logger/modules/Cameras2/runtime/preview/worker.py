"""
Preview worker specification.

- Purpose: bridge preview pipeline output to the view adapter safely; handle UI throttling and backpressure.
- Responsibilities: accept frames (likely via asyncio Queue), coalesce if UI lags, marshal to Tk thread, and report metrics/drops.
- Stub (codex) alignment: integrate with StubCodexView/adapter scheduling helpers (async_tkinter_loop) for Tk-safe callbacks; respect view/logging handler availability.
- Constraints: asyncio; non-blocking; robust cancellation; no Tk calls from background threads.
- Logging: queue depth anomalies, dropped frames, dispatch timing, and errors.
"""
