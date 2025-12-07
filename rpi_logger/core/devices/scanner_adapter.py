"""
Scanner Adapter - Adapts existing scanners to emit DeviceEvents.

This module provides adapters that wrap the existing scanner callbacks
and convert them to DeviceDiscoveredEvent and DeviceLostEvent, which
are then handled uniformly by DeviceLifecycleManager.

This allows gradual migration without rewriting all scanners at once.
"""

from typing import Callable, Awaitable, Any

from rpi_logger.core.logging_utils import get_module_logger
from .device_registry import DeviceType, DeviceFamily, InterfaceType, get_spec
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

    def __init__(self, event_handler: EventHandler):
        """
        Initialize the adapter.

        Args:
            event_handler: Async function to receive DeviceEvents
        """
        self._handler = event_handler

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
        spec = get_spec(DeviceType.PUPIL_LABS_NEON)
        if not spec:
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
            card_index=getattr(audio_device, 'card_index', None),
            device_index=getattr(audio_device, 'device_index', None),
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
        """
        spec = get_spec(DeviceType.USB_CAMERA)
        if not spec:
            return

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
        )
        await self._emit(event)

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
