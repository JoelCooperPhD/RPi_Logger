"""
EyeTracker module API controller mixin.

Provides EyeTracker (Pupil Labs Neon) specific methods that are
dynamically added to APIController.
"""

from typing import Any, Dict, Optional


class EyeTrackerApiMixin:
    """
    Mixin class providing EyeTracker module API methods.

    These methods are dynamically bound to the APIController instance
    at startup, giving them access to self.logger_system, self.session_active, etc.
    """

    async def list_eyetracker_devices(self) -> Dict[str, Any]:
        """List available eye tracker devices.

        Returns all discovered Pupil Labs Neon devices from the device system.
        """
        devices = []

        # Filter devices by module_id for EyeTracker
        for device in self.logger_system.device_system.get_all_devices():
            if device.module_id and "eyetracker" in device.module_id.lower():
                devices.append({
                    "device_id": device.device_id,
                    "display_name": device.display_name,
                    "network_address": device.port,  # For network devices
                    "connected": self.logger_system.device_system.is_device_connected(
                        device.device_id
                    ),
                    "connecting": self.logger_system.device_system.is_device_connecting(
                        device.device_id
                    ),
                    "is_wireless": device.is_wireless,
                    "metadata": device.metadata,
                })

        return {
            "devices": devices,
            "count": len(devices),
        }

    async def get_eyetracker_config(self) -> Optional[Dict[str, Any]]:
        """Get EyeTracker module configuration.

        Returns the current configuration settings for the EyeTracker module.
        """
        return await self.get_module_config("EyeTracker")

    async def update_eyetracker_config(
        self, updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update EyeTracker module configuration.

        Args:
            updates: Dictionary of configuration key-value pairs to update

        Returns:
            Result dict with success status
        """
        return await self.update_module_config("EyeTracker", updates)

    async def get_eyetracker_gaze_data(self) -> Optional[Dict[str, Any]]:
        """Get current gaze data from the eye tracker.

        Returns the most recent gaze sample with coordinates and metadata.
        """
        # Send command to get gaze data from the running module
        result = await self.send_module_command("EyeTracker", "get_gaze_data")

        if not result.get("success"):
            return None

        gaze_data = result.get("gaze_data")
        if gaze_data is None:
            return None

        # Format gaze data for API response
        return {
            "x": getattr(gaze_data, "x", None),
            "y": getattr(gaze_data, "y", None),
            "timestamp_unix_seconds": getattr(
                gaze_data, "timestamp_unix_seconds", None
            ),
            "worn": getattr(gaze_data, "worn", None),
            "available": True,
        }

    async def get_eyetracker_imu_data(self) -> Optional[Dict[str, Any]]:
        """Get current IMU data from the eye tracker.

        Returns accelerometer and gyroscope readings.
        """
        result = await self.send_module_command("EyeTracker", "get_imu_data")

        if not result.get("success"):
            return None

        imu_data = result.get("imu_data")
        if imu_data is None:
            return None

        # Format IMU data for API response
        return {
            "accelerometer": {
                "x": getattr(imu_data, "accel_x", None),
                "y": getattr(imu_data, "accel_y", None),
                "z": getattr(imu_data, "accel_z", None),
            },
            "gyroscope": {
                "x": getattr(imu_data, "gyro_x", None),
                "y": getattr(imu_data, "gyro_y", None),
                "z": getattr(imu_data, "gyro_z", None),
            },
            "timestamp_unix_seconds": getattr(
                imu_data, "timestamp_unix_seconds", None
            ),
            "available": True,
        }

    async def get_eyetracker_events(
        self, limit: int = 10
    ) -> Optional[Dict[str, Any]]:
        """Get recent eye events from the eye tracker.

        Args:
            limit: Maximum number of events to return

        Returns:
            Dict with list of recent eye events
        """
        result = await self.send_module_command(
            "EyeTracker", "get_eye_events", limit=limit
        )

        if not result.get("success"):
            return None

        events = result.get("events", [])

        return {
            "events": events,
            "count": len(events),
            "limit": limit,
        }

    async def start_eyetracker_calibration(self) -> Dict[str, Any]:
        """Start eye tracker calibration.

        Triggers the calibration workflow on the Neon device.
        Note: Calibration requires user interaction on the Companion app.
        """
        result = await self.send_module_command("EyeTracker", "start_calibration")

        if result.get("success"):
            self.logger.info("EyeTracker calibration started")
            return {
                "success": True,
                "message": "Calibration started - complete calibration on Neon Companion app",
            }

        return {
            "success": False,
            "error": "calibration_failed",
            "message": result.get("message", "Failed to start calibration"),
        }

    async def get_eyetracker_calibration_status(self) -> Optional[Dict[str, Any]]:
        """Get eye tracker calibration status.

        Returns information about the current calibration state.
        """
        result = await self.send_module_command(
            "EyeTracker", "get_calibration_status"
        )

        if not result.get("success"):
            return None

        return {
            "is_calibrated": result.get("is_calibrated", False),
            "calibration_time": result.get("calibration_time"),
            "calibration_quality": result.get("calibration_quality"),
        }

    async def get_eyetracker_status(self) -> Dict[str, Any]:
        """Get comprehensive EyeTracker module status.

        Returns detailed status including connection, streaming, and metrics.
        """
        # Get basic module info
        module = await self.get_module("EyeTracker")
        if not module:
            return {
                "module_found": False,
                "error": "EyeTracker module not found",
            }

        # Get device connection status
        eyetracker_devices = await self.list_eyetracker_devices()
        connected_devices = [
            d for d in eyetracker_devices.get("devices", []) if d.get("connected")
        ]

        # Try to get runtime metrics via command
        metrics_result = await self.send_module_command("EyeTracker", "get_metrics")
        metrics = metrics_result.get("metrics", {}) if metrics_result.get("success") else {}

        # Try to get recording status
        recording_result = await self.send_module_command(
            "EyeTracker", "get_recording_status"
        )

        return {
            "module_found": True,
            "module_name": module.get("name"),
            "module_state": module.get("state"),
            "enabled": module.get("enabled"),
            "running": module.get("running"),
            "device_connected": len(connected_devices) > 0,
            "connected_devices": connected_devices,
            "recording": recording_result.get("recording", False)
                if recording_result.get("success") else False,
            "metrics": {
                "fps_capture": metrics.get("fps_capture"),
                "fps_display": metrics.get("fps_display"),
                "fps_record": metrics.get("fps_record"),
                "target_fps": metrics.get("target_fps"),
            },
        }

    async def get_eyetracker_stream_settings(self) -> Optional[Dict[str, Any]]:
        """Get EyeTracker stream enable/disable states.

        Returns the current state of each data stream.
        """
        config = await self.get_eyetracker_config()
        if config is None:
            return None

        config_data = config.get("config", {})

        return {
            "streams": {
                "video": config_data.get("stream_video_enabled", True),
                "gaze": config_data.get("stream_gaze_enabled", True),
                "eyes": config_data.get("stream_eyes_enabled", True),
                "imu": config_data.get("stream_imu_enabled", True),
                "events": config_data.get("stream_events_enabled", True),
                "audio": config_data.get("stream_audio_enabled", True),
            }
        }

    async def set_eyetracker_stream_enabled(
        self, stream_type: str, enabled: bool
    ) -> Dict[str, Any]:
        """Enable or disable a specific EyeTracker data stream.

        Args:
            stream_type: One of 'video', 'gaze', 'eyes', 'imu', 'events', 'audio'
            enabled: Whether to enable or disable the stream

        Returns:
            Result dict with success status
        """
        # Map stream type to config key
        stream_config_keys = {
            "video": "stream_video_enabled",
            "gaze": "stream_gaze_enabled",
            "eyes": "stream_eyes_enabled",
            "imu": "stream_imu_enabled",
            "events": "stream_events_enabled",
            "audio": "stream_audio_enabled",
        }

        config_key = stream_config_keys.get(stream_type)
        if not config_key:
            return {
                "success": False,
                "error": "invalid_stream_type",
                "message": f"Unknown stream type: {stream_type}",
            }

        # Update the config
        result = await self.update_eyetracker_config({config_key: enabled})

        if result.get("success"):
            # Also send command to apply immediately if module is running
            await self.send_module_command(
                "EyeTracker",
                "set_stream_enabled",
                stream_type=stream_type,
                enabled=enabled,
            )

            self.logger.info(
                "EyeTracker stream %s %s",
                stream_type,
                "enabled" if enabled else "disabled",
            )

        return {
            "success": result.get("success", False),
            "stream_type": stream_type,
            "enabled": enabled,
            "message": f"Stream {stream_type} {'enabled' if enabled else 'disabled'}",
        }

    async def start_eyetracker_preview(self) -> Dict[str, Any]:
        """Start the eye tracker preview stream.

        Enables video preview display with gaze overlay.
        """
        result = await self.send_module_command("EyeTracker", "start_preview")

        if result.get("success"):
            self.logger.info("EyeTracker preview started")

        return {
            "success": result.get("success", False),
            "message": "Preview started" if result.get("success") else "Failed to start preview",
        }

    async def stop_eyetracker_preview(self) -> Dict[str, Any]:
        """Stop the eye tracker preview stream.

        Disables video preview to reduce CPU usage.
        """
        result = await self.send_module_command("EyeTracker", "stop_preview")

        if result.get("success"):
            self.logger.info("EyeTracker preview stopped")

        return {
            "success": result.get("success", False),
            "message": "Preview stopped" if result.get("success") else "Failed to stop preview",
        }
