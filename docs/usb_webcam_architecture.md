# USB Webcam Frame Size & FPS Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                    CONFIGURATION LAYER                                   │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│   defaults.py                              config.py                                    │
│   ┌─────────────────────────┐              ┌─────────────────────────────────────┐      │
│   │ CAPTURE_RESOLUTION:     │              │ PreviewSettings:                    │      │
│   │   (1280, 720)           │              │   resolution: (320, 180)  ◄─────────┼──┐   │
│   │                         │              │   fps_cap: 10.0           ◄─────────┼──┤   │
│   │ CAPTURE_FPS: 30.0       │              │                                     │  │   │
│   │                         │              ├─────────────────────────────────────┤  │   │
│   │ PREVIEW_SIZE:           │              │ RecordSettings:                     │  │   │
│   │   (320, 180)            │              │   resolution: (1280, 720) ◄─────────┼──┤   │
│   │                         │              │   fps_cap: 30.0           ◄─────────┼──┤   │
│   │ PREVIEW_FPS: 10.0       │              │                                     │  │   │
│   └─────────────────────────┘              └─────────────────────────────────────┘  │   │
│                                                                                     │   │
│   known_cameras.json (per-camera cache) ◄───────────────────────────────────────────┘   │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│   │ { "preview_resolution": "320x180", "preview_fps": "10",                         │   │
│   │   "record_resolution": "1280x720", "record_fps": "30", "overlay": "true" }      │   │
│   └─────────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                            │
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              MAIN PROCESS (bridge.py)                                    │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│   ┌───────────────────────────────────────────────────────────────────────────────┐     │
│   │                          WorkerManager                                         │     │
│   │                                                                               │     │
│   │   spawn_worker(resolution, fps)  ──────────────────────────────────────────┐  │     │
│   │        │                                                                   │  │     │
│   │        │  start_preview(preview_size, target_fps) ──────────────────────┐  │  │     │
│   │        │        │                                                       │  │  │     │
│   │        │        │  start_recording(resolution, fps) ─────────────────┐  │  │  │     │
│   │        │        │        │                                           │  │  │  │     │
│   └────────┼────────┼────────┼───────────────────────────────────────────┼──┼──┼──┘     │
│            │        │        │                                           │  │  │        │
│            ▼        ▼        ▼                                           │  │  │        │
│   ┌─────────────────────────────────────────┐                            │  │  │        │
│   │          Command Protocol               │                            │  │  │        │
│   │  ┌─────────────────────────────────┐    │                            │  │  │        │
│   │  │ CmdConfigure                    │◄───┼────────────────────────────┼──┼──┘        │
│   │  │   capture_resolution: (W, H)    │    │                            │  │           │
│   │  │   capture_fps: float            │    │                            │  │           │
│   │  └─────────────────────────────────┘    │                            │  │           │
│   │  ┌─────────────────────────────────┐    │                            │  │           │
│   │  │ CmdStartPreview                 │◄───┼────────────────────────────┼──┘           │
│   │  │   preview_size: (320, 180)      │    │                            │              │
│   │  │   target_fps: 10.0              │    │                            │              │
│   │  └─────────────────────────────────┘    │                            │              │
│   │  ┌─────────────────────────────────┐    │                            │              │
│   │  │ CmdStartRecord                  │◄───┼────────────────────────────┘              │
│   │  │   resolution: (1280, 720)       │    │                                           │
│   │  │   fps: 30.0                     │    │                                           │
│   │  └─────────────────────────────────┘    │                                           │
│   └─────────────────────────────────────────┘                                           │
│                        │                                                                │
└────────────────────────┼────────────────────────────────────────────────────────────────┘
                         │ IPC (multiprocessing)
                         ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              WORKER PROCESS (separate process)                           │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│   │                              USB BACKEND                                         │   │
│   │                          (usb_backend.py)                                        │   │
│   │                                                                                 │   │
│   │   _configure():                                                                 │   │
│   │     cv2.CAP_PROP_FRAME_WIDTH  ◄── capture_resolution[0]                         │   │
│   │     cv2.CAP_PROP_FRAME_HEIGHT ◄── capture_resolution[1]                         │   │
│   │     cv2.CAP_PROP_FPS          ◄── capture_fps                                   │   │
│   │     cv2.CAP_PROP_FOURCC       ◄── MJPG (preferred)                              │   │
│   │                                                                                 │   │
│   │   ⚠️  Camera may not honor requested settings!                                  │   │
│   │      Actual values queried after set                                            │   │
│   │                                                                                 │   │
│   └─────────────────────────────────────────────────────────────────────────────────┘   │
│                         │                                                               │
│                         │ Raw frames @ actual camera FPS                                │
│                         │ (e.g., 1280x720 @ 30fps)                                      │
│                         ▼                                                               │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│   │                              USBCapture                                          │   │
│   │                            (capture.py)                                          │   │
│   │                                                                                 │   │
│   │   frames() async generator:                                                     │   │
│   │     yields CaptureFrame(data, timestamp, color_format)                          │   │
│   │                                                                                 │   │
│   │   Tracks: actual_fps (what camera reports)                                      │   │
│   │          vs requested_fps (what we asked for)                                   │   │
│   │                                                                                 │   │
│   └─────────────────────────────────────────────────────────────────────────────────┘   │
│                         │                                                               │
│                         │ Single frame stream                                           │
│                         ▼                                                               │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│   │                           CameraWorker                                           │   │
│   │                            (main.py)                                             │   │
│   │                                                                                 │   │
│   │                    ┌──────────────────┐                                         │   │
│   │                    │   Frame Loop     │                                         │   │
│   │                    │                  │                                         │   │
│   │                    │  for each frame: │                                         │   │
│   │                    └────────┬─────────┘                                         │   │
│   │                             │                                                   │   │
│   │              ┌──────────────┴──────────────┐                                    │   │
│   │              ▼                             ▼                                    │   │
│   │   ┌─────────────────────────┐   ┌─────────────────────────┐                     │   │
│   │   │    PREVIEW PATH         │   │    RECORDING PATH       │                     │   │
│   │   │                         │   │                         │                     │   │
│   │   │  if preview_enabled:    │   │  if recording:          │                     │   │
│   │   │                         │   │                         │                     │   │
│   │   │  ┌───────────────────┐  │   │  ┌───────────────────┐  │                     │   │
│   │   │  │ FPS LIMITING      │  │   │  │ ALL FRAMES        │  │                     │   │
│   │   │  │                   │  │   │  │                   │  │                     │   │
│   │   │  │ interval = 1.0 /  │  │   │  │ Every captured    │  │                     │   │
│   │   │  │   preview_fps     │  │   │  │ frame written     │  │                     │   │
│   │   │  │                   │  │   │  │                   │  │                     │   │
│   │   │  │ Skip frames if    │  │   │  │ No frame dropping │  │                     │   │
│   │   │  │ now - last <      │  │   │  │                   │  │                     │   │
│   │   │  │   interval        │  │   │  │                   │  │                     │   │
│   │   │  └─────────┬─────────┘  │   │  └─────────┬─────────┘  │                     │   │
│   │   │            ▼            │   │            ▼            │                     │   │
│   │   │  ┌───────────────────┐  │   │  ┌───────────────────┐  │                     │   │
│   │   │  │ DOWNSCALE         │  │   │  │ ENCODER           │  │                     │   │
│   │   │  │   (preview.py)    │  │   │  │   (encoder.py)    │  │                     │   │
│   │   │  │                   │  │   │  │                   │  │                     │   │
│   │   │  │ cv2.resize(       │  │   │  │ fps = ACTUAL      │  │                     │   │
│   │   │  │   frame,          │  │   │  │   camera fps      │  │                     │   │
│   │   │  │   preview_size    │  │   │  │   (not requested) │  │                     │   │
│   │   │  │ )                 │  │   │  │                   │  │                     │   │
│   │   │  │                   │  │   │  │ Ensures correct   │  │                     │   │
│   │   │  │ cv2.imencode(     │  │   │  │ playback speed    │  │                     │   │
│   │   │  │   ".jpg",         │  │   │  │                   │  │                     │   │
│   │   │  │   quality=80      │  │   │  │                   │  │                     │   │
│   │   │  │ )                 │  │   │  │                   │  │                     │   │
│   │   │  └─────────┬─────────┘  │   │  └─────────┬─────────┘  │                     │   │
│   │   │            ▼            │   │            ▼            │                     │   │
│   │   │  ┌───────────────────┐  │   │  ┌───────────────────┐  │                     │   │
│   │   │  │ OUTPUT            │  │   │  │ OUTPUT            │  │                     │   │
│   │   │  │                   │  │   │  │                   │  │                     │   │
│   │   │  │ 320×180 JPEG      │  │   │  │ 1280×720 MP4      │  │                     │   │
│   │   │  │ @ 10 FPS (capped) │  │   │  │ @ actual FPS      │  │                     │   │
│   │   │  │                   │  │   │  │                   │  │                     │   │
│   │   │  │ → IPC to main     │  │   │  │ → disk file       │  │                     │   │
│   │   │  │   process for UI  │  │   │  │                   │  │                     │   │
│   │   │  └───────────────────┘  │   │  └───────────────────┘  │                     │   │
│   │   └─────────────────────────┘   └─────────────────────────┘                     │   │
│   │                                                                                 │   │
│   └─────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘


═══════════════════════════════════════════════════════════════════════════════════════════
                              SETTINGS CHANGE FLOW
═══════════════════════════════════════════════════════════════════════════════════════════

  User changes settings in UI (settings_panel.py)
                    │
                    ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │                    _apply_camera_settings()                      │
  │                        (bridge.py)                               │
  │                                                                 │
  │   ┌─────────────────────────────────────────────────────────┐   │
  │   │  Save to cache (known_cameras.json)                     │   │
  │   └─────────────────────────────────────────────────────────┘   │
  │                           │                                     │
  │                           ▼                                     │
  │   ┌─────────────────────────────────────────────────────────┐   │
  │   │  Did capture settings change?                           │   │
  │   │  (record_resolution or record_fps)                      │   │
  │   └───────────────────────┬─────────────────────────────────┘   │
  │                           │                                     │
  │              ┌────────────┴────────────┐                        │
  │              │                         │                        │
  │              ▼ YES                     ▼ NO                     │
  │   ┌─────────────────────┐   ┌─────────────────────┐             │
  │   │ RESPAWN WORKER      │   │ RESTART PREVIEW     │             │
  │   │                     │   │ ONLY                │             │
  │   │ • Kill old worker   │   │                     │             │
  │   │ • Spawn new worker  │   │ • Stop preview      │             │
  │   │   with new capture  │   │ • Start preview     │             │
  │   │   resolution/fps    │   │   with new settings │             │
  │   │ • Camera reopened   │   │                     │             │
  │   │   with new mode     │   │ Camera unchanged    │             │
  │   └─────────────────────┘   └─────────────────────┘             │
  │                                                                 │
  └─────────────────────────────────────────────────────────────────┘


═══════════════════════════════════════════════════════════════════════════════════════════
                              COMPARISON TABLE
═══════════════════════════════════════════════════════════════════════════════════════════

  ┌────────────────┬─────────────────────────────┬─────────────────────────────┐
  │    Aspect      │         PREVIEW             │         RECORDING           │
  ├────────────────┼─────────────────────────────┼─────────────────────────────┤
  │ Resolution     │ Software downscaled         │ Full capture resolution     │
  │ Source         │ (320×180 default)           │ (1280×720 default)          │
  ├────────────────┼─────────────────────────────┼─────────────────────────────┤
  │ FPS Control    │ Software frame dropping     │ Uses actual camera FPS      │
  │ Method         │ based on interval timer     │ for correct playback        │
  ├────────────────┼─────────────────────────────┼─────────────────────────────┤
  │ Default FPS    │ 10 FPS (UI display cap)     │ 30 FPS (or actual)          │
  ├────────────────┼─────────────────────────────┼─────────────────────────────┤
  │ Frame Source   │ Same capture stream         │ Same capture stream         │
  │                │ (frames skipped)            │ (all frames kept)           │
  ├────────────────┼─────────────────────────────┼─────────────────────────────┤
  │ Output Format  │ JPEG compressed             │ H.264/MP4 video file        │
  │                │ (quality=80)                │                             │
  ├────────────────┼─────────────────────────────┼─────────────────────────────┤
  │ Destination    │ IPC → Main Process → UI     │ Disk file                   │
  ├────────────────┼─────────────────────────────┼─────────────────────────────┤
  │ Settings       │ Restart preview only        │ Respawn worker process      │
  │ Change Impact  │ (fast)                      │ (camera reopen required)    │
  └────────────────┴─────────────────────────────┴─────────────────────────────┘


═══════════════════════════════════════════════════════════════════════════════════════════
                              FPS MISMATCH HANDLING
═══════════════════════════════════════════════════════════════════════════════════════════

                    ┌─────────────────────────────────────┐
                    │   User requests: 30 FPS             │
                    │   Camera reports: 25 FPS            │
                    └──────────────────┬──────────────────┘
                                       │
                                       ▼
                    ┌─────────────────────────────────────┐
                    │   worker/main.py:269-276            │
                    │                                     │
                    │   actual_fps = capabilities.get(    │
                    │       "actual_fps", requested_fps)  │
                    │                                     │
                    │   if |actual - requested| > 0.5:    │
                    │       log WARNING                   │
                    │                                     │
                    │   record_fps = actual_fps  ◄────────┼── Uses 25, not 30!
                    │                                     │
                    └─────────────────────────────────────┘
                                       │
                                       ▼
                    ┌─────────────────────────────────────┐
                    │   Result: Video plays back at       │
                    │   correct real-world speed          │
                    │                                     │
                    │   (Not sped up or slowed down)      │
                    └─────────────────────────────────────┘
```

## Key Files Reference

| Component | File | Key Lines |
|-----------|------|-----------|
| Defaults | `modules/Cameras/defaults.py` | 7-12 |
| USB Backend Config | `modules/Cameras/runtime/backends/usb_backend.py` | 93-105 |
| Capture Class | `modules/Cameras/worker/capture.py` | 172-316 |
| Preview Downscale | `modules/Cameras/worker/preview.py` | 12-49 |
| Worker Frame Loop | `modules/Cameras/worker/main.py` | 193-212 |
| Recording FPS Logic | `modules/Cameras/worker/main.py` | 269-276 |
| Encoder Init | `modules/Cameras/worker/encoder.py` | 30-46 |
| Command Protocol | `modules/Cameras/worker/protocol.py` | 28-73 |
| Settings Application | `modules/Cameras/bridge.py` | 464-529 |
| UI Settings Panel | `modules/Cameras/app/widgets/settings_panel.py` | 15-159 |
