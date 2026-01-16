"""
GPS module API controller mixin.

Provides GPS-specific methods that are dynamically added to APIController.
"""

from typing import Any, Dict, Optional


class GPSApiMixin:
    """
    Mixin class providing GPS module API methods.

    These methods are dynamically bound to the APIController instance
    at startup, giving them access to self.logger_system, self.session_active, etc.
    """

    async def get_gps_devices(self) -> Dict[str, Any]:
        """Get list of available GPS devices.

        Returns GPS devices that are discovered or connected, filtered
        from the general device system.

        Returns:
            Dict with list of GPS devices and their status.
        """
        devices = []

        # Get all devices from device system and filter for GPS
        for device in self.logger_system.device_system.get_all_devices():
            # Check if device is a GPS device by module_id
            if device.module_id and "gps" in device.module_id.lower():
                devices.append({
                    "device_id": device.device_id,
                    "display_name": device.display_name,
                    "port": device.port,
                    "baudrate": device.baudrate,
                    "connected": self.logger_system.device_system.is_device_connected(
                        device.device_id
                    ),
                    "connecting": self.logger_system.device_system.is_device_connecting(
                        device.device_id
                    ),
                    "interface": device.interface.value if device.interface else None,
                })

        return {
            "devices": devices,
            "count": len(devices),
        }

    async def get_gps_config(self) -> Optional[Dict[str, Any]]:
        """Get GPS module configuration.

        Returns:
            Dict with GPS config values, or None if GPS module not found.
        """
        # Use the existing module config method
        return await self.get_module_config("GPS")

    async def update_gps_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update GPS module configuration.

        Args:
            updates: Dictionary of config key-value pairs to update

        Returns:
            Result dict with success status.
        """
        return await self.update_module_config("GPS", updates)

    async def get_gps_position(
        self, device_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Get current GPS position.

        Retrieves current position (latitude, longitude, altitude) from
        the GPS module if running and a valid fix is available.

        Args:
            device_id: Optional device ID for specific device

        Returns:
            Dict with position data, or None if GPS not available.
        """
        # Check if GPS module is running
        if not self.logger_system.is_module_running("GPS"):
            return None

        # Send command to get position from GPS module
        result = await self.logger_system.send_module_command(
            "GPS", "get_position", device_id=device_id
        )

        # If command succeeded and returned data, format response
        if result:
            return {
                "available": True,
                "device_id": device_id,
                "latitude": result.get("latitude"),
                "longitude": result.get("longitude"),
                "altitude_m": result.get("altitude_m"),
                "speed_knots": result.get("speed_knots"),
                "speed_kmh": result.get("speed_kmh"),
                "course_deg": result.get("course_deg"),
                "timestamp": result.get("timestamp"),
                "fix_valid": result.get("fix_valid", False),
            }

        # Return basic status if command didn't return data
        return {
            "available": True,
            "device_id": device_id,
            "message": "GPS module running - position data pending",
            "note": "Connect GPS device for live position data",
        }

    async def get_gps_satellites(
        self, device_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Get satellite information.

        Returns satellite tracking data including satellites in use/view
        and dilution of precision values.

        Args:
            device_id: Optional device ID for specific device

        Returns:
            Dict with satellite data, or None if GPS not available.
        """
        if not self.logger_system.is_module_running("GPS"):
            return None

        # Send command to get satellite info from GPS module
        result = await self.logger_system.send_module_command(
            "GPS", "get_satellites", device_id=device_id
        )

        if result:
            return {
                "available": True,
                "device_id": device_id,
                "satellites_in_use": result.get("satellites_in_use"),
                "satellites_in_view": result.get("satellites_in_view"),
                "hdop": result.get("hdop"),
                "vdop": result.get("vdop"),
                "pdop": result.get("pdop"),
            }

        return {
            "available": True,
            "device_id": device_id,
            "message": "GPS module running - satellite data pending",
            "note": "Connect GPS device for satellite information",
        }

    async def get_gps_fix(
        self, device_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Get GPS fix quality and status.

        Returns fix information including validity, quality, mode,
        and age of the fix.

        Args:
            device_id: Optional device ID for specific device

        Returns:
            Dict with fix data, or None if GPS not available.
        """
        if not self.logger_system.is_module_running("GPS"):
            return None

        # Send command to get fix info from GPS module
        result = await self.logger_system.send_module_command(
            "GPS", "get_fix", device_id=device_id
        )

        if result and result.get("available"):
            return {
                "available": True,
                "device_id": result.get("device_id", device_id),
                "fix_valid": result.get("fix_valid", False),
                "fix_quality": result.get("fix_quality"),
                "fix_quality_desc": result.get("fix_quality_desc"),
                "fix_mode": result.get("fix_mode"),
                "age_seconds": result.get("age_seconds"),
                "connected": result.get("connected", False),
                "error": result.get("error"),
            }

        return {
            "available": True,
            "device_id": device_id,
            "fix_valid": False,
            "message": "GPS module running - fix data pending",
            "note": "Connect GPS device for fix information",
        }

    async def get_gps_nmea_raw(
        self, device_id: Optional[str] = None, limit: int = 0
    ) -> Optional[Dict[str, Any]]:
        """Get raw NMEA sentences.

        Returns the most recent raw NMEA sentences received from the GPS.

        Args:
            device_id: Optional device ID for specific device
            limit: Maximum number of sentences to return (0 = all available)

        Returns:
            Dict with NMEA sentences, or None if GPS not available.
        """
        if not self.logger_system.is_module_running("GPS"):
            return None

        # Send command to get NMEA data from GPS module
        result = await self.logger_system.send_module_command(
            "GPS", "get_nmea_raw", device_id=device_id, limit=limit
        )

        if result:
            sentences = result.get("sentences", [])
            if limit > 0:
                sentences = sentences[-limit:]
            return {
                "available": True,
                "device_id": device_id,
                "count": len(sentences),
                "sentences": sentences,
                "last_sentence": result.get("last_sentence"),
            }

        return {
            "available": True,
            "device_id": device_id,
            "count": 0,
            "sentences": [],
            "message": "GPS module running - NMEA data pending",
            "note": "Connect GPS device for NMEA sentences",
        }

    async def get_gps_status(self) -> Optional[Dict[str, Any]]:
        """Get GPS module status.

        Returns comprehensive status including module state, connected
        devices, recording status, and current session information.

        Returns:
            Dict with GPS status, or None if module not found.
        """
        # Check if GPS module exists
        module = await self.get_module("GPS")
        if not module:
            return None

        # Get GPS devices
        gps_devices = await self.get_gps_devices()

        # Build status response
        return {
            "module": {
                "name": module["name"],
                "display_name": module["display_name"],
                "enabled": module["enabled"],
                "running": module["running"],
                "state": module["state"],
            },
            "devices": gps_devices["devices"],
            "device_count": gps_devices["count"],
            "session_active": self.session_active,
            "trial_active": self.trial_active,
            "trial_number": self.trial_counter if self.trial_active else None,
            "session_dir": str(self._session_dir) if self._session_dir else None,
        }
