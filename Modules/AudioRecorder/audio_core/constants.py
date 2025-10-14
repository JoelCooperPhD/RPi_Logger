#!/usr/bin/env python3
"""
Constants for audio recording system.

Centralizes magic numbers and configuration values used throughout the audio module.
"""

# Sample rate limits
SAMPLE_RATE_MIN = 8000  # 8 kHz minimum
SAMPLE_RATE_MAX = 192000  # 192 kHz maximum
SAMPLE_RATE_DEFAULT = 48000  # 48 kHz default

# Audio format
AUDIO_DTYPE = 'float32'  # Internal format for sounddevice
AUDIO_CHANNELS_MONO = 1
AUDIO_BIT_DEPTH = 16  # 16-bit PCM output

# Buffer settings
AUDIO_BLOCKSIZE = 1024  # Samples per callback
FEEDBACK_QUEUE_SIZE = 100  # Max queued feedback messages
FEEDBACK_INTERVAL_SECONDS = 2.0  # Status update interval
MAX_AUDIO_BUFFER_CHUNKS = 10000  # Max chunks before warning (prevents unbounded growth)

# Timeouts (seconds)
CLEANUP_TIMEOUT_SECONDS = 2.0
DEVICE_DISCOVERY_TIMEOUT = 5.0
DEVICE_DISCOVERY_RETRY = 3.0
STREAM_STOP_TIMEOUT_SECONDS = 3.0

# Polling intervals (seconds)
USB_POLL_INTERVAL = 0.005  # 5ms for USB device detection
KEYBOARD_POLL_INTERVAL = 0.001  # 1ms for keyboard input

# Error message sanitization
MAX_ERROR_MESSAGE_LENGTH = 200

# Recording
WAV_COMPRESSION_NONE = 0
