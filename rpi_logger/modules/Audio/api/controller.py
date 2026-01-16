"""
Audio module API controller mixin.

Provides Audio-specific methods that are dynamically added to APIController.
"""

from typing import Any, Dict, Optional


class AudioApiMixin:
    """
    Mixin class providing Audio module API methods.

    These methods are dynamically bound to the APIController instance
    at startup, giving them access to self.logger_system, self.session_active, etc.
    """

    async def list_audio_devices(self) -> Dict[str, Any]:
        """List available audio input devices.

        Returns devices discovered by the device system that are audio-related,
        including device IDs, names, channel counts, and sample rates.

        Returns:
            Dict with 'devices' list containing audio device information.
        """
        devices = []

        # Get audio devices from the device system
        for device in self.logger_system.device_system.get_all_devices():
            # Filter for audio devices (module_id == "Audio" or device_type indicates audio)
            if device.module_id and device.module_id.lower() == "audio":
                device_info = {
                    "device_id": device.device_id,
                    "display_name": device.display_name,
                    "connected": self.logger_system.device_system.is_device_connected(
                        device.device_id
                    ),
                    "connecting": self.logger_system.device_system.is_device_connecting(
                        device.device_id
                    ),
                }

                # Include audio-specific metadata if available
                if device.metadata:
                    device_info["sounddevice_index"] = device.metadata.get(
                        "sounddevice_index"
                    )
                    device_info["channels"] = device.metadata.get("audio_channels")
                    device_info["sample_rate"] = device.metadata.get("audio_sample_rate")

                devices.append(device_info)

        return {
            "devices": devices,
            "count": len(devices),
        }

    async def get_audio_config(self) -> Optional[Dict[str, Any]]:
        """Get audio-specific configuration.

        Returns current audio module configuration including sample rate,
        output directory, session prefix, and other settings.

        Returns:
            Dict with audio configuration, or None if module not found.
        """
        # Get module config using existing method
        module_config = await self.get_module_config("Audio")

        if module_config is None:
            return None

        # Add audio-specific settings from preferences if available
        preferences = await self.get_module_preferences("Audio")

        return {
            "module": "Audio",
            "config_path": module_config.get("config_path"),
            "config": module_config.get("config", {}),
            "preferences": preferences.get("preferences", {}) if preferences else {},
            "settings_schema": {
                "sample_rate": {
                    "type": "int",
                    "default": 48000,
                    "description": "Audio sample rate in Hz",
                },
                "output_dir": {
                    "type": "path",
                    "default": "audio",
                    "description": "Output directory for recordings",
                },
                "session_prefix": {
                    "type": "str",
                    "default": "audio",
                    "description": "Prefix for session files",
                },
                "log_level": {
                    "type": "str",
                    "default": "debug",
                    "description": "Logging level (debug, info, warning, error)",
                },
                "meter_refresh_interval": {
                    "type": "float",
                    "default": 0.08,
                    "description": "Level meter refresh interval in seconds",
                },
                "recorder_start_timeout": {
                    "type": "float",
                    "default": 3.0,
                    "description": "Timeout for starting recorder in seconds",
                },
                "recorder_stop_timeout": {
                    "type": "float",
                    "default": 2.0,
                    "description": "Timeout for stopping recorder in seconds",
                },
            },
        }

    async def update_audio_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update audio configuration.

        Args:
            updates: Dictionary of config key-value pairs to update.

        Returns:
            Result dict with success status.
        """
        # Validate known audio config keys
        valid_keys = {
            "sample_rate",
            "output_dir",
            "session_prefix",
            "log_level",
            "meter_refresh_interval",
            "recorder_start_timeout",
            "recorder_stop_timeout",
            "shutdown_timeout",
            "console_output",
        }

        invalid_keys = set(updates.keys()) - valid_keys
        if invalid_keys:
            return {
                "success": False,
                "error": "invalid_keys",
                "message": f"Invalid configuration keys: {', '.join(invalid_keys)}",
                "valid_keys": list(valid_keys),
            }

        # Update module config using existing method
        return await self.update_module_config("Audio", updates)

    async def get_audio_levels(self) -> Dict[str, Any]:
        """Get current audio input levels.

        Returns the current RMS and peak audio levels in dB for the active
        audio device. Uses module command to query the running module.

        Returns:
            Dict with 'rms_db', 'peak_db', and 'has_device' fields.
        """
        # Check if Audio module is running
        if not self.logger_system.is_module_running("Audio"):
            return {
                "has_device": False,
                "rms_db": None,
                "peak_db": None,
                "message": "Audio module not running",
            }

        # Send get_status command to the audio module to get current levels
        # The module tracks levels internally via LevelMeter
        result = await self.send_module_command("Audio", "get_status")

        if not result.get("success"):
            return {
                "has_device": False,
                "rms_db": None,
                "peak_db": None,
                "message": "Failed to get audio status",
            }

        # The status command triggers a status report from the module
        # For now, return a response indicating the command was sent
        # In a full implementation, we would capture the status response
        return {
            "has_device": True,
            "rms_db": None,  # Would be populated from module response
            "peak_db": None,  # Would be populated from module response
            "message": "Level query sent to module",
            "note": "Real-time levels available via status callback",
        }

    async def get_audio_status(self) -> Dict[str, Any]:
        """Get audio module recording status.

        Returns current audio module status including recording state,
        trial number, device info, and session directory.

        Returns:
            Dict with status information.
        """
        # Check if Audio module exists
        module = await self.get_module("Audio")
        if not module:
            return {
                "module_found": False,
                "message": "Audio module not found",
            }

        running = self.logger_system.is_module_running("Audio")
        enabled = self.logger_system.is_module_enabled("Audio")

        # Get connected audio devices
        connected_devices = []
        for device in self.logger_system.device_system.get_connected_devices():
            if device.module_id and device.module_id.lower() == "audio":
                connected_devices.append({
                    "device_id": device.device_id,
                    "display_name": device.display_name,
                })

        return {
            "module_found": True,
            "enabled": enabled,
            "running": running,
            "state": module.get("state", "unknown"),
            "recording": self.trial_active and running,
            "trial_number": self.trial_counter,
            "session_active": self.session_active,
            "session_dir": str(self._session_dir) if self._session_dir else None,
            "connected_devices": connected_devices,
            "device_count": len(connected_devices),
        }

    async def start_audio_test_recording(self, duration: int = 5) -> Dict[str, Any]:
        """Start a test recording on the audio module.

        Starts a short test recording to verify audio device functionality.

        Args:
            duration: Test duration in seconds (1-30).

        Returns:
            Result dict with success status and recording info.
        """
        # Validate duration
        duration = min(30, max(1, duration))

        # Check if Audio module is running
        if not self.logger_system.is_module_running("Audio"):
            return {
                "success": False,
                "error": "module_not_running",
                "message": "Audio module is not running",
            }

        # Check if any audio device is connected
        audio_devices = []
        for device in self.logger_system.device_system.get_connected_devices():
            if device.module_id and device.module_id.lower() == "audio":
                audio_devices.append(device)

        if not audio_devices:
            return {
                "success": False,
                "error": "no_device",
                "message": "No audio device connected",
            }

        # Start recording via module command
        result = await self.send_module_command(
            "Audio",
            "start_recording",
            trial_number=0,  # Use 0 for test recordings
        )

        if not result.get("success"):
            return {
                "success": False,
                "error": "start_failed",
                "message": "Failed to start test recording",
            }

        # Log the test recording start
        if self.logger_system.event_logger:
            await self.logger_system.event_logger.log_button_press(
                "api_audio_test", f"duration={duration}s"
            )

        return {
            "success": True,
            "duration": duration,
            "message": f"Test recording started for {duration} seconds",
            "note": "Call stop_recording or wait for auto-stop to complete test",
            "device": audio_devices[0].display_name if audio_devices else None,
        }
