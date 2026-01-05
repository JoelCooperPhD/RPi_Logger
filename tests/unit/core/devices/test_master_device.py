"""
Tests for Master Device Architecture - Phase 1 components.

Tests cover:
- MasterDevice data model and properties
- MasterDeviceRegistry CRUD and queries
- USBPhysicalIdResolver (with mocked sysfs)
"""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from rpi_logger.core.devices.master_device import (
    MasterDevice,
    DeviceCapability,
    PhysicalInterface,
    CapabilityInfo,
    VideoUSBCapability,
    VideoCSICapability,
    AudioInputCapability,
    SerialCapability,
    NetworkCapability,
    InternalCapability,
)
from rpi_logger.core.devices.master_registry import MasterDeviceRegistry
from rpi_logger.core.devices.physical_id import USBPhysicalIdResolver


class TestMasterDevice:
    """Tests for MasterDevice data model."""

    def test_create_empty_device(self):
        """Test creating a device with no capabilities."""
        device = MasterDevice(
            physical_id="1-2",
            display_name="Test Device",
            physical_interface=PhysicalInterface.USB,
        )
        assert device.physical_id == "1-2"
        assert device.display_name == "Test Device"
        assert device.physical_interface == PhysicalInterface.USB
        assert device.capabilities == {}
        assert not device.has_video
        assert not device.has_audio_input

    def test_webcam_without_mic(self):
        """Test USB webcam without built-in microphone."""
        device = MasterDevice(
            physical_id="1-2",
            display_name="Basic Webcam",
            physical_interface=PhysicalInterface.USB,
            capabilities={
                DeviceCapability.VIDEO_USB: VideoUSBCapability(
                    dev_path="/dev/video0",
                    stable_id="1-2",
                ),
            },
        )
        assert device.is_webcam
        assert device.has_video
        assert not device.has_audio_input
        assert not device.is_webcam_with_mic
        assert not device.is_standalone_audio

    def test_webcam_with_mic(self):
        """Test USB webcam with built-in microphone."""
        device = MasterDevice(
            physical_id="1-2",
            display_name="Logitech C920",
            physical_interface=PhysicalInterface.USB,
            capabilities={
                DeviceCapability.VIDEO_USB: VideoUSBCapability(
                    dev_path="/dev/video0",
                    stable_id="1-2",
                    hw_model="Logitech C920",
                ),
                DeviceCapability.AUDIO_INPUT: AudioInputCapability(
                    sounddevice_index=3,
                    channels=2,
                    sample_rate=48000.0,
                ),
            },
        )
        assert device.is_webcam
        assert device.has_video
        assert device.has_audio_input
        assert device.is_webcam_with_mic
        assert not device.is_standalone_audio

    def test_standalone_microphone(self):
        """Test standalone USB microphone (no video)."""
        device = MasterDevice(
            physical_id="1-4",
            display_name="Blue Yeti",
            physical_interface=PhysicalInterface.USB,
            capabilities={
                DeviceCapability.AUDIO_INPUT: AudioInputCapability(
                    sounddevice_index=5,
                    channels=2,
                    sample_rate=48000.0,
                ),
            },
        )
        assert not device.is_webcam
        assert not device.has_video
        assert device.has_audio_input
        assert not device.is_webcam_with_mic
        assert device.is_standalone_audio

    def test_csi_camera(self):
        """Test CSI camera."""
        device = MasterDevice(
            physical_id="csi:0",
            display_name="Raspberry Pi Camera",
            physical_interface=PhysicalInterface.CSI,
            capabilities={
                DeviceCapability.VIDEO_CSI: VideoCSICapability(
                    camera_num=0,
                    sensor_model="imx219",
                ),
            },
        )
        assert device.is_csi_camera
        assert device.has_video
        assert not device.is_webcam
        assert not device.is_webcam_with_mic

    def test_serial_device(self):
        """Test serial device."""
        device = MasterDevice(
            physical_id="1-3",
            display_name="DRT Device",
            physical_interface=PhysicalInterface.USB,
            capabilities={
                DeviceCapability.SERIAL_DRT: SerialCapability(
                    port="/dev/ttyACM0",
                    baudrate=115200,
                    device_subtype="drt",
                ),
            },
        )
        assert device.is_serial
        assert not device.has_video
        assert not device.has_audio_input

    def test_capability_accessors(self):
        """Test capability accessor properties."""
        device = MasterDevice(
            physical_id="1-2",
            display_name="Webcam",
            physical_interface=PhysicalInterface.USB,
            capabilities={
                DeviceCapability.VIDEO_USB: VideoUSBCapability(
                    dev_path="/dev/video0",
                    stable_id="1-2",
                ),
                DeviceCapability.AUDIO_INPUT: AudioInputCapability(
                    sounddevice_index=3,
                    channels=2,
                ),
            },
        )
        video_cap = device.video_capability
        assert video_cap is not None
        assert video_cap.dev_path == "/dev/video0"

        audio_cap = device.audio_input_capability
        assert audio_cap is not None
        assert audio_cap.sounddevice_index == 3

    def test_capability_types(self):
        """Test capability_types method."""
        device = MasterDevice(
            physical_id="1-2",
            display_name="Webcam",
            physical_interface=PhysicalInterface.USB,
            capabilities={
                DeviceCapability.VIDEO_USB: VideoUSBCapability(
                    dev_path="/dev/video0",
                    stable_id="1-2",
                ),
                DeviceCapability.AUDIO_INPUT: AudioInputCapability(
                    sounddevice_index=3,
                ),
            },
        )
        cap_types = device.capability_types()
        assert DeviceCapability.VIDEO_USB in cap_types
        assert DeviceCapability.AUDIO_INPUT in cap_types
        assert len(cap_types) == 2


class TestMasterDeviceRegistry:
    """Tests for MasterDeviceRegistry."""

    def test_register_single_capability(self):
        """Test registering a single capability."""
        registry = MasterDeviceRegistry()

        device = registry.register_capability(
            physical_id="1-2",
            capability=DeviceCapability.VIDEO_USB,
            info=VideoUSBCapability(dev_path="/dev/video0", stable_id="1-2"),
            display_name="Webcam",
        )

        assert device.physical_id == "1-2"
        assert device.display_name == "Webcam"
        assert device.is_webcam
        assert len(registry.get_all_devices()) == 1

    def test_register_multiple_capabilities_same_device(self):
        """Test registering multiple capabilities for same physical device."""
        registry = MasterDeviceRegistry()

        # Register video
        registry.register_capability(
            physical_id="1-2",
            capability=DeviceCapability.VIDEO_USB,
            info=VideoUSBCapability(dev_path="/dev/video0", stable_id="1-2"),
            display_name="Logitech C920",
        )

        # Register audio on same device
        device = registry.register_capability(
            physical_id="1-2",
            capability=DeviceCapability.AUDIO_INPUT,
            info=AudioInputCapability(sounddevice_index=3, channels=2),
        )

        # Should be same device with both capabilities
        assert len(registry.get_all_devices()) == 1
        assert device.is_webcam_with_mic

    def test_unregister_capability(self):
        """Test unregistering a capability."""
        registry = MasterDeviceRegistry()

        registry.register_capability(
            physical_id="1-2",
            capability=DeviceCapability.VIDEO_USB,
            info=VideoUSBCapability(dev_path="/dev/video0", stable_id="1-2"),
        )
        registry.register_capability(
            physical_id="1-2",
            capability=DeviceCapability.AUDIO_INPUT,
            info=AudioInputCapability(sounddevice_index=3),
        )

        # Unregister video
        result = registry.unregister_capability("1-2", DeviceCapability.VIDEO_USB)
        assert result is True

        # Device should still exist with audio only
        device = registry.get_device("1-2")
        assert device is not None
        assert device.is_standalone_audio
        assert not device.is_webcam

    def test_unregister_last_capability_removes_device(self):
        """Test that removing last capability removes the device."""
        registry = MasterDeviceRegistry()

        registry.register_capability(
            physical_id="1-2",
            capability=DeviceCapability.VIDEO_USB,
            info=VideoUSBCapability(dev_path="/dev/video0", stable_id="1-2"),
        )

        registry.unregister_capability("1-2", DeviceCapability.VIDEO_USB)

        assert registry.get_device("1-2") is None
        assert len(registry.get_all_devices()) == 0

    def test_remove_device(self):
        """Test removing a device entirely."""
        registry = MasterDeviceRegistry()

        registry.register_capability(
            physical_id="1-2",
            capability=DeviceCapability.VIDEO_USB,
            info=VideoUSBCapability(dev_path="/dev/video0", stable_id="1-2"),
        )

        removed = registry.remove_device("1-2")
        assert removed is not None
        assert removed.physical_id == "1-2"
        assert registry.get_device("1-2") is None

    def test_get_webcams(self):
        """Test querying webcams."""
        registry = MasterDeviceRegistry()

        # Webcam with mic
        registry.register_capability(
            physical_id="1-2",
            capability=DeviceCapability.VIDEO_USB,
            info=VideoUSBCapability(dev_path="/dev/video0", stable_id="1-2"),
            display_name="C920",
        )
        registry.register_capability(
            physical_id="1-2",
            capability=DeviceCapability.AUDIO_INPUT,
            info=AudioInputCapability(sounddevice_index=3),
        )

        # Webcam without mic
        registry.register_capability(
            physical_id="1-3",
            capability=DeviceCapability.VIDEO_USB,
            info=VideoUSBCapability(dev_path="/dev/video2", stable_id="1-3"),
            display_name="Basic Cam",
        )

        # Standalone mic
        registry.register_capability(
            physical_id="1-4",
            capability=DeviceCapability.AUDIO_INPUT,
            info=AudioInputCapability(sounddevice_index=5),
            display_name="Blue Yeti",
        )

        webcams = registry.get_webcams()
        assert len(webcams) == 2

        webcams_with_audio = registry.get_webcams_with_audio()
        assert len(webcams_with_audio) == 1
        assert webcams_with_audio[0].display_name == "C920"

    def test_get_standalone_audio_devices(self):
        """Test querying standalone audio devices (the key filter)."""
        registry = MasterDeviceRegistry()

        # Webcam with mic - should NOT appear in standalone audio
        registry.register_capability(
            physical_id="1-2",
            capability=DeviceCapability.VIDEO_USB,
            info=VideoUSBCapability(dev_path="/dev/video0", stable_id="1-2"),
        )
        registry.register_capability(
            physical_id="1-2",
            capability=DeviceCapability.AUDIO_INPUT,
            info=AudioInputCapability(sounddevice_index=3),
        )

        # Standalone mic - SHOULD appear
        registry.register_capability(
            physical_id="1-4",
            capability=DeviceCapability.AUDIO_INPUT,
            info=AudioInputCapability(sounddevice_index=5),
            display_name="Blue Yeti",
        )

        standalone = registry.get_standalone_audio_devices()
        assert len(standalone) == 1
        assert standalone[0].display_name == "Blue Yeti"

    def test_is_audio_index_webcam_mic(self):
        """Test checking if audio index belongs to webcam."""
        registry = MasterDeviceRegistry()

        # Webcam with mic
        registry.register_capability(
            physical_id="1-2",
            capability=DeviceCapability.VIDEO_USB,
            info=VideoUSBCapability(dev_path="/dev/video0", stable_id="1-2"),
        )
        registry.register_capability(
            physical_id="1-2",
            capability=DeviceCapability.AUDIO_INPUT,
            info=AudioInputCapability(sounddevice_index=3),
        )

        # Standalone mic
        registry.register_capability(
            physical_id="1-4",
            capability=DeviceCapability.AUDIO_INPUT,
            info=AudioInputCapability(sounddevice_index=5),
        )

        assert registry.is_audio_index_webcam_mic(3) is True
        assert registry.is_audio_index_webcam_mic(5) is False
        assert registry.is_audio_index_webcam_mic(99) is False

    def test_find_device_by_video_path(self):
        """Test finding device by video path."""
        registry = MasterDeviceRegistry()

        registry.register_capability(
            physical_id="1-2",
            capability=DeviceCapability.VIDEO_USB,
            info=VideoUSBCapability(dev_path="/dev/video0", stable_id="1-2"),
            display_name="Webcam",
        )

        device = registry.find_device_by_video_path("/dev/video0")
        assert device is not None
        assert device.physical_id == "1-2"

        device = registry.find_device_by_video_path("/dev/video99")
        assert device is None

    def test_observer_notifications(self):
        """Test observer pattern for capability changes."""
        registry = MasterDeviceRegistry()
        events = []

        def observer(physical_id, capability, added):
            events.append((physical_id, capability, added))

        registry.add_observer(observer)

        # Register capability
        registry.register_capability(
            physical_id="1-2",
            capability=DeviceCapability.VIDEO_USB,
            info=VideoUSBCapability(dev_path="/dev/video0", stable_id="1-2"),
        )

        assert len(events) == 1
        assert events[0] == ("1-2", DeviceCapability.VIDEO_USB, True)

        # Unregister capability
        registry.unregister_capability("1-2", DeviceCapability.VIDEO_USB)

        assert len(events) == 2
        assert events[1] == ("1-2", DeviceCapability.VIDEO_USB, False)

    def test_clear_registry(self):
        """Test clearing the registry."""
        registry = MasterDeviceRegistry()

        registry.register_capability(
            physical_id="1-2",
            capability=DeviceCapability.VIDEO_USB,
            info=VideoUSBCapability(dev_path="/dev/video0", stable_id="1-2"),
        )
        registry.register_capability(
            physical_id="1-3",
            capability=DeviceCapability.AUDIO_INPUT,
            info=AudioInputCapability(sounddevice_index=5),
        )

        registry.clear()

        assert len(registry.get_all_devices()) == 0


class TestUSBPhysicalIdResolver:
    """Tests for USBPhysicalIdResolver with mocked sysfs."""

    def test_from_video_device_usb(self):
        """Test resolving USB bus path from video device."""
        # Mock sysfs structure
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_resolved = Path("/sys/devices/pci0000:00/0000:00:14.0/usb1/1-2/1-2:1.0/video4linux/video0")
        mock_path.resolve.return_value = mock_resolved

        with patch.object(Path, "__new__", return_value=mock_path):
            with patch("rpi_logger.core.devices.physical_id._is_usb_path", return_value=True):
                with patch("rpi_logger.core.devices.physical_id._extract_usb_bus_path", return_value="1-2"):
                    result = USBPhysicalIdResolver.from_video_device("/dev/video0")
                    assert result == "1-2"

    def test_from_video_device_not_usb(self):
        """Test that non-USB video devices return None."""
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_resolved = Path("/sys/devices/platform/soc/fe801000.csi")
        mock_path.resolve.return_value = mock_resolved

        with patch.object(Path, "__new__", return_value=mock_path):
            with patch("rpi_logger.core.devices.physical_id._is_usb_path", return_value=False):
                result = USBPhysicalIdResolver.from_video_device("/dev/video0")
                assert result is None

    def test_from_video_device_not_found(self):
        """Test handling of non-existent video device."""
        mock_path = MagicMock()
        mock_path.exists.return_value = False

        with patch.object(Path, "__new__", return_value=mock_path):
            result = USBPhysicalIdResolver.from_video_device("/dev/video99")
            assert result is None

    def test_from_alsa_card_usb(self):
        """Test resolving USB bus path from ALSA card."""
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_resolved = Path("/sys/devices/pci0000:00/0000:00:14.0/usb1/1-2/1-2:1.1")
        mock_path.resolve.return_value = mock_resolved

        with patch.object(Path, "__new__", return_value=mock_path):
            with patch("rpi_logger.core.devices.physical_id._is_usb_path", return_value=True):
                with patch("rpi_logger.core.devices.physical_id._extract_usb_bus_path", return_value="1-2"):
                    result = USBPhysicalIdResolver.from_alsa_card(2)
                    assert result == "1-2"

    def test_from_sounddevice_index(self):
        """Test resolving USB bus path from sounddevice index."""
        mock_devices = [
            {"name": "Built-in Audio", "max_input_channels": 2},
            {"name": "USB Audio (hw:2,0)", "max_input_channels": 2},
        ]

        with patch("sounddevice.query_devices", return_value=mock_devices):
            with patch.object(USBPhysicalIdResolver, "from_alsa_card", return_value="1-2"):
                result = USBPhysicalIdResolver.from_sounddevice_index(1)
                assert result == "1-2"

    def test_find_audio_sibling_for_video(self):
        """Test finding audio sibling of video device."""
        mock_devices = [
            {"name": "Built-in Audio", "max_input_channels": 2, "default_samplerate": 44100},
            {"name": "C920 Audio (hw:2,0)", "max_input_channels": 2, "default_samplerate": 48000},
        ]

        with patch.object(USBPhysicalIdResolver, "from_video_device", return_value="1-2"):
            with patch("sounddevice.query_devices", return_value=mock_devices):
                # First audio device is on different bus, second is on same bus
                with patch.object(
                    USBPhysicalIdResolver,
                    "from_sounddevice_index",
                    side_effect=[None, "1-2"]
                ):
                    result = USBPhysicalIdResolver.find_audio_sibling_for_video("/dev/video0")

                    assert result is not None
                    assert result["sounddevice_index"] == 1
                    assert result["channels"] == 2
                    assert result["sample_rate"] == 48000

    def test_find_audio_sibling_none_found(self):
        """Test when no audio sibling exists."""
        mock_devices = [
            {"name": "Built-in Audio", "max_input_channels": 2},
        ]

        with patch.object(USBPhysicalIdResolver, "from_video_device", return_value="1-2"):
            with patch("sounddevice.query_devices", return_value=mock_devices):
                with patch.object(
                    USBPhysicalIdResolver,
                    "from_sounddevice_index",
                    return_value="1-5"  # Different bus path
                ):
                    result = USBPhysicalIdResolver.find_audio_sibling_for_video("/dev/video0")
                    assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
