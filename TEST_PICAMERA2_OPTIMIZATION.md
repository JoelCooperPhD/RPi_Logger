# Testing Picamera2 Optimization

## Quick Test

### 1. Start the Logger
```bash
cd /home/rs-pi-2/Development/RPi_Logger
uv run python main_logger.py
```

### 2. Enable Cameras Module
- In the logger GUI, enable the "Cameras" module
- Click "Start Recording" to begin a session

### 3. Monitor CPU Usage
Open a new terminal:
```bash
htop
```
- Look for Python processes
- Note CPU % usage (should be 35-45% lower than before)
- Watch for sustained high usage (if still high, encoder may have issues)

### 4. Verify Recording
After 10-30 seconds, stop recording:
- Check the output directory for MP4 files
- Verify files play correctly: `ffplay <path-to-mp4>`
- Check resolution matches expected (likely 160x120 based on config)
- Verify framerate is smooth

### 5. Check Logs
Look for these key messages in the logger output:

**Expected on startup:**
```
Storage targets prepared -> video: ... | csv: ... | encoder: Picamera2 H264Encoder
Picamera2 encoder started -> ... (fps=30.00, codec=h264)
```

**If fallback to OpenCV:**
```
Storage targets prepared -> video: ... | csv: ... | encoder: OpenCV VideoWriter
```

### 6. Verify Dual Streams
In the log output, look for:
```
Camera 0 streaming 640x480 (RGB888) for preview and recording
```

This confirms lores stream is configured.

## Detailed Verification

### CPU Usage Comparison

**Before optimization (baseline):**
- Expected: ~60-80% CPU usage during recording
- Memory: ~41 MB/sec allocations

**After optimization (expected):**
- Expected: ~20-35% CPU usage during recording
- Memory: ~8-12 MB/sec allocations

### Preview Performance

The preview should feel responsive. Note that:
- Preview FPS still limited by Tkinter (this is expected)
- BUT frames should arrive without software resize delay
- CPU spikes should be lower and less frequent

### Video File Verification

```bash
# Check video file info
ffprobe -v error -show_entries format=duration:stream=codec_name,width,height,r_frame_rate <video.mp4>

# Expected output:
# codec_name=h264
# width=160 (or your configured resolution)
# height=120
# r_frame_rate=30/1 (or your configured framerate)
```

### Still Images (if enabled)

Check that still images:
- Are saved to the camera directory
- Have correct resolution
- Display properly

## Troubleshooting

### Issue: "Failed to start Picamera2 encoder"
**Cause**: Encoder initialization failed
**Solution**: Check logs for specific error. System will automatically fall back to OpenCV VideoWriter.

### Issue: No video file created
**Cause**: Encoder may not have started recording
**Solution**:
1. Check logs for encoder start message
2. Verify camera object was passed to pipeline
3. Try increasing recording duration (encoder may need time to flush)

### Issue: CPU usage still high
**Possible causes:**
1. Encoder is using software encoding (expected on Pi 5)
2. Resolution/framerate too high for CPU
3. Multiple cameras running simultaneously
4. Other system processes consuming CPU

**Solutions:**
- Check `htop` to identify which process is using CPU
- Try lower resolution or framerate
- Test with single camera first

### Issue: Video playback issues
**Possible causes:**
1. FfmpegOutput may need proper codec configuration
2. File may not be properly closed (stop recording before checking)

**Solutions:**
- Ensure recording stopped before playing file
- Try different video player: `vlc <file.mp4>`
- Check file size is non-zero

### Issue: Preview not showing
**Cause**: Lores stream capture may have failed
**Solution**: Check logs for errors in capture loop. System should fall back to main stream if lores unavailable.

## Performance Expectations

### Best Case (Single Camera, 640x480@30fps):
- CPU: 15-25% for entire Python process
- Memory: Stable, low GC pressure
- Preview: Smooth at configured FPS
- Video: Clean H.264 encoding

### Normal Case (Dual Camera, 640x480@30fps):
- CPU: 30-40% for entire Python process
- Memory: Stable, moderate GC pressure
- Preview: Smooth for both cameras
- Video: Clean H.264 encoding on both

### Degraded Case (High Resolution/Framerate):
- CPU: May reach 70-90% (software encoding bottleneck)
- Consider lowering resolution or FPS
- MJPEG encoder may be more efficient alternative

## Rollback Procedure

If optimization causes issues:

1. Stop the logger
2. Edit `Modules/Cameras/controller/runtime.py` line 1486:
   ```python
   # Change:
   camera=slot.camera,

   # To:
   camera=None,
   ```
3. Restart logger - will use OpenCV VideoWriter

## Success Criteria

✅ **Optimization is working if:**
1. Logs show "Picamera2 H264Encoder" mode
2. CPU usage reduced by 30-45%
3. Video files play correctly with H.264 codec
4. Preview remains responsive
5. No crashes or errors during recording

❌ **May need adjustment if:**
1. Logs show "OpenCV VideoWriter" (fallback active)
2. CPU usage unchanged or higher
3. Video files corrupted or won't play
4. Errors in logs about encoder failures

## Next Steps After Testing

If successful:
1. Monitor stability over longer recordings (5-10 minutes)
2. Test with both cameras simultaneously
3. Verify storage space usage is reasonable
4. Check thermal behavior (CPU temperature)

If issues found:
1. Capture full error logs
2. Note specific failure mode
3. Consider reverting specific changes
4. May need encoder parameter tuning
