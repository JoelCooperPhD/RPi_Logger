# Phase 4: Preview

> Display pipeline with efficient scaling

## Quick Reference

| | |
|-|-|
| **Status** | See [TASKS.md](../TASKS.md) |
| **Task** | P4 (single task) |
| **Dependencies** | P1.1, P2.1 |
| **Effort** | Small |
| **Key Specs** | [hardware.md](../reference/hardware.md) |

## Goal

Prepare frames for display with efficient YUV→RGB conversion and scaling.

---

## Deliverables

### preview/processor.py (~80 lines)

```python
class PreviewProcessor:
    def __init__(self, gate: TimingGate): ...
    def process(self, frame: CapturedFrame) -> Optional[bytes]: ...
    def set_target_size(self, width: int, height: int) -> None: ...
    def set_target_fps(self, fps: float) -> None: ...
```

**Processing pipeline**:
1. Check TimingGate → skip if too soon
2. Convert YUV420 → RGB (`cv2.cvtColor`)
3. Crop stride padding (1536 → 1456)
4. Scale to target size (`cv2.resize` with `INTER_NEAREST`)
5. Return PPM bytes for Tk

### preview/scaler.py (~40 lines)

```python
def scale_frame(frame: np.ndarray, target_size: tuple[int, int]) -> np.ndarray:
    """Fast frame scaling using INTER_NEAREST."""

def yuv420_to_rgb(yuv: np.ndarray) -> np.ndarray:
    """Convert YUV420 to RGB."""

def crop_stride(frame: np.ndarray, actual_size: tuple[int, int]) -> np.ndarray:
    """Remove DMA stride padding."""
```

---

## Implementation Notes

### Stride Padding

IMX296 buffers have stride padding for DMA alignment:
- Buffer: 1536 × 1088
- Actual: 1456 × 1088
- Must crop 80 pixels from right edge after YUV→RGB

### PPM Format

For Tk canvas, output raw PPM:
```python
header = f"P6\n{width} {height}\n255\n".encode('ascii')
return header + rgb.tobytes()
```

No PIL required, very fast.

---

## Validation Checklist

- [ ] Both files created
- [ ] YUV420→RGB conversion correct
- [ ] Stride padding cropped (no green bars)
- [ ] Benchmark: <5ms per frame at 640×480

---

## Completion Criteria

When all validation items pass, update [TASKS.md](../TASKS.md).
