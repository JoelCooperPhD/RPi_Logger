# Mission: Cameras-USB2 Module

## Goal

Capture synchronized video from USB webcams with precise frame-level timing for scientific data logging.

## Core Requirements

1. **Frame-accurate timing**: Every frame timestamped with monotonic and wall-clock time
2. **Real-time preview**: Live camera feed with performance metrics
3. **Configurable capture**: Resolution, FPS, and camera controls adjustable at runtime
4. **Async architecture**: Non-blocking I/O throughout, modern asyncio patterns
5. **Graceful degradation**: Handle camera disconnects, low disk, queue overflow

## Non-Goals

- Audio recording (separate module responsibility)
- Multi-camera sync (handled by supervisor)
- Video transcoding (output is MJPEG only)
- Cloud upload or streaming
- Post-processing or analysis

## Success Metrics

| Metric | Target |
|--------|--------|
| Frame drop rate | < 0.1% at target FPS |
| Preview latency | < 100ms end-to-end |
| Startup time | < 2s to first frame |
| Memory usage | < 200MB per camera |
| CPU usage | < 30% per camera at 1080p30 |

## Integration Points

| System | Interface |
|--------|-----------|
| Supervisor | Commands via `handle_command()` |
| Base module | Shared types: `CameraId`, `CameraDescriptor`, `Encoder` |
| Core logger | Logging via `rpi_logger.core.logger` |
| Storage | Session paths, disk guard from base |
