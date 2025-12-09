"""
Device Catalog - Single source of truth for all device metadata.

This module defines the canonical ordering, display names, and metadata
for all device families and interface types. UI and business logic should
query this catalog rather than hardcoding enum values.
"""

from dataclasses import dataclass
from typing import ClassVar

from .device_registry import DeviceFamily, InterfaceType, DeviceType, DEVICE_REGISTRY


@dataclass(frozen=True)
class FamilyMetadata:
    """Metadata for a device family."""
    family: DeviceFamily
    display_name: str
    display_order: int
    description: str = ""


@dataclass(frozen=True)
class InterfaceMetadata:
    """Metadata for an interface type."""
    interface: InterfaceType
    display_name: str
    display_order: int
    description: str = ""


class DeviceCatalog:
    """
    Single source of truth for all device metadata.

    This class provides:
    - Canonical ordering for families and interfaces
    - Display names for UI rendering
    - Available connection combinations
    - Device type to family/interface mapping

    All UI components and business logic should use this catalog
    instead of hardcoding DeviceFamily/InterfaceType values.
    """

    # Canonical family definitions with ordering
    # Display names match module config.txt display_name values for consistency
    FAMILIES: ClassVar[tuple[FamilyMetadata, ...]] = (
        FamilyMetadata(
            DeviceFamily.VOG,
            "VOG",
            0,
            "Video-oculography devices"
        ),
        FamilyMetadata(
            DeviceFamily.DRT,
            "DRT",
            1,
            "Detection response task devices"
        ),
        FamilyMetadata(
            DeviceFamily.CAMERA,
            "Cameras",
            2,
            "Camera devices (USB and CSI)"
        ),
        FamilyMetadata(
            DeviceFamily.EYE_TRACKER,
            "EyeTracker-Neon",
            3,
            "Pupil Labs Neon eye tracker"
        ),
        FamilyMetadata(
            DeviceFamily.AUDIO,
            "Audio",
            4,
            "Audio input devices"
        ),
        FamilyMetadata(
            DeviceFamily.GPS,
            "GPS",
            5,
            "GPS receivers"
        ),
        FamilyMetadata(
            DeviceFamily.INTERNAL,
            "Notes",
            6,
            "Internal software-only modules"
        ),
    )

    # Canonical interface definitions with ordering
    INTERFACES: ClassVar[tuple[InterfaceMetadata, ...]] = (
        InterfaceMetadata(
            InterfaceType.USB,
            "USB",
            0,
            "USB-connected devices"
        ),
        InterfaceMetadata(
            InterfaceType.XBEE,
            "XBee",
            1,
            "XBee wireless (via USB dongle)"
        ),
        InterfaceMetadata(
            InterfaceType.NETWORK,
            "Network",
            2,
            "Network/mDNS discovered devices"
        ),
        InterfaceMetadata(
            InterfaceType.CSI,
            "CSI",
            3,
            "Raspberry Pi Camera Serial Interface"
        ),
        InterfaceMetadata(
            InterfaceType.UART,
            "UART",
            4,
            "Built-in serial ports (Pi GPIO UART)"
        ),
        InterfaceMetadata(
            InterfaceType.INTERNAL,
            "Internal",
            5,
            "Software-only (no hardware)"
        ),
    )

    # Cached lookups (built lazily)
    _family_by_enum: ClassVar[dict[DeviceFamily, FamilyMetadata] | None] = None
    _interface_by_enum: ClassVar[dict[InterfaceType, InterfaceMetadata] | None] = None
    _available_connections: ClassVar[dict[DeviceFamily, set[InterfaceType]] | None] = None

    @classmethod
    def _ensure_family_lookup(cls) -> dict[DeviceFamily, FamilyMetadata]:
        if cls._family_by_enum is None:
            cls._family_by_enum = {f.family: f for f in cls.FAMILIES}
        return cls._family_by_enum

    @classmethod
    def _ensure_interface_lookup(cls) -> dict[InterfaceType, InterfaceMetadata]:
        if cls._interface_by_enum is None:
            cls._interface_by_enum = {i.interface: i for i in cls.INTERFACES}
        return cls._interface_by_enum

    @classmethod
    def _ensure_available_connections(cls) -> dict[DeviceFamily, set[InterfaceType]]:
        """Build available connections from device registry."""
        if cls._available_connections is None:
            connections: dict[DeviceFamily, set[InterfaceType]] = {}
            for spec in DEVICE_REGISTRY.values():
                if spec.is_coordinator:
                    continue
                family = spec.family
                interface = spec.interface_type
                if family not in connections:
                    connections[family] = set()
                connections[family].add(interface)
            cls._available_connections = connections
        return cls._available_connections

    # =========================================================================
    # Family Methods
    # =========================================================================

    @classmethod
    def families_ordered(cls) -> list[FamilyMetadata]:
        """Get all families in display order."""
        return sorted(cls.FAMILIES, key=lambda f: f.display_order)

    @classmethod
    def get_family_metadata(cls, family: DeviceFamily) -> FamilyMetadata | None:
        """Get metadata for a specific family."""
        return cls._ensure_family_lookup().get(family)

    @classmethod
    def get_family_display_name(cls, family: DeviceFamily) -> str:
        """Get display name for a family."""
        meta = cls.get_family_metadata(family)
        return meta.display_name if meta else family.value

    @classmethod
    def get_family_order(cls) -> list[DeviceFamily]:
        """Get families in display order (just the enums)."""
        return [f.family for f in cls.families_ordered()]

    # =========================================================================
    # Interface Methods
    # =========================================================================

    @classmethod
    def interfaces_ordered(cls) -> list[InterfaceMetadata]:
        """Get all interfaces in display order."""
        return sorted(cls.INTERFACES, key=lambda i: i.display_order)

    @classmethod
    def get_interface_metadata(cls, interface: InterfaceType) -> InterfaceMetadata | None:
        """Get metadata for a specific interface."""
        return cls._ensure_interface_lookup().get(interface)

    @classmethod
    def get_interface_display_name(cls, interface: InterfaceType) -> str:
        """Get display name for an interface."""
        meta = cls.get_interface_metadata(interface)
        return meta.display_name if meta else interface.value

    @classmethod
    def get_interface_order(cls) -> list[InterfaceType]:
        """Get interfaces in display order (just the enums)."""
        return [i.interface for i in cls.interfaces_ordered()]

    # =========================================================================
    # Connection Methods
    # =========================================================================

    @classmethod
    def get_available_connections(cls) -> dict[DeviceFamily, set[InterfaceType]]:
        """
        Get all available family+interface combinations.

        Returns:
            Dict mapping DeviceFamily to set of InterfaceType that support it.
        """
        return cls._ensure_available_connections().copy()

    @classmethod
    def get_interfaces_for_family(cls, family: DeviceFamily) -> list[InterfaceType]:
        """
        Get interfaces available for a family, in display order.

        Returns:
            List of InterfaceType in display order.
        """
        available = cls._ensure_available_connections()
        interfaces = available.get(family, set())
        interface_order = cls.get_interface_order()
        return [i for i in interface_order if i in interfaces]

    @classmethod
    def get_families_for_interface(cls, interface: InterfaceType) -> list[DeviceFamily]:
        """
        Get families available for an interface, in display order.

        Returns:
            List of DeviceFamily in display order.
        """
        available = cls._ensure_available_connections()
        families = [f for f, interfaces in available.items() if interface in interfaces]
        family_order = cls.get_family_order()
        return [f for f in family_order if f in families]

    @classmethod
    def is_valid_connection(cls, interface: InterfaceType, family: DeviceFamily) -> bool:
        """Check if a family+interface combination is valid."""
        available = cls._ensure_available_connections()
        return family in available and interface in available[family]

    # =========================================================================
    # Display Name Building
    # =========================================================================

    @classmethod
    def extract_short_device_id(cls, device_id: str, interface: InterfaceType) -> str:
        """
        Extract a short, human-readable device identifier.

        Args:
            device_id: Full device identifier (e.g., /dev/ttyACM0, node_id, etc.)
            interface: Interface type to determine extraction method

        Returns:
            Short identifier like "ACM0", "video0", etc.
        """
        if not device_id:
            return ""

        # For USB serial devices: extract "ACM0" from "/dev/ttyACM0"
        if interface == InterfaceType.USB and "/" in device_id:
            short = device_id.split("/")[-1]
            if short.startswith("tty"):
                return short[3:]  # Remove "tty" prefix
            return short

        # For UART devices: extract "serial0" from "/dev/serial0"
        if interface == InterfaceType.UART and "/" in device_id:
            return device_id.split("/")[-1]

        # For CSI cameras: extract "0" from "csi_0"
        if interface == InterfaceType.CSI and device_id.startswith("csi_"):
            return device_id[4:]

        # For network devices: use as-is if short, truncate if long
        if interface == InterfaceType.NETWORK:
            if len(device_id) > 12:
                return device_id[:12]
            return device_id

        # For XBee wireless: use first 8 chars of node_id if long
        if interface == InterfaceType.XBEE:
            if len(device_id) > 8:
                return device_id[:8]
            return device_id

        # For internal devices: use as-is
        if interface == InterfaceType.INTERNAL:
            return device_id.replace("internal_", "")

        # Default: use last part if path-like, otherwise full id
        if "/" in device_id:
            return device_id.split("/")[-1]

        return device_id

    @classmethod
    def build_device_display_name(
        cls,
        raw_name: str | None,
        family: DeviceFamily,
        interface: InterfaceType,
        device_id: str = "",
        include_interface: bool = True,
    ) -> str:
        """
        Build a consistent display name for a device.

        Args:
            raw_name: Raw name from scanner (e.g., camera name, audio device name)
            family: Device family
            interface: Interface type
            device_id: Full device identifier for extracting short ID
            include_interface: Whether to append interface hint

        Returns:
            Formatted display name like "VOG(USB):ACM0" or "Camera(CSI):0"
        """
        base_name = raw_name or cls.get_family_display_name(family)

        if include_interface:
            interface_hint = cls.get_interface_display_name(interface)
            short_id = cls.extract_short_device_id(device_id, interface) if device_id else ""
            if short_id:
                return f"{base_name}({interface_hint}):{short_id}"
            return f"{base_name}({interface_hint})"

        return base_name

    # =========================================================================
    # Device Type Helpers
    # =========================================================================

    @classmethod
    def get_family_for_device_type(cls, device_type: DeviceType) -> DeviceFamily | None:
        """Get the family for a device type."""
        spec = DEVICE_REGISTRY.get(device_type)
        return spec.family if spec else None

    @classmethod
    def get_interface_for_device_type(cls, device_type: DeviceType) -> InterfaceType | None:
        """Get the interface for a device type."""
        spec = DEVICE_REGISTRY.get(device_type)
        return spec.interface_type if spec else None

    # =========================================================================
    # Module Mapping
    # =========================================================================

    @classmethod
    def get_module_connection_map(cls) -> dict[str, tuple[InterfaceType, DeviceFamily]]:
        """
        Build mapping from module names to their primary (interface, family).

        This is derived from the device registry's module_id fields,
        providing a single source of truth for which modules handle which
        connection types.

        Returns:
            Dict mapping module_id to (InterfaceType, DeviceFamily).
            Each module appears only once with its primary interface.
        """
        module_map: dict[str, tuple[InterfaceType, DeviceFamily]] = {}

        for spec in DEVICE_REGISTRY.values():
            if spec.is_coordinator or not spec.module_id:
                continue

            module_id = spec.module_id
            # Skip if we already have this module (use first occurrence)
            if module_id in module_map:
                continue

            module_map[module_id] = (spec.interface_type, spec.family)

        return module_map
