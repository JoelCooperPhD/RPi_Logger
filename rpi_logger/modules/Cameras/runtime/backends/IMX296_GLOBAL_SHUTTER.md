# IMX296 Global Shutter Camera Reference

Technical reference for the Raspberry Pi Global Shutter Camera (Sony IMX296) connected via CSI port.

## Sensor Specifications

| Parameter | Value |
|-----------|-------|
| Sensor | Sony IMX296 |
| Resolution | 1456 x 1088 (1.58MP) |
| Pixel Size | 3.45um x 3.45um |
| Optical Format | 1/2.9" (6.3mm diagonal) |
| Shutter Type | Global Shutter |
| Bit Depth | 10-bit RAW Bayer |
| Interface | MIPI CSI-2 (1 data lane) |
| Max FPS (full res) | ~60 fps |
| Min Exposure | 29us (with adequate light) |

## Single Sensor Mode

Unlike rolling shutter cameras (IMX708, IMX219) which have multiple binned/cropped modes, the **IMX296 has only ONE sensor mode**:

```
$ libcamera-hello --list-cameras
0 : imx296 [1456x1088]
    Modes: 'SRGGB10_CSI2P' : 1456x1088 [60.38 fps - (0, 0)/1456x1088 crop]
```

**No binning support** on the color version. Higher frame rates require cropping.

## Frame Rate Control

### Continuous FPS Range (Not Discrete Modes)

The IMX296 does **not** have discrete FPS modes. FPS is controlled by adjusting VBLANK, giving a continuous range:

| Parameter | Value |
|-----------|-------|
| **Maximum FPS** | ~60.38 fps (VBLANK=30, minimum) |
| **Minimum FPS** | ~0.64 fps (VBLANK=1,047,487, maximum) |

You can request **any FPS between 0.64 and 60.38**. The sensor adjusts VBLANK to achieve it.

**Silent clamping:** If you request >60 fps at full resolution, the sensor delivers ~60 fps without error.

### Driver-Level (V4L2)

Frame rate is controlled via VBLANK:

```
Frame Rate = Pixel_Rate / (HMAX_pixels x (Height + VBLANK))

Max FPS = 118,800,000 / (1760 x (1088 + 30))     = ~60.38 fps
Min FPS = 118,800,000 / (1760 x (1088 + 1047487)) = ~0.64 fps
```

Constants from kernel driver (`imx296.c`):
- Pixel rate: 118.8 Mpixels/sec (1188 Mbps / 10 bits)
- HMAX_pixels: ~1760 (from HMAX=1100 at 74.25MHz internal PLL)
- VBLANK range: 30 to 1,047,487 lines
- HBLANK: read-only, ~1760 - width

### Picamera2 Configuration

libcamera translates `FrameDurationLimits` to VBLANK adjustments internally.

```python
# Method 1: FrameDurationLimits (microseconds)
# Formula: duration_us = 1_000_000 / fps
controls = {"FrameDurationLimits": (16666, 16666)}  # 60 fps
controls = {"FrameDurationLimits": (33333, 33333)}  # 30 fps

# Method 2: FrameRate control
controls = {"FrameRate": 60}
```

**Note:** Requesting FPS above sensor capability (e.g., 120 fps) will silently clamp to ~60 fps.

## Increasing FPS via Cropping

Since binning is unavailable, **cropping is the only way to exceed 60 fps**.

### Achievable Frame Rates

| Resolution | Max FPS | Notes |
|------------|---------|-------|
| 1456x1088 | ~60 | Full sensor |
| 720x540 | ~200 | Centered crop |
| 300x200 | ~293 | Small ROI |
| 128x96 | ~536 | Minimum useful |

### Crop Configuration

Set crop via `media-ctl` **before** starting libcamera:

```bash
# Calculate centered crop offsets
WIDTH=720
HEIGHT=540
CROP_X=$(( (1456 - WIDTH) / 2 ))
CROP_Y=$(( (1088 - HEIGHT) / 2 ))

media-ctl -d /dev/media0 --set-v4l2 \
  "'imx296 10-001a':0 [fmt:SBGGR10_1X10/${WIDTH}x${HEIGHT} crop:(${CROP_X},${CROP_Y})/${WIDTH}x${HEIGHT}]"
```

**Constraints:**
- Width/height must be multiples of 4
- Minimum ROI: 96x88 pixels

## Preview vs Capture Behavior

**Key difference from rolling shutter cameras:** The IMX296 does not switch sensor modes between preview and capture. No "flicker" or mode-switch delay occurs.

| Operation | Rolling Shutter (IMX708) | Global Shutter (IMX296) |
|-----------|--------------------------|-------------------------|
| Preview | Binned mode (fast) | Full sensor mode |
| Still Capture | Switches to full res (flicker) | Same mode (no switch) |
| Mode Change Delay | 0.5-2 seconds | None |

## Picamera2 Integration

```python
from picamera2 import Picamera2

picam2 = Picamera2()

# Query sensor modes (only one for IMX296)
print(picam2.sensor_modes)
# [{'format': SRGGB10_CSI2P, 'size': (1456, 1088), 'fps': 60.38,
#   'crop_limits': (0, 0, 1456, 1088), 'exposure_limits': (29, None)}]

# Video configuration
config = picam2.create_video_configuration(
    main={"size": (1456, 1088), "format": "RGB888"},
    controls={"FrameDurationLimits": (16666, 16666)},  # 60 fps
    buffer_count=4,
)
picam2.configure(config)
picam2.start()
```

## External Trigger Mode

The IMX296 supports hardware triggering for precise frame synchronization:

```bash
# Enable trigger mode
v4l2-ctl -d /dev/v4l-subdev0 -c trigger_mode=1
```

In fast trigger mode, **exposure is controlled by trigger pulse duration**, not register settings.

**Pin voltage warning:** XVS, XHS, XTR pins are 1.8V logic. Applying 3.3V will damage the sensor.

## Device Tree Configuration

```bash
# /boot/firmware/config.txt (Bookworm/Pi5)
# /boot/config.txt (Bullseye/Pi4)
camera_auto_detect=0
[all]
dtoverlay=imx296
```

## References

- Kernel driver: `drivers/media/i2c/imx296.c`
- libcamera IPA: `cam_helper_imx296.cpp`
- Tuning file: `imx296.json`
