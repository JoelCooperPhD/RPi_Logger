# Help Dialog Update Plan

## Objective
Update each module's help dialog to include comprehensive documentation about:
1. Output file formats and naming conventions
2. CSV field descriptions with data types and units
3. Timing accuracy and synchronization information
4. Video encoding details (where applicable)

## Modules to Update

### 1. Audio Module
**File:** `rpi_logger/modules/Audio/ui/help_dialog.py`

**Research needed:**
- [ ] WAV file format details (sample rate, bit depth, channels)
- [ ] AUDIOTIMING CSV fields and their meanings
- [ ] Timing accuracy for audio synchronization
- [ ] File naming convention

**Sources to check:**
- `rpi_logger/modules/Audio/services/recorder_service.py`
- `rpi_logger/modules/Audio/services/device_recorder.py`
- `rpi_logger/modules/Audio/services/session.py`

---

### 2. Cameras Module
**File:** `rpi_logger/modules/Cameras/app/help_dialog.py`

**Research needed:**
- [ ] MP4/video file encoding details (codec, container)
- [ ] CAMTIMING CSV fields and their meanings
- [ ] Frame timing accuracy
- [ ] Resolution and FPS information in filenames
- [ ] Global shutter vs rolling shutter notes (IMX296)

**Sources to check:**
- `rpi_logger/modules/Cameras/runtime/` directory
- Any CSV writing code
- Video encoder configuration

---

### 3. DRT Module
**File:** `rpi_logger/modules/DRT/drt/help_dialog.py`

**Research needed:**
- [ ] CSV output fields (timestamp, trial_number, reaction_time, etc.)
- [ ] Timing accuracy of reaction time measurements
- [ ] Device-specific timing characteristics (sDRT vs wDRT)
- [ ] File naming convention

**Sources to check:**
- `rpi_logger/modules/DRT/drt_core/handlers/` directory
- CSV logging code in handlers

---

### 4. EyeTracker Module
**File:** `rpi_logger/modules/EyeTracker/tracker_core/interfaces/gui/help_dialog.py`

**Research needed:**
- [ ] Gaze data CSV fields
- [ ] Events CSV fields (fixations, blinks, saccades)
- [ ] Scene video format and timing
- [ ] Pupil diameter data
- [ ] Timing accuracy and synchronization

**Sources to check:**
- `rpi_logger/modules/EyeTracker/tracker_core/` directory
- CSV writers and data loggers

---

### 5. GPS Module
**File:** `rpi_logger/modules/GPS/help_dialog.py`

**Research needed:**
- [ ] GPS data CSV fields (lat, lon, altitude, speed, etc.)
- [ ] NMEA sentence types logged
- [ ] Update rate and timing accuracy
- [ ] File naming convention

**Sources to check:**
- `rpi_logger/modules/GPS/` runtime and data handling code

---

### 6. Notes Module
**File:** `rpi_logger/modules/Notes/help_dialog.py`

**Research needed:**
- [ ] Notes CSV fields (timestamp, note text, category)
- [ ] Timestamp format and accuracy
- [ ] File naming convention

**Sources to check:**
- `rpi_logger/modules/Notes/notes_runtime.py`

---

### 7. VOG Module
**File:** `rpi_logger/modules/VOG/vog/help_dialog.py`

**Research needed:**
- [ ] VOG data CSV fields (timestamps, lens states, TSOT, TSCT)
- [ ] Timing accuracy of lens state changes
- [ ] Device-specific timing (USB vs wireless)
- [ ] File naming convention

**Sources to check:**
- `rpi_logger/modules/VOG/vog_core/` directory
- `rpi_logger/modules/VOG/vog_core/vog_handler.py`

---

## Standard Sections to Add to Each Help Dialog

Each module's help dialog should include these sections:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
N. OUTPUT FILES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

File Naming Convention
   {timestamp}_{TYPE}_trial{N}_{device}.{ext}

   Example: 20251208_143022_AUDIO_trial001_MIC0.wav

Data Files
   [List each output file type with description]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
N+1. CSV FIELD REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[filename_pattern].csv
   column_name     - Description (type, unit)
   ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
N+2. TIMING & SYNCHRONIZATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Timing Accuracy
   [Device-specific timing accuracy information]

Synchronization
   [How this module syncs with other modules]
   [Reference to sync tools if applicable]
```

## Execution Order

1. Research each module's actual output (read source code)
2. Update help dialogs one by one
3. Verify formatting consistency across all modules

## Notes

- All timestamps should use ISO 8601 or clearly documented format
- Units should be explicit (ms, seconds, Hz, etc.)
- Accuracy statements should be realistic and documented
