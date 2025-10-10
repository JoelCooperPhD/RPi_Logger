# Camera Module Technical Specification Sheet

## System Architecture

### Core Components
- **Dual-Camera System**: Simultaneous control of 2 cameras (indexes 0 and 1)
- **Master-Slave Architecture**: Command-driven operation via JSON protocol over stdin/stdout
- **Multi-Threading**: Separate threads for command listening and camera operations
- **Signal Handling**: SIGTERM and SIGINT for graceful shutdown

### Operating Modes
- **Standalone Mode**: Interactive GUI with OpenCV preview windows
- **Slave Mode** (`--mode slave`): Headless operation controlled via JSON commands
- **Preview Loop**: Continuous frame capture with real-time display
- **Command Listener**: Asynchronous command processing with select() polling

## Camera Specifications

### Video Capture
- **Resolution Range**: Configurable (default 1920x1080, tested with 1280x720)
- **Frame Rate**: Configurable 1-60 FPS (default 30 FPS)
- **Video Format**: RGB888 color space for processing
- **Recording Format**: H.264 encoded video files
- **Preview Resolution**: Separate configurable preview size (default 640x360)

### Camera Configuration
- **Hardware Support**: Picamera2 API for Raspberry Pi cameras
- **Multi-Camera**: Automatic detection and initialization of available cameras
- **Frame Duration Control**: Precise timing via FrameDurationLimits
- **Stream Configuration**: Main stream for recording with separate preview processing

## Data Processing

### Frame Processing
- **Real-Time Resizing**: Dynamic frame resizing for preview
- **FPS Calculation**: Rolling average with 1-second update interval
- **Frame Overlay**: Timestamp and FPS display on preview frames
- **Color Processing**: OpenCV-compatible RGB888 format

### File Management
- **Output Directory**: Configurable with automatic creation
- **File Naming**: Timestamp-based naming (YYYYMMDD_HHMMSS format)
- **Recording Files**: H.264 video files per camera (cam0_timestamp.h264)
- **Snapshot Files**: JPEG images per camera (snapshot_cam0_timestamp.jpg)

## Communication Protocol

### JSON Command Interface (Slave Mode)
- **Input**: Line-delimited JSON commands via stdin
- **Output**: Line-delimited JSON status messages via stdout
- **Logging**: Stderr for system logging (does not interfere with JSON protocol)

### Supported Commands
- **start_recording**: Begin video recording on all cameras
- **stop_recording**: Stop video recording on all cameras
- **take_snapshot**: Capture still images from all cameras
- **get_status**: Retrieve system and camera status
- **quit**: Graceful shutdown with resource cleanup

### Status Messages
- **initialized**: System startup confirmation with camera count
- **recording_started**: Recording initiation confirmation
- **recording_stopped**: Recording termination confirmation
- **snapshot_taken**: Snapshot completion with file paths
- **status_report**: Detailed system status with camera metrics
- **error**: Error reporting with descriptive messages
- **shutdown**: Shutdown notification with signal information

### Message Format
```json
{
  "type": "status",
  "status": "status_type",
  "timestamp": "ISO-8601 timestamp",
  "data": {
    // Status-specific data
  }
}
```

## Performance Metrics

### Timing Characteristics
- **Initialization Time**: <10 seconds for dual-camera setup
- **Command Response**: <1ms processing latency
- **Frame Processing**: ~40ms per frame pair (25 FPS effective)
- **Inter-Camera Sync**: ~23ms average offset between cameras

### Resource Usage
- **CPU Usage**: Multi-core utilization for parallel camera processing
- **Memory**: Buffered frame handling with immediate processing
- **Storage**: H.264 compression for efficient recording
- **I/O**: Line-buffered stdin/stdout for responsive communication

## Interactive Controls (Standalone Mode)

### Keyboard Commands
- **'q'**: Quit application with cleanup
- **'r'**: Toggle recording state (start/stop)
- **'s'**: Capture snapshot from all cameras

### Display Features
- **Dual Windows**: Separate OpenCV windows per camera
- **Live Preview**: Real-time frame display at preview resolution
- **Status Overlay**: Camera ID, timestamp, and FPS display
- **Window Management**: Standard OpenCV window controls

## Error Handling

### Resource Management
- **Camera Cleanup**: Automatic resource release on shutdown
- **Recording Safety**: Stop recording before camera closure
- **Process Termination**: Graceful shutdown with timeout fallback

### Error Recovery
- **JSON Parse Errors**: Logged and reported without termination
- **Command Errors**: Error status messages sent to master
- **Camera Failures**: Individual camera error isolation
- **Signal Handling**: Clean shutdown on SIGTERM/SIGINT

## System Requirements

### Hardware
- **Platform**: Raspberry Pi 5 (ARM architecture)
- **Cameras**: Multiple CSI camera support (tested with 2x IMX296)
- **Storage**: Fast storage for video recording (Class 10+ SD/USB 3.0)
- **Memory**: Adequate RAM for dual-camera buffering

### Software Dependencies
- **picamera2**: Camera hardware interface
- **opencv-python**: Image processing and display
- **numpy**: Array operations
- **Python 3.x**: Core runtime environment

## Configuration Parameters

### Command-Line Arguments
- **--width**: Recording width in pixels (default: 1920)
- **--height**: Recording height in pixels (default: 1080)
- **--fps**: Target frames per second (default: 30)
- **--preview-width**: Preview window width (default: 640)
- **--preview-height**: Preview window height (default: 360)
- **--output**: Output directory path (default: "recordings")
- **--slave**: Enable slave mode (no GUI, command-driven)

## Process Management

### Threading Model
- **Main Thread**: Camera control and preview/slave loop
- **Command Thread**: Asynchronous command processing (slave mode)
- **Signal Handlers**: Interrupt handling in main thread

### Synchronization
- **Shutdown Event**: Thread-safe termination signaling
- **Queue-Based Communication**: Thread-safe status message passing
- **Atomic Operations**: Recording state changes

## Output Formats

### Video Files
- **Format**: H.264 encoded video
- **Naming**: cam{number}_{timestamp}.h264
- **Location**: Configurable output directory

### Image Files
- **Format**: JPEG compressed images
- **Naming**: snapshot_cam{number}_{timestamp}.jpg
- **Location**: Same as video output directory

## Master Control Interface

### Subprocess Management
- **Process Launch**: Popen with pipe communication
- **Line Buffering**: Real-time message exchange
- **Bidirectional Communication**: JSON over stdin/stdout
- **Error Stream**: Separate stderr for logging

### Control Features
- **Automated Sessions**: Demo mode with programmed sequences
- **Interactive Sessions**: Manual command input
- **Status Monitoring**: Asynchronous status message handling
- **Graceful Shutdown**: Timeout-based termination sequence