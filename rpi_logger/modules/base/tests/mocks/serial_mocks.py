"""Mock serial devices for GPS, DRT, and VOG testing.

Provides mock implementations that can replay recorded data or simulate
device responses for testing without physical hardware.
"""

from __future__ import annotations

import io
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union


@dataclass
class MockSerialConfig:
    """Configuration for mock serial device."""
    port: str = "/dev/ttyMOCK0"
    baudrate: int = 9600
    timeout: float = 1.0
    response_delay: float = 0.01  # Delay between responses


class MockSerialDevice:
    """Base mock serial device.

    Provides a serial.Serial-compatible interface for testing.
    Subclasses implement device-specific behavior.
    """

    def __init__(self, config: Optional[MockSerialConfig] = None):
        """Initialize mock serial device.

        Args:
            config: Device configuration
        """
        self.config = config or MockSerialConfig()
        self._is_open = False
        self._read_buffer = queue.Queue()
        self._write_log: List[bytes] = []
        self._response_handlers: Dict[bytes, Callable[[], bytes]] = {}
        self._auto_responses: List[bytes] = []
        self._auto_response_index = 0
        self._response_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # =========================================================================
    # Serial-compatible interface
    # =========================================================================

    @property
    def port(self) -> str:
        return self.config.port

    @property
    def baudrate(self) -> int:
        return self.config.baudrate

    @property
    def timeout(self) -> float:
        return self.config.timeout

    @property
    def is_open(self) -> bool:
        return self._is_open

    def open(self) -> None:
        """Open the mock serial port."""
        self._is_open = True
        self._stop_event.clear()

    def close(self) -> None:
        """Close the mock serial port."""
        self._is_open = False
        self._stop_event.set()
        if self._response_thread and self._response_thread.is_alive():
            self._response_thread.join(timeout=1.0)

    def read(self, size: int = 1) -> bytes:
        """Read bytes from the mock device.

        Args:
            size: Number of bytes to read

        Returns:
            Bytes read (may be less than size)
        """
        if not self._is_open:
            raise IOError("Port not open")

        result = b""
        try:
            while len(result) < size:
                chunk = self._read_buffer.get(timeout=self.config.timeout)
                result += chunk
        except queue.Empty:
            pass

        return result[:size]

    def readline(self) -> bytes:
        """Read a line from the mock device.

        Returns:
            Line ending with newline, or partial line on timeout
        """
        if not self._is_open:
            raise IOError("Port not open")

        result = b""
        try:
            start_time = time.time()
            while True:
                if time.time() - start_time > self.config.timeout:
                    break
                try:
                    chunk = self._read_buffer.get(timeout=0.1)
                    result += chunk
                    if b"\n" in result:
                        break
                except queue.Empty:
                    continue
        except Exception:
            pass

        return result

    def write(self, data: bytes) -> int:
        """Write bytes to the mock device.

        Args:
            data: Bytes to write

        Returns:
            Number of bytes written
        """
        if not self._is_open:
            raise IOError("Port not open")

        self._write_log.append(data)

        # Check for response handlers
        for pattern, handler in self._response_handlers.items():
            if pattern in data:
                response = handler()
                if response:
                    self._queue_response(response)
                break

        return len(data)

    def flush(self) -> None:
        """Flush output buffer (no-op for mock)."""
        pass

    def reset_input_buffer(self) -> None:
        """Clear input buffer."""
        while not self._read_buffer.empty():
            try:
                self._read_buffer.get_nowait()
            except queue.Empty:
                break

    def reset_output_buffer(self) -> None:
        """Clear output buffer (no-op for mock)."""
        pass

    @property
    def in_waiting(self) -> int:
        """Return number of bytes waiting to be read."""
        return self._read_buffer.qsize()

    # =========================================================================
    # Mock control methods
    # =========================================================================

    def _queue_response(self, data: bytes) -> None:
        """Queue data to be read."""
        for byte in data:
            self._read_buffer.put(bytes([byte]))

    def add_response_handler(self, pattern: bytes, handler: Callable[[], bytes]) -> None:
        """Add a handler for a specific command pattern.

        Args:
            pattern: Bytes pattern to match in write()
            handler: Function returning response bytes
        """
        self._response_handlers[pattern] = handler

    def set_auto_responses(self, responses: List[bytes]) -> None:
        """Set automatic responses to be sent in sequence.

        Args:
            responses: List of response bytes to cycle through
        """
        self._auto_responses = responses
        self._auto_response_index = 0

    def start_auto_responses(self, interval: float = 1.0) -> None:
        """Start sending automatic responses at intervals.

        Args:
            interval: Seconds between responses
        """
        if not self._auto_responses:
            return

        def response_loop():
            while not self._stop_event.is_set():
                if self._auto_responses:
                    response = self._auto_responses[self._auto_response_index % len(self._auto_responses)]
                    self._queue_response(response)
                    self._auto_response_index += 1
                self._stop_event.wait(interval)

        self._response_thread = threading.Thread(target=response_loop, daemon=True)
        self._response_thread.start()

    def get_write_log(self) -> List[bytes]:
        """Get log of all written data."""
        return self._write_log.copy()

    def clear_write_log(self) -> None:
        """Clear the write log."""
        self._write_log.clear()


class MockGPSDevice(MockSerialDevice):
    """Mock GPS device that replays NMEA sentences.

    Can either replay from a file or generate synthetic NMEA data.
    """

    # Sample NMEA sentences for testing
    SAMPLE_NMEA = [
        b"$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*47\r\n",
        b"$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A\r\n",
        b"$GPVTG,054.7,T,034.4,M,005.5,N,010.2,K*48\r\n",
        b"$GPGSA,A,3,04,05,,09,12,,,24,,,,,2.5,1.3,2.1*39\r\n",
    ]

    def __init__(
        self,
        nmea_file: Optional[Union[str, Path]] = None,
        config: Optional[MockSerialConfig] = None,
    ):
        """Initialize mock GPS device.

        Args:
            nmea_file: Optional file with NMEA sentences to replay
            config: Device configuration
        """
        super().__init__(config or MockSerialConfig(baudrate=9600))
        self.nmea_file = Path(nmea_file) if nmea_file else None
        self._sentences: List[bytes] = []
        self._load_sentences()

    def _load_sentences(self) -> None:
        """Load NMEA sentences from file or use defaults."""
        if self.nmea_file and self.nmea_file.exists():
            with self.nmea_file.open("rb") as f:
                self._sentences = [
                    line.strip() + b"\r\n"
                    for line in f
                    if line.strip().startswith(b"$")
                ]
        else:
            self._sentences = self.SAMPLE_NMEA.copy()

    def start_streaming(self, interval: float = 1.0) -> None:
        """Start streaming NMEA sentences.

        Args:
            interval: Seconds between sentence groups
        """
        self.set_auto_responses(self._sentences)
        self.start_auto_responses(interval)

    @staticmethod
    def generate_gga(
        lat: float = 48.1173,
        lon: float = 11.5167,
        alt: float = 545.4,
        fix_quality: int = 1,
        satellites: int = 8,
    ) -> bytes:
        """Generate a GPGGA sentence.

        Args:
            lat: Latitude in decimal degrees
            lon: Longitude in decimal degrees
            alt: Altitude in meters
            fix_quality: GPS fix quality (0-8)
            satellites: Number of satellites

        Returns:
            NMEA GPGGA sentence with checksum
        """
        # Convert lat/lon to NMEA format
        lat_deg = int(abs(lat))
        lat_min = (abs(lat) - lat_deg) * 60
        lat_dir = "N" if lat >= 0 else "S"
        lat_str = f"{lat_deg:02d}{lat_min:07.4f}"

        lon_deg = int(abs(lon))
        lon_min = (abs(lon) - lon_deg) * 60
        lon_dir = "E" if lon >= 0 else "W"
        lon_str = f"{lon_deg:03d}{lon_min:07.4f}"

        time_str = time.strftime("%H%M%S")

        sentence = f"GPGGA,{time_str},{lat_str},{lat_dir},{lon_str},{lon_dir},{fix_quality},{satellites:02d},0.9,{alt:.1f},M,47.0,M,,"

        # Calculate checksum
        checksum = 0
        for char in sentence:
            checksum ^= ord(char)

        return f"${sentence}*{checksum:02X}\r\n".encode()


class MockDRTDevice(MockSerialDevice):
    """Mock DRT device for testing sDRT and wDRT protocols."""

    def __init__(
        self,
        device_type: str = "sdrt",
        config: Optional[MockSerialConfig] = None,
    ):
        """Initialize mock DRT device.

        Args:
            device_type: "sdrt" or "wdrt"
            config: Device configuration
        """
        cfg = config or MockSerialConfig(
            baudrate=115200 if device_type == "sdrt" else 57600
        )
        super().__init__(cfg)
        self.device_type = device_type.lower()
        self._trial_number = 0
        self._experiment_running = False
        self._setup_handlers()

    def _setup_handlers(self) -> None:
        """Set up command response handlers."""
        if self.device_type == "sdrt":
            self.add_response_handler(b"exp_start", self._handle_exp_start)
            self.add_response_handler(b"exp_stop", self._handle_exp_stop)
        else:
            self.add_response_handler(b"trl>1", self._handle_exp_start)
            self.add_response_handler(b"trl>0", self._handle_exp_stop)

    def _handle_exp_start(self) -> bytes:
        """Handle experiment start command."""
        self._experiment_running = True
        self._trial_number = 0
        if self.device_type == "sdrt":
            return b"expStart\r\n"
        return b"trl>1\n"

    def _handle_exp_stop(self) -> bytes:
        """Handle experiment stop command."""
        self._experiment_running = False
        if self.device_type == "sdrt":
            return b"expStop\r\n"
        return b"trl>0\n"

    def simulate_trial(
        self,
        reaction_time_ms: int = 250,
        responses: int = 1,
        battery_percent: int = 85,
    ) -> bytes:
        """Generate a simulated trial response.

        Args:
            reaction_time_ms: Reaction time in milliseconds (-1 for timeout)
            responses: Number of responses
            battery_percent: Battery percentage (wDRT only)

        Returns:
            Trial data response
        """
        self._trial_number += 1
        device_time = int(time.time() * 1000) % 1000000

        if self.device_type == "sdrt":
            return f"trl>{self._trial_number},{device_time},{responses},{reaction_time_ms}\r\n".encode()
        else:
            device_utc = int(time.time())
            return f"dta>{self._trial_number},{device_time},{responses},{reaction_time_ms},{battery_percent},{device_utc}\n".encode()

    def simulate_timeout(self) -> bytes:
        """Generate a timeout response."""
        return self.simulate_trial(reaction_time_ms=-1, responses=0)


class MockVOGDevice(MockSerialDevice):
    """Mock VOG device for testing sVOG and wVOG protocols."""

    def __init__(
        self,
        device_type: str = "svog",
        config: Optional[MockSerialConfig] = None,
    ):
        """Initialize mock VOG device.

        Args:
            device_type: "svog" or "wvog"
            config: Device configuration
        """
        cfg = config or MockSerialConfig(
            baudrate=115200 if device_type == "svog" else 57600
        )
        super().__init__(cfg)
        self.device_type = device_type.lower()
        self._trial_number = 0
        self._experiment_running = False
        self._shutter_open = 0
        self._shutter_closed = 0
        self._setup_handlers()

    def _setup_handlers(self) -> None:
        """Set up command response handlers."""
        if self.device_type == "svog":
            self.add_response_handler(b">do_expStart|<<", self._handle_exp_start)
            self.add_response_handler(b">do_expStop|<<", self._handle_exp_stop)
            self.add_response_handler(b">do_trialStart|<<", self._handle_trial_start)
        else:
            self.add_response_handler(b"exp>1", self._handle_exp_start)
            self.add_response_handler(b"exp>0", self._handle_exp_stop)
            self.add_response_handler(b"trl>1", self._handle_trial_start)

    def _handle_exp_start(self) -> bytes:
        """Handle experiment start command."""
        self._experiment_running = True
        self._trial_number = 0
        if self.device_type == "svog":
            return b"expStart\r\n"
        return b"exp>1\n"

    def _handle_exp_stop(self) -> bytes:
        """Handle experiment stop command."""
        self._experiment_running = False
        if self.device_type == "svog":
            return b"expStop\r\n"
        return b"exp>0\n"

    def _handle_trial_start(self) -> bytes:
        """Handle trial start command."""
        self._shutter_open = 0
        self._shutter_closed = 0
        if self.device_type == "svog":
            return b"trialStart\r\n"
        return b"trl>1\n"

    def simulate_shutter_event(
        self,
        open_ms: int = 1500,
        closed_ms: int = 1500,
        lens: str = "X",
        battery_percent: int = 85,
    ) -> bytes:
        """Generate a simulated shutter event.

        Args:
            open_ms: Time shutter was open (ms)
            closed_ms: Time shutter was closed (ms)
            lens: Lens identifier (A/B/X) for wVOG
            battery_percent: Battery percentage (wVOG only)

        Returns:
            Shutter data response
        """
        self._trial_number += 1
        self._shutter_open += open_ms
        self._shutter_closed += closed_ms

        if self.device_type == "svog":
            return f"data|{self._trial_number},{open_ms},{closed_ms}\r\n".encode()
        else:
            total_ms = open_ms + closed_ms
            device_unix = int(time.time())
            return f"dta>{self._trial_number},{open_ms},{closed_ms},{total_ms},{lens},{battery_percent},{device_unix}\n".encode()
