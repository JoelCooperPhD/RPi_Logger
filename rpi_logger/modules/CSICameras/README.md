# CSICameras Module

Raspberry Pi CSI camera module using libcamera/Picamera2 with hardware H.264 encoding.

## Supported Hardware

- **Raspberry Pi 5** with PiSP (Pi Signal Processor)
- **CSI cameras**: IMX296 (tested), IMX219, IMX477, IMX708, and other libcamera-supported sensors

## Sensor Resolution and Scaling

### Native Sensor Mode

CSI cameras operate at their **native sensor resolution**. The ISP cannot arbitrarily scale or crop the sensor output for the main capture stream. When you request a resolution like 1280x720, libcamera selects the closest sensor mode and the ISP scales to your requested size.

For example, the **IMX296** sensor:
- Native resolution: **1456x1088**
- This is the only available sensor mode
- Requesting 1280x720 still captures at 1456x1088, then ISP scales to 1280x720

### Buffer Stride Padding

Camera buffers include **stride padding** for DMA alignment (typically 64-byte boundaries):

```
Actual image:  1456 pixels wide
Buffer stride: 1536 pixels (1456 + 80 padding)
```

The module automatically crops this padding after YUV→BGR conversion to prevent artifacts (green bars) in the preview.

### No Hardware Preview Scaling

The Pi 5's ISP **does not reliably provide a separate scaled "lores" stream** for preview. Attempting to use hardware lores scaling results in incorrect crops or aspect ratio issues.

**Solution**: This module uses software scaling for preview:
1. Capture full-resolution YUV420 frames from main stream
2. Convert YUV420 → BGR
3. Crop stride padding
4. Scale in software (cv2.resize) for preview display

This uses more CPU than hardware scaling but provides correct output.

## Recording Pipeline

Recording uses **Picamera2's native H.264 encoder pipeline**:

```
Sensor → ISP → YUV420 buffer → H264Encoder → FfmpegOutput → MP4
```

Key settings:
- **Format**: YUV420 (required for hardware H.264 encoding)
- **Bitrate**: 5 Mbps default
- **Preset**: ultrafast (minimal CPU on Pi 5)
- **I-frame interval**: 30 frames

The encoder runs in a separate hardware pipeline, not consuming the frames used for preview.

## Testing

Run the module standalone with a specific camera:

```bash
cd /home/rs-pi-2/Development/Logger

# Test CSI camera 0
PYTHONPATH=. python3 -m rpi_logger.modules.CSICameras.main_csicameras --camera-index 0

# Test CSI camera 1
PYTHONPATH=. python3 -m rpi_logger.modules.CSICameras.main_csicameras --camera-index 1

# With console logging
PYTHONPATH=. python3 -m rpi_logger.modules.CSICameras.main_csicameras --camera-index 0 --console
```

This launches the full GUI and auto-assigns the specified camera for preview testing.

## Configuration

Settings in `config.txt`:

```
capture_resolution = 1456x1088    # Should match sensor native resolution
capture_fps = 60.0                # Sensor's native FPS
preview_fps = 15.0                # Preview update rate (lower = less CPU)
overlay_enabled = true            # Timestamp overlay on recordings
```

## Architecture

```
main_csicameras.py      Entry point, CLI parsing
bridge.py               CSICamerasRuntime - camera lifecycle, preview loop
csi_core/
  capture.py            PicamCapture - Picamera2 wrapper, H.264 recording
  preview.py            YUV420 → BGR conversion
  picam_recorder.py     TimingAwareFfmpegOutput with frame timing CSV
  backends/
    picam_backend.py    Capability probing, control enumeration
    picam_color.py      IMX296 color format detection
```

## Debug Logging

Debug output written to `/tmp/csi_debug.log`:

```bash
tail -f /tmp/csi_debug.log
```

Shows frame capture timing, buffer shapes, and pipeline state.
