"""
Camera tab widget specification.

- Purpose: per-camera UI component inserted into notebook tabs; shows preview canvas, status, basic controls (select/enable, start preview/record), and quick metrics.
- Dynamic behavior: created when camera is discovered or restored from cache; destroyed when camera disappears (USB unplug) or user deselects; resilient to rapid plug/unplug.
- Integration: receives lo-res frames from preview worker via adapter, surfaces user actions to controller, displays capability-derived labels.
- Logging: lifecycle events, frame update errors, control actions; include camera id and backend info.
"""
