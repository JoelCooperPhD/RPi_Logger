"""
Scanner Adapter - Adapts existing scanners to emit DeviceEvents.

This module provides adapters that wrap the existing scanner callbacks
and convert them to DeviceDiscoveredEvent and DeviceLostEvent, which
are then handled uniformly by DeviceLifecycleManager.

This allows gradual migration without rewriting all scanners at once.
"""

from typing import Callable, Awaitable, Any, Optional, TYPE_CHECKING

from rpi_logger.core.logging_utils import get_module_logger
from .device_registry import DeviceType, DeviceFamily, InterfaceType, get_spec

if TYPE_CHECKING:
    from .master_registry import MasterDeviceRegistry
from .events import (
    DeviceEvent,
    DeviceDiscoveredEvent,
    DeviceLostEvent,
    discovered_usb_device,
    discovered_wireless_device,
    discovered_network_device,
    discovered_audio_device,
    discovered_internal_device,
    discovered_camera_device,
    discovered_uart_device,
    device_lost,
)

logger = get_module_logger("ScannerAdapter")


# Type alias for event handler
EventHandler = Callable[[DeviceEvent], Awaitable[None]]


class ScannerEventAdapter:
    """
    Adapts existing scanner callbacks to DeviceEvents.

    This class provides callback methods that match the existing scanner
    interfaces but convert the data to DeviceEvents and forward them
    to the DeviceLifecycleManager.

    Usage:
        adapter = ScannerEventAdapter(lifecycle_manager.handle_event)

        # Wire to USB scanner
        usb_scanner.set_device_found_callback(adapter.on_usb_device_found)
        usb_scanner.set_device_lost_callback(adapter.on_usb_device_lost)

        # Wire to XBee manager
        xbee_manager.set_wireless_device_found_callback(adapter.on_wireless_device_found)
        ...
    """

    def __init__(
        self,
        event_handler: EventHandler,
        master_registry: Optional["MasterDeviceRegistry"] = None,
    ):
        """
        Initialize the adapter.

        Args:
            event_handler: Async function to receive DeviceEvents
            master_registry: Optional MasterDeviceRegistry for tracking physical
                device capabilities (e.g., webcam audio siblings)
        """
        self._handler = event_handler
        self._master_registry = master_registry

    async def _emit(self, event: DeviceEvent) -> None:
        """Emit an event to the handler."""
        await self._handler(event)

    # =========================================================================
    # USB Scanner Callbacks
    # =========================================================================

    async def on_usb_device_found(self, usb_device: Any) -> None:
        """
        Adapt USB scanner device found callback.

        Expected usb_device attributes:
            - port: str
            - device_type: DeviceType
        """
        spec = get_spec(usb_device.device_type)
        if not spec:
            logger.warning(f"Unknown device type: {usb_device.device_type}")
            return

        # Skip XBee coordinators (handled separately)
        if usb_device.device_type == DeviceType.XBEE_COORDINATOR:
            return

        event = discovered_usb_device(
            port=usb_device.port,
            device_type=usb_device.device_type,
            family=spec.family,
            baudrate=spec.baudrate,
            module_id=spec.module_id,
            raw_name=spec.display_name,
        )
        await self._emit(event)

    async def on_usb_device_lost(self, port: str) -> None:
        """Adapt USB scanner device lost callback."""
        await self._emit(device_lost(port))

    # =========================================================================
    # XBee/Wireless Callbacks
    # =========================================================================

    async def on_wireless_device_found(
        self,
        wireless_device: Any,
        dongle_port: str,
    ) -> None:
        """
        Adapt XBee manager wireless device found callback.

        Expected wireless_device attributes:
            - node_id: str
            - device_type: DeviceType
            - family: DeviceFamily
            - battery_percent: int | None
        """
        spec = get_spec(wireless_device.device_type)
        if not spec:
            logger.warning(f"Unknown wireless device type: {wireless_device.device_type}")
            return

        event = discovered_wireless_device(
            node_id=wireless_device.node_id,
            device_type=wireless_device.device_type,
            family=wireless_device.family,
            dongle_port=dongle_port,
            baudrate=spec.baudrate,
            module_id=spec.module_id,
            battery_percent=getattr(wireless_device, 'battery_percent', None),
        )
        await self._emit(event)

    async def on_wireless_device_lost(self, node_id: str) -> None:
        """Adapt XBee manager wireless device lost callback."""
        await self._emit(device_lost(node_id))

    # =========================================================================
    # Network Scanner Callbacks
    # =========================================================================

    async def on_network_device_found(self, network_device: Any) -> None:
        """
        Adapt network scanner device found callback.

        Expected network_device attributes:
            - device_id: str
            - name: str
            - address: str
            - port: int
        """
        logger.info(f"Network device callback received: {network_device.device_id}")
        spec = get_spec(DeviceType.PUPIL_LABS_NEON)
        if not spec:
            logger.warning("No spec found for PUPIL_LABS_NEON")
            return

        event = discovered_network_device(
            device_id=network_device.device_id,
            device_type=DeviceType.PUPIL_LABS_NEON,
            family=DeviceFamily.EYE_TRACKER,
            module_id=spec.module_id,
            name=network_device.name,
            address=network_device.address,
            port=network_device.port,
        )
        logger.info(f"Emitting network device event for {network_device.device_id}")
        await self._emit(event)

    async def on_network_device_lost(self, device_id: str) -> None:
        """Adapt network scanner device lost callback."""
        await self._emit(device_lost(device_id))

    # =========================================================================
    # Audio Scanner Callbacks
    # =========================================================================

    async def on_audio_device_found(self, audio_device: Any) -> None:
        """
        Adapt audio scanner device found callback.

        Expected audio_device attributes:
            - device_id: str
            - name: str
            - card_index: int | None
            - device_index: int | None
            - sample_rate: int | None
            - channels: int | None
        """
        spec = get_spec(DeviceType.USB_MICROPHONE)
        if not spec:
            return

        event = discovered_audio_device(
            device_id=audio_device.device_id,
            device_type=DeviceType.USB_MICROPHONE,
            module_id=spec.module_id,
            name=audio_device.name,
            sounddevice_index=getattr(audio_device, 'sounddevice_index', None),
            sample_rate=getattr(audio_device, 'sample_rate', None),
            channels=getattr(audio_device, 'channels', None),
        )
        await self._emit(event)

    async def on_audio_device_lost(self, device_id: str) -> None:
        """Adapt audio scanner device lost callback."""
        await self._emit(device_lost(device_id))

    # =========================================================================
    # Internal Device Callbacks
    # =========================================================================

    async def on_internal_device_found(self, internal_device: Any) -> None:
        """
        Adapt internal device scanner callback.

        Expected internal_device attributes:
            - device_id: str
            - device_type: DeviceType
            - spec: DeviceSpec
        """
        spec = internal_device.spec

        event = discovered_internal_device(
            device_id=internal_device.device_id,
            device_type=internal_device.device_type,
            family=spec.family,
            module_id=spec.module_id,
            raw_name=spec.display_name,
        )
        await self._emit(event)

    async def on_internal_device_lost(self, device_id: str) -> None:
        """Adapt internal device lost callback."""
        await self._emit(device_lost(device_id))

    # =========================================================================
    # USB Camera Callbacks
    # =========================================================================

    async def on_usb_camera_found(self, camera: Any) -> None:
        """
        Adapt USB camera scanner callback.

        Expected camera attributes:
            - device_id: str
            - friendly_name: str
            - stable_id: str | None
            - dev_path: str | None
            - hw_model: str | None
            - location_hint: str | None
            - usb_bus_path: str | None
            - audio_sibling: AudioSiblingInfo | None
        """
        spec = get_spec(DeviceType.USB_CAMERA)
        if not spec:
            return

        # Register in MasterDeviceRegistry if available
        usb_bus_path = getattr(camera, 'usb_bus_path', None)
        audio_sibling = getattr(camera, 'audio_sibling', None)

        if self._master_registry and usb_bus_path:
            self._register_webcam_in_master_registry(
                camera, usb_bus_path, audio_sibling
            )

        # Include audio sibling info in event if present
        audio_sibling_index = None
        audio_sibling_channels = None
        audio_sibling_sample_rate = None
        audio_sibling_alsa_card = None

        if audio_sibling:
            audio_sibling_index = audio_sibling.sounddevice_index
            audio_sibling_channels = getattr(audio_sibling, 'channels', 2)
            audio_sibling_sample_rate = getattr(audio_sibling, 'sample_rate', 48000.0)
            audio_sibling_alsa_card = getattr(audio_sibling, 'alsa_card', None)

        event = discovered_camera_device(
            device_id=camera.device_id,
            device_type=DeviceType.USB_CAMERA,
            interface=InterfaceType.USB,
            module_id=spec.module_id,
            friendly_name=camera.friendly_name,
            stable_id=getattr(camera, 'stable_id', None),
            dev_path=getattr(camera, 'dev_path', None),
            hw_model=getattr(camera, 'hw_model', None),
            location_hint=getattr(camera, 'location_hint', None),
            camera_index=getattr(camera, 'camera_index', None),
            usb_bus_path=usb_bus_path,
            audio_sibling_index=audio_sibling_index,
            audio_sibling_channels=audio_sibling_channels,
            audio_sibling_sample_rate=audio_sibling_sample_rate,
            audio_sibling_alsa_card=audio_sibling_alsa_card,
        )
        await self._emit(event)

    def _register_webcam_in_master_registry(
        self,
        camera: Any,
        usb_bus_path: str,
        audio_sibling: Any,
    ) -> None:
        """Register a webcam and its audio sibling in the MasterDeviceRegistry."""
        from .master_device import (
            DeviceCapability,
            VideoUSBCapability,
            AudioInputCapability,
            PhysicalInterface,
        )

        # Register video capability
        self._master_registry.register_capability(
            physical_id=usb_bus_path,
            capability=DeviceCapability.VIDEO_USB,
            info=VideoUSBCapability(
                dev_path=getattr(camera, 'dev_path', None),
                stable_id=getattr(camera, 'stable_id', usb_bus_path),
            ),
            display_name=camera.friendly_name,
            physical_interface=PhysicalInterface.USB,
        )

        # If webcam has built-in microphone, register audio capability
        if audio_sibling:
            self._master_registry.register_capability(
                physical_id=usb_bus_path,
                capability=DeviceCapability.AUDIO_INPUT,
                info=AudioInputCapability(
                    sounddevice_index=audio_sibling.sounddevice_index,
                    channels=getattr(audio_sibling, 'channels', 2),
                    sample_rate=getattr(audio_sibling, 'sample_rate', 48000.0),
                    alsa_card=getattr(audio_sibling, 'alsa_card', None),
                ),
            )
            logger.info(
                f"Registered webcam {camera.friendly_name} with audio sibling "
                f"(index={audio_sibling.sounddevice_index})"
            )

    async def on_usb_camera_lost(self, device_id: str) -> None:
        """Adapt USB camera lost callback."""
        await self._emit(device_lost(device_id))

    # =========================================================================
    # CSI Camera Callbacks
    # =========================================================================

    async def on_csi_camera_found(self, camera: Any) -> None:
        """
        Adapt CSI camera scanner callback.

        Expected camera attributes:
            - device_id: str
            - friendly_name: str
            - stable_id: str | None
            - hw_model: str | None
            - location_hint: str | None
        """
        spec = get_spec(DeviceType.PI_CAMERA)
        if not spec:
            return

        event = discovered_camera_device(
            device_id=camera.device_id,
            device_type=DeviceType.PI_CAMERA,
            interface=InterfaceType.CSI,
            module_id=spec.module_id,
            friendly_name=camera.friendly_name,
            stable_id=getattr(camera, 'stable_id', None),
            dev_path=None,
            hw_model=getattr(camera, 'hw_model', None),
            location_hint=getattr(camera, 'location_hint', None),
        )
        await self._emit(event)

    async def on_csi_camera_lost(self, device_id: str) -> None:
        """Adapt CSI camera lost callback."""
        await self._emit(device_lost(device_id))

    # =========================================================================
    # UART Device Callbacks
    # =========================================================================

    async def on_uart_device_found(self, uart_device: Any) -> None:
        """
        Adapt UART scanner callback.

        Expected uart_device attributes:
            - device_id: str
            - device_type: DeviceType
            - path: str
            - spec: DeviceSpec
        """
        spec = uart_device.spec

        event = discovered_uart_device(
            device_id=uart_device.device_id,
            device_type=uart_device.device_type,
            family=spec.family,
            path=uart_device.path,
            baudrate=spec.baudrate,
            module_id=spec.module_id,
            raw_name=spec.display_name,
        )
        await self._emit(event)

    async def on_uart_device_lost(self, device_id: str) -> None:
        """Adapt UART device lost callback."""
        await self._emit(device_lost(device_id))
