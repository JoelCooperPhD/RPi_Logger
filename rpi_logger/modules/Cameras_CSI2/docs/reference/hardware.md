# Hardware Notes

> Platform-specific behaviors and constraints

## Target Platform

- **Raspberry Pi 5** with PiSP (Pi Signal Processor)
- **Supported sensors**: IMX296 (primary), IMX219, IMX477, IMX708, and other libcamera-supported sensors

---

## Native Sensor Resolution

CSI cameras operate at their **native sensor resolution**. The ISP cannot arbitrarily scale or crop the sensor output for the main capture stream.

**IMX296 Example**:
- Native resolution: **1456x1088** (only available sensor mode)
- Requesting 1280x720 still captures at 1456x1088, then ISP scales down
- **Implication**: Always capture at native resolution for maximum quality; scale in software for preview

---

## Buffer Stride Padding

Camera buffers include **stride padding** for DMA alignment (typically 64-byte boundaries):

```
Actual image:  1456 pixels wide
Buffer stride: 1536 pixels (1456 + 80 padding bytes)
```

**Failure mode**: If stride padding is not cropped, you get green bars on the right edge of the preview.

**Solution**: After YUV→RGB conversion, crop to actual image dimensions before display.

---

## No Hardware Preview Scaling on Pi 5

The Pi 5's ISP **does not reliably provide a separate scaled "lores" stream** for preview. Attempting to use hardware lores scaling results in:
- Incorrect crops
- Wrong aspect ratios
- Garbled output

**Solution**: Software scaling for preview:
1. Capture full-resolution YUV420 frames from main stream
2. Convert YUV420 → RGB
3. Crop stride padding
4. Scale in software (cv2.resize with INTER_NEAREST for speed)

This uses more CPU than hardware scaling but provides correct output.

---

## Recording Pipeline

**Pi 5 has NO hardware H.264 encoder.** Unlike the Pi 4, the Pi 5's VideoCore VII does not include H.264 encoding hardware.

| Encoder | Format | CPU Usage | Quality | Notes |
|---------|--------|-----------|---------|-------|
| JpegEncoder | MJPEG/AVI | Low | High (quality 85) | Hardware-accelerated JPEG |

**Why MJPEG/AVI is correct for scientific capture**:
- Each frame is independently compressed (no temporal dependencies)
- Frame-accurate seeking and editing
- No GOP artifacts or keyframe issues
- Predictable quality per frame
- Hardware JPEG encoding is fast and low-power on Pi 5
- Larger files than H.264, but storage is cheap

**Note**: Software H.264 encoding is possible but would consume significant CPU and compete with the capture pipeline. Not recommended for scientific capture where timing is critical.

---

## Sensor-Specific Quirks

### IMX296 (Global Shutter)
- Color format detection can be incorrect (picam_color.py handles this)
- Native FPS: ~60.38 at full resolution
- Global shutter eliminates rolling shutter artifacts
- Primary sensor for scientific applications

### IMX219 / IMX477 / IMX708 (Rolling Shutter)
- Higher resolution options
- Rolling shutter visible with fast motion
- May need different default settings

---

## Performance Targets

| Metric | Target | Rationale |
|--------|--------|-----------|
| Capture thread overhead | <100 μs/frame | Must not miss frames at 60fps |
| Preview latency | <50 ms | UI responsiveness |
| Memory per frame | <5 MB | 1456x1088 YUV420 ≈ 2.4 MB |
| Buffer size | 8 frames | ~130 ms buffer at 60fps |
