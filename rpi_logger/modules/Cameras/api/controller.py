"""
Cameras module API controller mixin.

Provides Cameras (USB webcam) specific methods that are
dynamically added to APIController.
"""

from typing import Any, Dict, Optional


class CamerasApiMixin:
    """
    Mixin class providing Cameras module API methods.

    These methods are dynamically bound to the APIController instance
    at startup, giving them access to self.logger_system, self.session_active, etc.
    """

    async def list_camera_devices(self) -> Dict[str, Any]:
        """List available USB cameras.

        Returns discovered USB camera devices from the device system.

        Returns:
            Dict with list of camera devices and their properties.
        """
        cameras = []
        for device in self.logger_system.device_system.get_all_devices():
            # Filter for camera devices (USB webcams)
            if device.module_id == "Cameras":
                cameras.append({
                    "device_id": device.device_id,
                    "display_name": device.display_name,
                    "connected": self.logger_system.device_system.is_device_connected(
                        device.device_id
                    ),
                    "connecting": self.logger_system.device_system.is_device_connecting(
                        device.device_id
                    ),
                    "port": device.port,
                    "interface": device.interface.value if device.interface else None,
                    "metadata": device.metadata,
                })

        return {
            "cameras": cameras,
            "count": len(cameras),
        }

    async def get_camera_config(self) -> Dict[str, Any]:
        """Get camera module configuration.

        Returns the current configuration for the Cameras module.

        Returns:
            Dict with camera configuration values.
        """
        config = await self.get_module_config("Cameras")
        if config is None:
            return {
                "success": False,
                "error": "module_not_found",
                "message": "Cameras module not found",
            }
        return config

    async def update_camera_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update camera module configuration.

        Args:
            updates: Dictionary of configuration updates.

        Returns:
            Result dict with success status.
        """
        return await self.update_module_config("Cameras", updates)

    async def get_camera_preview(self, camera_id: str) -> Optional[Dict[str, Any]]:
        """Get a preview frame from a camera as base64.

        Sends a command to the Cameras module to capture a preview frame
        and return it encoded as base64.

        Args:
            camera_id: The camera identifier.

        Returns:
            Dict with base64-encoded frame data and metadata,
            or None if camera not found.
        """
        import base64

        # Find the camera instance
        instances = await self.list_instances()
        camera_instance = None
        for instance in instances:
            if instance.get("module_id") == "Cameras":
                # Check if this instance matches the camera_id
                if camera_id in instance.get("device_id", ""):
                    camera_instance = instance
                    break
                if camera_id in instance.get("instance_id", ""):
                    camera_instance = instance
                    break

        if not camera_instance:
            return None

        # Send get_preview command to the module
        result = await self.send_module_command(
            "Cameras", "get_preview", camera_id=camera_id
        )

        if not result.get("success"):
            return {
                "error": result.get("message", "Failed to get preview"),
                "error_code": "PREVIEW_FAILED",
            }

        # The module should return frame data in its response
        frame_data = result.get("frame_data")
        if frame_data:
            return {
                "camera_id": camera_id,
                "frame": base64.b64encode(frame_data).decode("utf-8"),
                "format": result.get("format", "jpeg"),
                "width": result.get("width"),
                "height": result.get("height"),
                "timestamp": result.get("timestamp"),
            }

        return {
            "error": "No frame data available",
            "error_code": "NO_FRAME_DATA",
        }

    async def capture_camera_snapshot(
        self,
        camera_id: str,
        save_path: Optional[str] = None,
        format: str = "jpeg",
    ) -> Optional[Dict[str, Any]]:
        """Capture a single frame from a camera.

        Args:
            camera_id: The camera identifier.
            save_path: Optional path to save the image file.
            format: Image format (jpeg, png). Default: jpeg.

        Returns:
            Dict with snapshot result and path or base64 data,
            or None if camera not found.
        """
        import base64

        # Find the camera instance
        instances = await self.list_instances()
        camera_instance = None
        for instance in instances:
            if instance.get("module_id") == "Cameras":
                if camera_id in instance.get("device_id", ""):
                    camera_instance = instance
                    break
                if camera_id in instance.get("instance_id", ""):
                    camera_instance = instance
                    break

        if not camera_instance:
            return None

        # Send capture_snapshot command to the module
        result = await self.send_module_command(
            "Cameras",
            "capture_snapshot",
            camera_id=camera_id,
            save_path=save_path,
            format=format,
        )

        if not result.get("success"):
            return {
                "success": False,
                "error": result.get("message", "Failed to capture snapshot"),
                "error_code": "SNAPSHOT_FAILED",
            }

        response = {
            "success": True,
            "camera_id": camera_id,
            "format": format,
            "timestamp": result.get("timestamp"),
        }

        if save_path:
            response["path"] = save_path
        elif result.get("frame_data"):
            response["frame"] = base64.b64encode(result["frame_data"]).decode("utf-8")

        if result.get("width"):
            response["width"] = result["width"]
        if result.get("height"):
            response["height"] = result["height"]

        return response

    async def get_cameras_status(self) -> Dict[str, Any]:
        """Get recording status for all cameras.

        Returns:
            Dict with status information for all camera instances.
        """
        instances = await self.list_instances()
        camera_statuses = []

        for instance in instances:
            if instance.get("module_id") == "Cameras":
                # Query the module for detailed status
                result = await self.send_module_command(
                    "Cameras", "get_status", instance_id=instance.get("instance_id")
                )

                status = {
                    "instance_id": instance.get("instance_id"),
                    "device_id": instance.get("device_id"),
                    "state": instance.get("state"),
                    "recording": result.get("recording", False) if result.get("success") else False,
                    "resolution": result.get("resolution") if result.get("success") else None,
                    "fps": result.get("fps") if result.get("success") else None,
                    "frames_captured": result.get("frames_captured") if result.get("success") else None,
                }
                camera_statuses.append(status)

        return {
            "cameras": camera_statuses,
            "count": len(camera_statuses),
            "any_recording": any(c.get("recording") for c in camera_statuses),
        }

    async def set_camera_resolution(
        self, camera_id: str, width: int, height: int
    ) -> Optional[Dict[str, Any]]:
        """Set resolution for a camera.

        Args:
            camera_id: The camera identifier.
            width: Resolution width in pixels.
            height: Resolution height in pixels.

        Returns:
            Result dict with success status,
            or None if camera not found.
        """
        # Find the camera instance
        instances = await self.list_instances()
        camera_instance = None
        for instance in instances:
            if instance.get("module_id") == "Cameras":
                if camera_id in instance.get("device_id", ""):
                    camera_instance = instance
                    break
                if camera_id in instance.get("instance_id", ""):
                    camera_instance = instance
                    break

        if not camera_instance:
            return None

        # Send set_resolution command to the module
        result = await self.send_module_command(
            "Cameras",
            "set_resolution",
            camera_id=camera_id,
            width=width,
            height=height,
        )

        return {
            "success": result.get("success", False),
            "camera_id": camera_id,
            "resolution": f"{width}x{height}",
            "message": result.get("message", "Resolution update sent"),
        }

    async def set_camera_fps(
        self, camera_id: str, fps: float
    ) -> Optional[Dict[str, Any]]:
        """Set frame rate for a camera.

        Args:
            camera_id: The camera identifier.
            fps: Frame rate in frames per second.

        Returns:
            Result dict with success status,
            or None if camera not found.
        """
        # Find the camera instance
        instances = await self.list_instances()
        camera_instance = None
        for instance in instances:
            if instance.get("module_id") == "Cameras":
                if camera_id in instance.get("device_id", ""):
                    camera_instance = instance
                    break
                if camera_id in instance.get("instance_id", ""):
                    camera_instance = instance
                    break

        if not camera_instance:
            return None

        # Send set_fps command to the module
        result = await self.send_module_command(
            "Cameras",
            "set_fps",
            camera_id=camera_id,
            fps=fps,
        )

        return {
            "success": result.get("success", False),
            "camera_id": camera_id,
            "fps": fps,
            "message": result.get("message", "FPS update sent"),
        }
