"""
DRT module API controller mixin.

Provides DRT-specific methods that are dynamically added to APIController.
"""

from typing import Any, Dict, List, Optional


class DRTApiMixin:
    """
    Mixin class providing DRT module API methods.

    These methods are dynamically bound to the APIController instance
    at startup, giving them access to self.logger_system, self.session_active, etc.
    """

    async def _get_drt_instances(self) -> List[Dict[str, Any]]:
        """Get all running DRT module instances with their handlers.

        Returns:
            List of dicts with instance_id, device_id, device_type, handler info
        """
        instances = []
        instance_manager = self.logger_system.instance_manager

        for instance_id, state in instance_manager._instances.items():
            if state.module_id != "DRT":
                continue

            # Get the runtime from the process if available
            handler_info = None
            device_id = state.device_id

            # Try to get handler info via command
            try:
                # Send a status query command to get runtime state
                result = await self.logger_system.send_instance_command(
                    instance_id, "get_status"
                )
                if result:
                    handler_info = result
            except Exception:
                pass

            instances.append({
                "instance_id": instance_id,
                "device_id": device_id,
                "module_id": state.module_id,
                "state": state.state.value,
                "handler_info": handler_info,
            })

        return instances

    async def list_drt_devices(self) -> Dict[str, Any]:
        """List all available DRT devices (connected and discovered).

        Returns:
            Dict with list of DRT devices and their status.
        """
        devices = []

        # Get discovered DRT devices from device system
        for device in self.logger_system.device_system.get_all_devices():
            if device.module_id != "DRT":
                continue

            is_connected = self.logger_system.device_system.is_device_connected(
                device.device_id
            )
            is_connecting = self.logger_system.device_system.is_device_connecting(
                device.device_id
            )

            # Use device_type from discovery (already determined by device registry)
            device_type = device.device_type.value if device.device_type else "unknown"

            devices.append({
                "device_id": device.device_id,
                "display_name": device.display_name,
                "device_type": device_type,
                "port": device.port,
                "is_wireless": device.is_wireless,
                "connected": is_connected,
                "connecting": is_connecting,
            })

        return {
            "devices": devices,
            "count": len(devices),
        }

    async def get_drt_config(
        self, device_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get DRT device configuration.

        Args:
            device_id: Optional specific device ID. If None, returns config
                      for all connected devices or module defaults.

        Returns:
            Dict with configuration data.
        """
        # Get module-level config
        module_config = await self.get_module_config("DRT")

        # If no device specified, return module config
        if device_id is None:
            # Try to get config from first connected device
            instances = await self._get_drt_instances()
            if not instances:
                return {
                    "module_config": module_config.get("config", {}) if module_config else {},
                    "device_config": None,
                    "message": "No DRT devices connected - returning module defaults",
                }

            # Use first instance
            device_id = instances[0].get("device_id")

        # Send get_config command to the device's module instance
        result = await self.send_module_command("DRT", "get_config", device_id=device_id)

        return {
            "device_id": device_id,
            "module_config": module_config.get("config", {}) if module_config else {},
            "device_config": result.get("config") if result.get("success") else None,
            "success": result.get("success", False),
        }

    async def update_drt_config(
        self,
        updates: Dict[str, Any],
        device_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update DRT configuration.

        Args:
            updates: Configuration key-value pairs to update.
                    Supported keys depend on device type:
                    - lowerISI: Lower inter-stimulus interval (ms)
                    - upperISI: Upper inter-stimulus interval (ms)
                    - stimDur: Stimulus duration (ms)
                    - intensity: Stimulus intensity (0-255)
            device_id: Optional specific device ID.

        Returns:
            Result dict with success status.
        """
        if not updates:
            return {
                "success": False,
                "error": "empty_updates",
                "message": "No configuration updates provided",
            }

        # If no device specified, apply to first connected device
        if device_id is None:
            instances = await self._get_drt_instances()
            if not instances:
                return {
                    "success": False,
                    "error": "no_devices",
                    "message": "No DRT devices connected",
                }
            device_id = instances[0].get("device_id")

        # Send configuration updates to the device
        results = {}
        for key, value in updates.items():
            result = await self.send_module_command(
                "DRT", "set_config_param", device_id=device_id, param=key, value=value
            )
            results[key] = result.get("success", False)

        all_success = all(results.values())
        return {
            "success": all_success,
            "device_id": device_id,
            "updated": results,
            "message": "Configuration updated" if all_success else "Some updates failed",
        }

    async def trigger_drt_stimulus(
        self,
        device_id: Optional[str] = None,
        on: bool = True,
        duration_ms: Optional[int] = None
    ) -> Dict[str, Any]:
        """Trigger manual stimulus on DRT device.

        Args:
            device_id: Optional specific device ID.
            on: True to turn stimulus on, False to turn off.
            duration_ms: Optional auto-off duration in milliseconds.

        Returns:
            Result dict with success status.
        """
        # If no device specified, use first connected device
        if device_id is None:
            instances = await self._get_drt_instances()
            if not instances:
                return {
                    "success": False,
                    "error": "no_devices",
                    "message": "No DRT devices connected",
                }
            device_id = instances[0].get("device_id")

        # Send stimulus command
        result = await self.send_module_command(
            "DRT", "set_stimulus", device_id=device_id, on=on
        )

        response = {
            "success": result.get("success", False),
            "device_id": device_id,
            "stimulus_state": "on" if on else "off",
        }

        # If duration specified, schedule auto-off (handled by module)
        if on and duration_ms and result.get("success"):
            response["auto_off_ms"] = duration_ms

        return response

    async def get_drt_responses(
        self,
        device_id: Optional[str] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """Get recent DRT response data.

        Args:
            device_id: Optional specific device ID.
            limit: Maximum number of responses to return.

        Returns:
            Dict with recent response data.
        """
        responses = []
        instances = await self._get_drt_instances()

        if device_id:
            # Filter to specific device
            instances = [i for i in instances if i.get("device_id") == device_id]

        if not instances:
            return {
                "device_id": device_id,
                "responses": [],
                "count": 0,
                "message": "No DRT devices connected or no data available",
            }

        # For each instance, try to read recent trial data
        for instance in instances:
            inst_device_id = instance.get("device_id")
            # Send command to get recent responses from module's buffer
            result = await self.send_module_command(
                "DRT", "get_recent_responses",
                device_id=inst_device_id,
                limit=limit
            )
            if result.get("success") and result.get("responses"):
                for resp in result.get("responses", []):
                    resp["device_id"] = inst_device_id
                    responses.append(resp)

        return {
            "device_id": device_id,
            "responses": responses[:limit],
            "count": len(responses),
        }

    async def get_drt_statistics(
        self,
        device_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get DRT session statistics.

        Args:
            device_id: Optional specific device ID.

        Returns:
            Dict with session statistics including:
            - trial_count: Total number of trials
            - hit_count: Number of hits (responses within time limit)
            - miss_count: Number of misses (no response/timeout)
            - avg_reaction_time_ms: Average reaction time for hits
            - min_reaction_time_ms: Minimum reaction time
            - max_reaction_time_ms: Maximum reaction time
        """
        instances = await self._get_drt_instances()

        if device_id:
            instances = [i for i in instances if i.get("device_id") == device_id]

        if not instances:
            return {
                "device_id": device_id,
                "statistics": None,
                "message": "No DRT devices connected",
            }

        # Aggregate statistics from all devices (or single device)
        all_stats = []
        for instance in instances:
            inst_device_id = instance.get("device_id")
            result = await self.send_module_command(
                "DRT", "get_statistics", device_id=inst_device_id
            )
            if result.get("success") and result.get("statistics"):
                stats = result.get("statistics")
                stats["device_id"] = inst_device_id
                all_stats.append(stats)

        if len(all_stats) == 1:
            return {
                "device_id": all_stats[0].get("device_id"),
                "statistics": all_stats[0],
            }
        elif len(all_stats) > 1:
            return {
                "device_id": device_id,
                "statistics": all_stats,
                "aggregated": True,
            }
        else:
            # Return empty statistics structure
            return {
                "device_id": device_id,
                "statistics": {
                    "trial_count": 0,
                    "hit_count": 0,
                    "miss_count": 0,
                    "avg_reaction_time_ms": None,
                    "min_reaction_time_ms": None,
                    "max_reaction_time_ms": None,
                },
                "message": "No statistics available - start recording to collect data",
            }

    async def get_drt_battery(
        self,
        device_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get battery level for wDRT devices.

        Args:
            device_id: Optional specific device ID.

        Returns:
            Dict with battery information.
        """
        instances = await self._get_drt_instances()

        if device_id:
            instances = [i for i in instances if i.get("device_id") == device_id]

        if not instances:
            return {
                "device_id": device_id,
                "battery_percent": None,
                "message": "No DRT devices connected",
            }

        # Get battery from devices (wDRT only)
        battery_info = []
        for instance in instances:
            inst_device_id = instance.get("device_id")
            result = await self.send_module_command(
                "DRT", "get_battery", device_id=inst_device_id
            )
            if result.get("success"):
                battery_info.append({
                    "device_id": inst_device_id,
                    "battery_percent": result.get("battery_percent"),
                    "is_wireless": True,  # Battery only available on wDRT
                })
            else:
                # Device might be sDRT (no battery)
                battery_info.append({
                    "device_id": inst_device_id,
                    "battery_percent": None,
                    "is_wireless": False,
                    "message": "Battery not available (sDRT device)",
                })

        if len(battery_info) == 1:
            return battery_info[0]
        else:
            return {
                "devices": battery_info,
                "count": len(battery_info),
            }

    async def get_drt_status(self) -> Dict[str, Any]:
        """Get overall DRT module status.

        Returns:
            Dict with module and device status information.
        """
        # Get module status
        module = await self.get_module("DRT")
        module_enabled = module.get("enabled", False) if module else False
        module_running = module.get("running", False) if module else False

        # Get connected devices
        devices_result = await self.list_drt_devices()
        devices = devices_result.get("devices", [])
        connected_count = sum(1 for d in devices if d.get("connected"))

        # Get running instances
        instances = await self._get_drt_instances()

        # Check recording state
        recording = False
        for instance in instances:
            if instance.get("handler_info", {}).get("recording"):
                recording = True
                break

        return {
            "module_enabled": module_enabled,
            "module_running": module_running,
            "devices_discovered": len(devices),
            "devices_connected": connected_count,
            "instances_running": len(instances),
            "recording": recording,
            "devices": devices,
            "instances": instances,
        }
