"""
VOG module API controller mixin.

Provides VOG-specific methods that are dynamically added to APIController.
"""

from typing import Any, Dict, Optional


class VOGApiMixin:
    """
    Mixin class providing VOG module API methods.

    These methods are dynamically bound to the APIController instance
    at startup, giving them access to self.logger_system, self.session_active, etc.
    """

    async def list_vog_devices(self) -> Dict[str, Any]:
        """List all discovered/connected VOG devices.

        Returns devices filtered to VOG family with their device types
        from discovery metadata.

        Returns:
            Dict with devices list containing device info.
        """
        devices = []
        all_devices = await self.list_devices()

        for device in all_devices:
            # Filter to VOG devices only
            if device.get("module_id", "").upper() == "VOG":
                # Use device_type from discovery (returned as 'family' in list_devices)
                devices.append({
                    "device_id": device.get("device_id"),
                    "display_name": device.get("display_name"),
                    "device_type": device.get("family"),
                    "connected": device.get("connected", False),
                    "connecting": device.get("connecting", False),
                    "is_wireless": device.get("is_wireless", False),
                    "port": device.get("port"),
                })

        return {
            "devices": devices,
            "count": len(devices),
        }

    async def get_vog_config(self, device_id: Optional[str] = None) -> Dict[str, Any]:
        """Get VOG device configuration.

        Args:
            device_id: Optional specific device ID, or None for all devices

        Returns:
            Dict with configuration data.
        """
        # First get the module config
        module_config = await self.get_module_config("VOG")

        if device_id:
            # Get config for specific device by sending command to module
            device = await self.get_device(device_id)
            if not device:
                return {
                    "success": False,
                    "error": "device_not_found",
                    "message": f"Device '{device_id}' not found",
                }

            # Request device config via module command
            result = await self.send_module_command("VOG", "get_config", device_id=device_id)
            return {
                "success": True,
                "device_id": device_id,
                "module_config": module_config.get("config", {}) if module_config else {},
                "device_config": result.get("config", {}),
            }

        # Return module-level config
        return {
            "success": True,
            "module_config": module_config.get("config", {}) if module_config else {},
            "config_path": module_config.get("config_path") if module_config else None,
        }

    async def update_vog_config(
        self, device_id: Optional[str], config_updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update VOG configuration.

        Args:
            device_id: Optional device ID for device-specific config
            config_updates: Dictionary of configuration updates

        Returns:
            Result dict with success status.
        """
        if device_id:
            # Update device-specific config
            device = await self.get_device(device_id)
            if not device:
                return {
                    "success": False,
                    "error": "device_not_found",
                    "message": f"Device '{device_id}' not found",
                }

            # Send config updates to device via module command
            for param, value in config_updates.items():
                result = await self.send_module_command(
                    "VOG", "set_config",
                    device_id=device_id,
                    param=param,
                    value=str(value),
                )
                if not result.get("success"):
                    return {
                        "success": False,
                        "error": "config_update_failed",
                        "message": f"Failed to update '{param}'",
                        "param": param,
                    }

            return {
                "success": True,
                "device_id": device_id,
                "updated": list(config_updates.keys()),
            }

        # Update module-level config
        return await self.update_module_config("VOG", config_updates)

    async def get_vog_eye_position(self, device_id: Optional[str] = None) -> Dict[str, Any]:
        """Get current eye position / shutter timing data from VOG devices.

        VOG devices track shutter open/closed timing rather than direct eye position.
        This endpoint returns the latest timing data.

        Args:
            device_id: Optional specific device ID

        Returns:
            Dict with eye position/shutter timing data.
        """
        # Get connected VOG devices
        vog_devices = await self.list_vog_devices()
        devices = vog_devices.get("devices", [])

        if device_id:
            # Find specific device
            device = next((d for d in devices if d.get("device_id") == device_id), None)
            if not device:
                return {
                    "success": False,
                    "error": "device_not_found",
                    "message": f"VOG device '{device_id}' not found",
                }

            if not device.get("connected"):
                return {
                    "success": False,
                    "error": "device_not_connected",
                    "message": f"VOG device '{device_id}' is not connected",
                }

            # Get data from the device via module command
            result = await self.send_module_command(
                "VOG", "get_eye_position", device_id=device_id
            )
            return {
                "success": True,
                "device_id": device_id,
                "device_type": device.get("device_type"),
                "data": result.get("data", {}),
            }

        # Return data for all connected devices
        data = []
        for device in devices:
            if device.get("connected"):
                result = await self.send_module_command(
                    "VOG", "get_eye_position", device_id=device.get("device_id")
                )
                data.append({
                    "device_id": device.get("device_id"),
                    "device_type": device.get("device_type"),
                    "data": result.get("data", {}),
                })

        return {
            "success": True,
            "devices": data,
        }

    async def get_vog_pupil_data(self, device_id: Optional[str] = None) -> Dict[str, Any]:
        """Get pupil/shutter state data from VOG devices.

        Note: VOG devices track shutter state (open/closed), not direct pupil measurements.

        Args:
            device_id: Optional specific device ID

        Returns:
            Dict with shutter state data.
        """
        # This is similar to eye_position - VOG devices report shutter state
        return await self.get_vog_eye_position(device_id)

    async def switch_vog_lens(
        self, device_id: Optional[str], lens: str, state: str
    ) -> Dict[str, Any]:
        """Switch VOG lens state (open/closed).

        Args:
            device_id: Optional device ID (if None, applies to all connected)
            lens: Lens to control - 'A', 'B', or 'X' (both). For sVOG, lens is ignored.
            state: Target state - 'open' or 'closed'

        Returns:
            Result dict with success status.
        """
        # Determine the command based on state
        if state == "open":
            command = "peek_open"
        else:
            command = "peek_close"

        if device_id:
            # Switch specific device
            device = await self.get_device(device_id)
            if not device:
                return {
                    "success": False,
                    "error": "device_not_found",
                    "message": f"Device '{device_id}' not found",
                }

            result = await self.send_module_command(
                "VOG", command, device_id=device_id, lens=lens
            )
            return {
                "success": result.get("success", False),
                "device_id": device_id,
                "lens": lens,
                "state": state,
                "message": f"Lens {lens} set to {state}",
            }

        # Apply to all connected VOG devices
        vog_devices = await self.list_vog_devices()
        results = []
        all_success = True

        for device in vog_devices.get("devices", []):
            if device.get("connected"):
                result = await self.send_module_command(
                    "VOG", command,
                    device_id=device.get("device_id"),
                    lens=lens,
                )
                success = result.get("success", False)
                results.append({
                    "device_id": device.get("device_id"),
                    "success": success,
                })
                if not success:
                    all_success = False

        return {
            "success": all_success,
            "lens": lens,
            "state": state,
            "devices": results,
        }

    async def get_vog_battery(self, device_id: Optional[str] = None) -> Dict[str, Any]:
        """Get battery level for wVOG devices.

        Note: Battery monitoring is only available on wVOG (wireless) devices.
        sVOG devices will return battery_supported: false.

        Args:
            device_id: Optional specific device ID

        Returns:
            Dict with battery status.
        """
        vog_devices = await self.list_vog_devices()
        devices = vog_devices.get("devices", [])

        if device_id:
            # Find specific device
            device = next((d for d in devices if d.get("device_id") == device_id), None)
            if not device:
                return {
                    "success": False,
                    "error": "device_not_found",
                    "message": f"VOG device '{device_id}' not found",
                }

            device_type = device.get("device_type", "")

            # Check if device supports battery
            if device_type == "sVOG":
                return {
                    "success": True,
                    "device_id": device_id,
                    "device_type": device_type,
                    "battery_supported": False,
                    "message": "sVOG devices do not support battery monitoring",
                }

            if not device.get("connected"):
                return {
                    "success": False,
                    "error": "device_not_connected",
                    "message": f"Device '{device_id}' is not connected",
                }

            # Request battery status via module command
            result = await self.send_module_command(
                "VOG", "get_battery", device_id=device_id
            )
            return {
                "success": True,
                "device_id": device_id,
                "device_type": device_type,
                "battery_supported": True,
                "battery_percent": result.get("battery_percent", 0),
            }

        # Return battery for all connected wVOG devices
        battery_data = []
        for device in devices:
            device_type = device.get("device_type", "")
            dev_id = device.get("device_id")

            if device_type == "sVOG":
                battery_data.append({
                    "device_id": dev_id,
                    "device_type": device_type,
                    "battery_supported": False,
                })
            elif device.get("connected"):
                result = await self.send_module_command(
                    "VOG", "get_battery", device_id=dev_id
                )
                battery_data.append({
                    "device_id": dev_id,
                    "device_type": device_type,
                    "battery_supported": True,
                    "battery_percent": result.get("battery_percent", 0),
                })

        return {
            "success": True,
            "devices": battery_data,
        }

    async def get_vog_status(self) -> Dict[str, Any]:
        """Get comprehensive VOG module status.

        Returns:
            Dict with module status including:
            - Module running state
            - Connected devices
            - Recording state
            - Session information
        """
        # Get module info
        module = await self.get_module("VOG")
        if not module:
            return {
                "success": False,
                "error": "module_not_found",
                "message": "VOG module not found",
            }

        # Get VOG devices
        vog_devices = await self.list_vog_devices()

        # Get session info
        session_info = await self.get_session_info()

        return {
            "success": True,
            "module": {
                "name": module.get("name"),
                "display_name": module.get("display_name"),
                "enabled": module.get("enabled"),
                "running": module.get("running"),
                "state": module.get("state"),
            },
            "devices": vog_devices.get("devices", []),
            "device_count": vog_devices.get("count", 0),
            "connected_count": sum(
                1 for d in vog_devices.get("devices", []) if d.get("connected")
            ),
            "session_active": session_info.get("session_active", False),
            "recording": session_info.get("recording", False),
            "session_dir": session_info.get("session_dir"),
        }
