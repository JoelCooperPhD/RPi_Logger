"""
Main view specification for Cameras2 (stub Tk view integration).

- Purpose: plug into StubCodexView to render the Cameras2 UI region, add toolbar buttons (e.g., Configure Cameras), host dynamic tabs for cameras, and embed metrics panel.
- Responsibilities: subscribe to model changes, create/destroy tabs on discovery/hotplug, forward user actions to controller, and manage visibility of preview/metrics/log panels.
- Stub (codex) alignment: can either subclass or wrap `StubCodexView` to reuse window geometry persistence, status strip, and logging handler attachment. Should respect `window_geometry` arg and preferences keys (`view.show_*`) used by stub.
- Constraints: Tk interactions must run on the Tk thread; all async updates marshaled via safe callbacks; no blocking IO. Integrate with StubCodexView's async loop (`async_tkinter_loop.async_handler`) for scheduling.
- Logging: UI init timing, tab lifecycle, dialog launches, and any Tk exceptions routed to logger; ensure view attaches handler via supervisor when GUI present.
"""
