"""
USB discovery specification.

- Purpose: async probe for USB cameras (v4l2/udev/OpenCV) to produce CameraDescriptor + capabilities.
- Behavior: enumerate /dev/video*, resolve stable ids (vendor/product/serial), query supported modes (res/FPS), and detect hotplug changes.
- Constraints: no blocking; any slow syscalls offloaded; robust to missing drivers; retries with backoff.
- Logging: discovery start/stop, devices found/removed, capability probing results, errors with context.
"""
