"""
Pi camera discovery specification.

- Purpose: detect CSI/board cameras (libcamera/rpi APIs), enumerate sensors, and query supported modes.
- Behavior: gather stable ids (model, connector, sensor id), produce capabilities (res/FPS) per camera, and detect availability changes.
- Picamera2 adherence: use Picamera2/libcamera queries for mode listings and controls whenever possible; avoid diverging from Picamera2's reported capabilities to keep behavior predictable.
- Constraints: async-friendly wrappers around libcamera; avoid blocking; defensive against missing firmware.
- Logging: detection events, capabilities, probe errors, and timing.
"""
