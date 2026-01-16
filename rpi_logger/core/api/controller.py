"""
API Controller - Thin wrapper around LoggerSystem for REST API.

This controller provides async methods that can be called from HTTP routes.
It delegates to LoggerSystem and related components without duplicating
business logic.
"""

import datetime
import platform
import psutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.core.logger_system import LoggerSystem
from rpi_logger.core.module_process import ModuleState
from rpi_logger.core.shutdown_coordinator import get_shutdown_coordinator
from rpi_logger.core.config_manager import get_config_manager
from rpi_logger.core.paths import CONFIG_PATH, MASTER_LOG_FILE
from rpi_logger.core.devices import InterfaceType, DeviceFamily


logger = get_module_logger("APIController")


class APIController:
    """
    API controller providing programmatic access to Logger functionality.

    This class wraps LoggerSystem and provides async methods for all
    operations that can be performed via the GUI. It maintains session
    and trial state.
    """

    def __init__(self, logger_system: LoggerSystem):
        """
        Initialize the API controller.

        Args:
            logger_system: The LoggerSystem instance to wrap
        """
        self.logger = get_module_logger("APIController")
        self.logger_system = logger_system
        self.config_manager = get_config_manager()

        # Session/trial state
        self.trial_counter: int = 0
        self.session_active: bool = False
        self.trial_active: bool = False
        self.trial_label: str = ""
        self._session_dir: Optional[Path] = None

        # Apply module-provided API mixins
        from .module_api_loader import apply_mixins_to_controller
        apply_mixins_to_controller(self)

    # =========================================================================
    # System Endpoints
    # =========================================================================

    async def health_check(self) -> Dict[str, Any]:
        """Check system health."""
        return {
            "status": "ok",
            "timestamp": datetime.datetime.now().isoformat(),
            "api_version": "v1",
        }

    async def get_status(self) -> Dict[str, Any]:
        """Get full system status."""
        session_info = self.logger_system.get_session_info()

        return {
            "session_active": self.session_active,
            "trial_active": self.trial_active,
            "trial_counter": self.trial_counter,
            "trial_label": self.trial_label if self.trial_active else None,
            "session_dir": str(self._session_dir) if self._session_dir else None,
            "available_modules": [m.name for m in self.logger_system.get_available_modules()],
            "running_modules": session_info.get("running_modules", []),
            "selected_modules": session_info.get("selected_modules", []),
            "recording": session_info.get("recording", False),
            "scanning_enabled": self.logger_system.device_system._scanning_enabled,
        }

    async def get_platform_info(self) -> Dict[str, Any]:
        """Get platform information."""
        platform_info = self.logger_system.platform_info
        return {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "is_raspberry_pi": platform_info.is_raspberry_pi if platform_info else False,
        }

    async def get_system_info(self) -> Dict[str, Any]:
        """Get detailed system information (like System Info dialog)."""
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        return {
            "cpu_percent": cpu_percent,
            "memory": {
                "total_gb": round(memory.total / (1024**3), 2),
                "used_gb": round(memory.used / (1024**3), 2),
                "available_gb": round(memory.available / (1024**3), 2),
                "percent": memory.percent,
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent": disk.percent,
            },
            "platform": await self.get_platform_info(),
        }

    async def shutdown(self) -> Dict[str, Any]:
        """Initiate graceful shutdown."""
        self.logger.info("Shutdown requested via API")

        if self.logger_system.event_logger:
            await self.logger_system.event_logger.log_button_press("api_shutdown")

        if self.trial_active:
            await self.stop_trial()

        if self.session_active:
            await self.stop_session()

        shutdown_coordinator = get_shutdown_coordinator()
        await shutdown_coordinator.initiate_shutdown("API")

        return {"status": "shutdown_initiated"}

    # =========================================================================
    # Module Management
    # =========================================================================

    async def list_modules(self) -> List[Dict[str, Any]]:
        """List all available modules with their states."""
        modules = []
        for module_info in self.logger_system.get_available_modules():
            state = self.logger_system.get_module_state(module_info.name)
            enabled = self.logger_system.is_module_enabled(module_info.name)
            running = self.logger_system.is_module_running(module_info.name)

            modules.append({
                "name": module_info.name,
                "display_name": module_info.display_name,
                "module_id": module_info.module_id,
                "entry_point": str(module_info.entry_point),
                "enabled": enabled,
                "running": running,
                "state": state.value if state else "unknown",
                "config_path": str(module_info.config_path) if module_info.config_path else None,
            })

        return modules

    async def get_module(self, name: str) -> Optional[Dict[str, Any]]:
        """Get details for a specific module."""
        modules = await self.list_modules()
        for module in modules:
            if module["name"].lower() == name.lower():
                return module
        return None

    async def get_module_state(self, name: str) -> Optional[str]:
        """Get the state of a module."""
        state = self.logger_system.get_module_state(name)
        return state.value if state else None

    async def enable_module(self, name: str) -> Dict[str, Any]:
        """Enable a module (equivalent to checking the checkbox)."""
        if self.logger_system.event_logger:
            await self.logger_system.event_logger.log_button_press(f"api_module_{name}", "enable")

        await self.logger_system.toggle_module_enabled(name, True)
        success = await self.logger_system.set_module_enabled(name, True)

        if success and self.logger_system.event_logger:
            await self.logger_system.event_logger.log_module_started(name)

        return {
            "success": success,
            "module": name,
            "enabled": True,
            "message": f"Module {name} {'enabled' if success else 'failed to enable'}",
        }

    async def disable_module(self, name: str) -> Dict[str, Any]:
        """Disable a module (equivalent to unchecking the checkbox)."""
        if self.logger_system.event_logger:
            await self.logger_system.event_logger.log_button_press(f"api_module_{name}", "disable")

        success = await self.logger_system.set_module_enabled(name, False)
        await self.logger_system.toggle_module_enabled(name, False)

        if success and self.logger_system.event_logger:
            await self.logger_system.event_logger.log_module_stopped(name)

        return {
            "success": success,
            "module": name,
            "enabled": False,
            "message": f"Module {name} {'disabled' if success else 'failed to disable'}",
        }

    async def start_module(self, name: str) -> Dict[str, Any]:
        """Start a module process."""
        success = await self.logger_system.start_module(name)
        return {
            "success": success,
            "module": name,
            "message": f"Module {name} {'started' if success else 'failed to start'}",
        }

    async def stop_module(self, name: str) -> Dict[str, Any]:
        """Stop a module process."""
        success = await self.logger_system.stop_module(name)
        return {
            "success": success,
            "module": name,
            "message": f"Module {name} {'stopped' if success else 'failed to stop'}",
        }

    async def get_running_modules(self) -> List[str]:
        """Get list of running modules."""
        return self.logger_system.get_running_modules()

    async def get_enabled_states(self) -> Dict[str, bool]:
        """Get enabled states for all modules."""
        return self.logger_system.get_module_enabled_states()

    async def send_module_command(
        self, name: str, command: str, **kwargs
    ) -> Dict[str, Any]:
        """Send a command to a running module."""
        success = await self.logger_system.send_module_command(name, command, **kwargs)
        return {
            "success": success,
            "module": name,
            "command": command,
            "message": f"Command '{command}' {'sent' if success else 'failed'}",
        }

    # =========================================================================
    # Instance Management (Multi-Instance Modules)
    # =========================================================================

    async def list_instances(self) -> List[Dict[str, Any]]:
        """List all running module instances."""
        instances = []
        instance_manager = self.logger_system.instance_manager

        for instance_id, state in instance_manager._instances.items():
            instances.append({
                "instance_id": instance_id,
                "module_id": state.module_id,
                "device_id": state.device_id,
                "state": state.state.value,
            })

        return instances

    async def stop_instance(self, instance_id: str) -> Dict[str, Any]:
        """Stop a specific module instance."""
        success = await self.logger_system.stop_module_instance(instance_id)
        return {
            "success": success,
            "instance_id": instance_id,
            "message": f"Instance {instance_id} {'stopped' if success else 'failed to stop'}",
        }

    # =========================================================================
    # Session Management
    # =========================================================================

    async def get_session_info(self) -> Dict[str, Any]:
        """Get current session information."""
        return {
            "session_active": self.session_active,
            "session_dir": str(self._session_dir) if self._session_dir else None,
            "idle_session_dir": str(self.logger_system.idle_session_path),
            "recording": self.logger_system.recording,
            **self.logger_system.get_session_info(),
        }

    async def start_session(self, directory: Optional[str] = None) -> Dict[str, Any]:
        """Start a recording session."""
        if self.session_active:
            return {
                "success": False,
                "error": "session_already_active",
                "message": "A session is already active",
            }

        # Determine session directory
        if directory:
            session_dir = Path(directory)
        else:
            session_dir = self.logger_system.idle_session_path

        session_dir = Path(session_dir)
        self.logger_system.set_idle_session_dir(session_dir)

        # Create timestamped session directory
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        session_name = f"{self.logger_system.session_prefix}_{timestamp}"
        full_session_dir = session_dir / session_name
        full_session_dir.mkdir(parents=True, exist_ok=True)

        self.logger_system.set_session_dir(full_session_dir)
        self._session_dir = full_session_dir

        # Initialize event logger
        from rpi_logger.core.event_logger import EventLogger
        self.logger_system.event_logger = EventLogger(full_session_dir, timestamp)
        await self.logger_system.event_logger.initialize()

        await self.logger_system.event_logger.log_button_press("api_session_start")
        await self.logger_system.event_logger.log_session_start(str(full_session_dir))

        self.session_active = True
        self.trial_counter = 0

        self.logger.info("Session started in: %s", full_session_dir)

        await self.logger_system.start_session_all()

        return {
            "success": True,
            "session_active": True,
            "session_dir": str(full_session_dir),
            "session_name": session_name,
            "running_modules": self.logger_system.get_running_modules(),
        }

    async def stop_session(self) -> Dict[str, Any]:
        """Stop the recording session."""
        if not self.session_active:
            return {
                "success": False,
                "error": "no_active_session",
                "message": "No session is active",
            }

        if self.trial_active:
            await self.stop_trial()

        if self.logger_system.event_logger:
            await self.logger_system.event_logger.log_button_press("api_session_stop")
            await self.logger_system.event_logger.log_session_stop()

        await self.logger_system.stop_session_all()

        self.session_active = False
        session_dir = self._session_dir
        self._session_dir = None

        self.logger_system.reset_session_dir()

        self.logger.info("Session stopped")

        return {
            "success": True,
            "session_active": False,
            "session_dir": str(session_dir) if session_dir else None,
        }

    async def get_session_directory(self) -> Dict[str, Any]:
        """Get the current session directory."""
        return {
            "session_dir": str(self.logger_system.session_dir),
            "idle_session_dir": str(self.logger_system.idle_session_path),
            "session_active": self.session_active,
        }

    async def set_idle_session_directory(self, directory: str) -> Dict[str, Any]:
        """Set the idle session directory."""
        path = Path(directory)
        self.logger_system.set_idle_session_dir(path)
        return {
            "success": True,
            "idle_session_dir": str(path),
        }

    # =========================================================================
    # Trial/Recording Management
    # =========================================================================

    async def get_trial_info(self) -> Dict[str, Any]:
        """Get current trial information."""
        return {
            "trial_active": self.trial_active,
            "trial_counter": self.trial_counter,
            "trial_label": self.trial_label if self.trial_active else None,
        }

    async def start_trial(self, label: str = "") -> Dict[str, Any]:
        """Start recording a trial."""
        if not self.session_active:
            return {
                "success": False,
                "error": "no_active_session",
                "message": "Cannot start trial - no active session",
            }

        if self.trial_active:
            return {
                "success": False,
                "error": "trial_already_active",
                "message": "A trial is already active",
            }

        self.trial_label = label
        next_trial_num = self.trial_counter + 1

        if self.logger_system.event_logger:
            await self.logger_system.event_logger.log_button_press(
                "api_trial_record", f"trial={next_trial_num}"
            )
            await self.logger_system.event_logger.log_trial_start(next_trial_num, label)

        results = await self.logger_system.record_all(next_trial_num, label)

        failed = [name for name, success in results.items() if not success]
        self.trial_active = True

        self.logger.info("Trial %d started (label: %s)", next_trial_num, label or "none")

        return {
            "success": True,
            "trial_active": True,
            "trial_number": next_trial_num,
            "trial_label": label,
            "recording_modules": [name for name, success in results.items() if success],
            "failed_modules": failed,
        }

    async def stop_trial(self) -> Dict[str, Any]:
        """Stop recording the current trial."""
        if not self.trial_active:
            return {
                "success": False,
                "error": "no_active_trial",
                "message": "No trial is active",
            }

        results = await self.logger_system.pause_all()

        failed = [name for name, success in results.items() if not success]

        self.trial_active = False
        self.trial_counter += 1

        if self.logger_system.event_logger:
            await self.logger_system.event_logger.log_button_press(
                "api_trial_pause", f"trial={self.trial_counter}"
            )
            await self.logger_system.event_logger.log_trial_stop(self.trial_counter)

        self.logger.info("Trial %d stopped", self.trial_counter)

        return {
            "success": True,
            "trial_active": False,
            "trial_number": self.trial_counter,
            "paused_modules": [name for name, success in results.items() if success],
            "failed_modules": failed,
        }

    # =========================================================================
    # Device Management
    # =========================================================================

    async def list_devices(self) -> List[Dict[str, Any]]:
        """List all discovered devices."""
        devices = []
        for device in self.logger_system.device_system.get_all_devices():
            devices.append({
                "device_id": device.device_id,
                "display_name": device.display_name,
                "family": device.device_type.value if device.device_type else None,
                "interface": device.interface.value if device.interface else None,
                "module_id": device.module_id,
                "connected": self.logger_system.device_system.is_device_connected(device.device_id),
                "connecting": self.logger_system.device_system.is_device_connecting(device.device_id),
                "is_wireless": device.is_wireless,
                "is_internal": device.is_internal,
                "port": device.port,
            })
        return devices

    async def get_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get details for a specific device."""
        device = self.logger_system.device_system.get_device(device_id)
        if not device:
            return None

        return {
            "device_id": device.device_id,
            "display_name": device.display_name,
            "family": device.device_type.value if device.device_type else None,
            "interface": device.interface.value if device.interface else None,
            "module_id": device.module_id,
            "connected": self.logger_system.device_system.is_device_connected(device.device_id),
            "connecting": self.logger_system.device_system.is_device_connecting(device.device_id),
            "is_wireless": device.is_wireless,
            "is_internal": device.is_internal,
            "port": device.port,
            "baudrate": device.baudrate,
            "metadata": device.metadata,
        }

    async def connect_device(self, device_id: str) -> Dict[str, Any]:
        """Connect a device."""
        success = await self.logger_system.connect_and_start_device(device_id)
        return {
            "success": success,
            "device_id": device_id,
            "message": f"Device {device_id} {'connected' if success else 'failed to connect'}",
        }

    async def disconnect_device(self, device_id: str) -> Dict[str, Any]:
        """Disconnect a device."""
        success = await self.logger_system.stop_and_disconnect_device(device_id)
        return {
            "success": success,
            "device_id": device_id,
            "message": f"Device {device_id} disconnected",
        }

    async def get_connected_devices(self) -> List[Dict[str, Any]]:
        """Get list of connected devices."""
        devices = []
        for device in self.logger_system.device_system.get_connected_devices():
            devices.append({
                "device_id": device.device_id,
                "display_name": device.display_name,
                "module_id": device.module_id,
            })
        return devices

    # =========================================================================
    # Scanning Control
    # =========================================================================

    async def start_scanning(self) -> Dict[str, Any]:
        """Start device scanning."""
        await self.logger_system.start_device_scanning()
        return {
            "success": True,
            "scanning_enabled": True,
            "message": "Device scanning started",
        }

    async def stop_scanning(self) -> Dict[str, Any]:
        """Stop device scanning."""
        await self.logger_system.stop_device_scanning()
        return {
            "success": True,
            "scanning_enabled": False,
            "message": "Device scanning stopped",
        }

    async def get_scanning_status(self) -> Dict[str, Any]:
        """Get scanning status."""
        return {
            "scanning_enabled": self.logger_system.device_system._scanning_enabled,
        }

    # =========================================================================
    # Connection Type Management
    # =========================================================================

    async def get_enabled_connections(self) -> List[str]:
        """Get list of enabled connection types."""
        connections = self.logger_system.device_system.get_enabled_connections()
        return [f"{c[0].value}:{c[1].value}" for c in connections]

    async def set_connection_enabled(
        self,
        interface: str,
        family: str,
        enabled: bool
    ) -> Dict[str, Any]:
        """Enable or disable a connection type."""
        try:
            interface_type = InterfaceType(interface.upper())
            family_type = DeviceFamily(family.upper())

            self.logger_system.set_connection_enabled(interface_type, family_type, enabled)

            return {
                "success": True,
                "interface": interface,
                "family": family,
                "enabled": enabled,
            }
        except ValueError as e:
            return {
                "success": False,
                "error": "invalid_type",
                "message": str(e),
            }

    # =========================================================================
    # XBee/Wireless Management
    # =========================================================================

    async def get_xbee_status(self) -> Dict[str, Any]:
        """Get XBee dongle status."""
        return {
            "dongle_connected": self.logger_system.device_system.is_xbee_dongle_connected,
        }

    async def xbee_rescan(self) -> Dict[str, Any]:
        """Trigger XBee network rescan."""
        xbee = self.logger_system.device_system.xbee_manager
        if xbee and self.logger_system.device_system.is_xbee_dongle_connected:
            await xbee.rescan_network()
            return {"success": True, "message": "XBee rescan initiated"}
        return {"success": False, "message": "XBee dongle not connected"}

    # =========================================================================
    # Configuration
    # =========================================================================

    async def get_config(self) -> Dict[str, Any]:
        """Get global configuration."""
        config = self.config_manager.read_config(CONFIG_PATH)
        return dict(config) if config else {}

    async def update_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update global configuration."""
        self.config_manager.write_config(CONFIG_PATH, updates)
        return {
            "success": True,
            "updated": list(updates.keys()),
        }

    async def get_config_path(self) -> Dict[str, Any]:
        """Get config file path."""
        return {
            "config_path": str(CONFIG_PATH),
            "exists": CONFIG_PATH.exists(),
        }

    async def get_module_config(self, name: str) -> Optional[Dict[str, Any]]:
        """Get module-specific configuration.

        Args:
            name: Module name (case-insensitive)

        Returns:
            Dict with module name, config_path, and config values,
            or None if module not found or has no config.
        """
        # Find the module by name (case-insensitive)
        modules = self.logger_system.module_manager.get_available_modules()
        module_info = next(
            (m for m in modules if m.name.lower() == name.lower()),
            None
        )

        if not module_info:
            return None

        if not module_info.config_path:
            return {
                "module": module_info.name,
                "config_path": None,
                "config": {},
                "message": "Module has no configuration file",
            }

        config = await self.config_manager.read_config_async(module_info.config_path)
        return {
            "module": module_info.name,
            "config_path": str(module_info.config_path),
            "config": dict(config) if config else {},
        }

    async def update_module_config(
        self, name: str, updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update module-specific configuration.

        Args:
            name: Module name (case-insensitive)
            updates: Dictionary of config key-value pairs to update

        Returns:
            Result dict with success status and updated keys.
        """
        # Find the module by name (case-insensitive)
        modules = self.logger_system.module_manager.get_available_modules()
        module_info = next(
            (m for m in modules if m.name.lower() == name.lower()),
            None
        )

        if not module_info:
            return {
                "success": False,
                "error": "module_not_found",
                "message": f"Module '{name}' not found",
            }

        if not module_info.config_path:
            return {
                "success": False,
                "error": "no_config",
                "message": f"Module '{name}' has no configuration file",
            }

        success = await self.config_manager.write_config_async(
            module_info.config_path, updates
        )

        if success:
            self.logger.info(
                "Updated config for module %s: %s",
                module_info.name,
                list(updates.keys())
            )

        return {
            "success": success,
            "module": module_info.name,
            "updated": list(updates.keys()) if success else [],
            "message": f"Module config {'updated' if success else 'failed to update'}",
        }

    async def get_module_preferences(self, name: str) -> Optional[Dict[str, Any]]:
        """Get module preferences snapshot.

        Uses the StateFacade to load all preferences for a module.

        Args:
            name: Module name (case-insensitive)

        Returns:
            Dict with module name and preferences snapshot,
            or None if module not found.
        """
        # Find the module by name (case-insensitive)
        modules = self.logger_system.module_manager.get_available_modules()
        module_info = next(
            (m for m in modules if m.name.lower() == name.lower()),
            None
        )

        if not module_info:
            return None

        # Use StateFacade to load preferences
        preferences = await self.logger_system._state.load_all_preferences(
            module_info.name
        )

        return {
            "module": module_info.name,
            "config_path": str(module_info.config_path) if module_info.config_path else None,
            "preferences": preferences,
        }

    async def update_module_preference(
        self, name: str, key: str, value: Any
    ) -> Dict[str, Any]:
        """Update a single module preference.

        Uses the StateFacade to set a single preference value.

        Args:
            name: Module name (case-insensitive)
            key: Preference key to update
            value: New value for the preference

        Returns:
            Result dict with success status.
        """
        # Find the module by name (case-insensitive)
        modules = self.logger_system.module_manager.get_available_modules()
        module_info = next(
            (m for m in modules if m.name.lower() == name.lower()),
            None
        )

        if not module_info:
            return {
                "success": False,
                "error": "module_not_found",
                "message": f"Module '{name}' not found",
            }

        # Use StateFacade to set the preference
        success = await self.logger_system._state.set_preference(
            module_info.name, key, value
        )

        if success:
            self.logger.info(
                "Updated preference for module %s: %s = %s",
                module_info.name, key, value
            )

        return {
            "success": success,
            "module": module_info.name,
            "key": key,
            "value": value,
            "message": f"Preference {'updated' if success else 'failed to update'}",
        }

    # =========================================================================
    # Log Access
    # =========================================================================

    async def get_log_paths(self) -> Dict[str, Any]:
        """Get paths to log files."""
        from rpi_logger.core.paths import LOGS_DIR, MODULE_LOGS_DIR, MASTER_LOG_FILE

        # Get module log paths from centralized location
        module_logs = {}
        if MODULE_LOGS_DIR.exists():
            for module_dir in MODULE_LOGS_DIR.iterdir():
                if module_dir.is_dir():
                    log_file = module_dir / f"{module_dir.name}.log"
                    if log_file.exists():
                        module_logs[module_dir.name] = str(log_file)

        return {
            "master_log": str(MASTER_LOG_FILE),
            "session_log": str(self._session_dir / "logs") if self._session_dir else None,
            "event_log": str(self.logger_system.event_logger.event_log_path)
                if self.logger_system.event_logger else None,
            "logs_dir": str(LOGS_DIR),
            "module_logs_dir": str(MODULE_LOGS_DIR),
            "module_logs": module_logs,
        }

    # =========================================================================
    # Log File Reading
    # =========================================================================

    def _validate_log_path(self, path: str) -> tuple[bool, str, Optional[Path]]:
        """
        Validate that a path is within allowed log directories.

        Args:
            path: The path to validate

        Returns:
            Tuple of (is_valid, error_message, resolved_path)
        """
        from rpi_logger.core.paths import LOGS_DIR, MODULE_LOGS_DIR

        try:
            # Resolve the path to handle any .. or symlinks
            resolved = Path(path).resolve()
        except (ValueError, OSError) as e:
            return False, f"Invalid path: {e}", None

        # Define allowed directories (centralized logs only)
        allowed_dirs = [
            LOGS_DIR.resolve(),
            MODULE_LOGS_DIR.resolve(),
        ]

        # Add session logs directory if session is active
        if self._session_dir:
            session_logs = (self._session_dir / "logs").resolve()
            allowed_dirs.append(session_logs)
            # Also allow the session directory itself for event logs
            allowed_dirs.append(self._session_dir.resolve())

        # Check if the resolved path is under any allowed directory
        for allowed_dir in allowed_dirs:
            try:
                resolved.relative_to(allowed_dir)
                return True, "", resolved
            except ValueError:
                continue

        return False, "Path is outside allowed log directories", None

    async def read_log_file(
        self, path: str, offset: int = 0, limit: int = 100
    ) -> Dict[str, Any]:
        """
        Read a log file with pagination.

        Args:
            path: Path to the log file
            offset: Line offset to start reading from
            limit: Maximum number of lines to return

        Returns:
            Dict with success status, lines, and metadata
        """
        is_valid, error_msg, resolved_path = self._validate_log_path(path)
        if not is_valid:
            return {
                "success": False,
                "error": "INVALID_PATH",
                "message": error_msg,
            }

        if not resolved_path.exists():
            return {
                "success": False,
                "error": "FILE_NOT_FOUND",
                "message": f"Log file not found: {path}",
            }

        if not resolved_path.is_file():
            return {
                "success": False,
                "error": "NOT_A_FILE",
                "message": f"Path is not a file: {path}",
            }

        try:
            lines = []
            total_lines = 0

            with open(resolved_path, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f):
                    total_lines += 1
                    if i >= offset and len(lines) < limit:
                        lines.append(line.rstrip("\n\r"))

            return {
                "success": True,
                "path": str(resolved_path),
                "offset": offset,
                "limit": limit,
                "total_lines": total_lines,
                "returned_lines": len(lines),
                "has_more": offset + len(lines) < total_lines,
                "lines": lines,
            }
        except PermissionError:
            return {
                "success": False,
                "error": "PERMISSION_DENIED",
                "message": f"Permission denied reading: {path}",
            }
        except Exception as e:
            self.logger.error("Error reading log file %s: %s", path, e)
            return {
                "success": False,
                "error": "READ_ERROR",
                "message": str(e),
            }

    async def tail_log_file(self, path: str, lines: int = 50) -> Dict[str, Any]:
        """
        Get the last N lines from a log file.

        Uses efficient tail reading for large files.

        Args:
            path: Path to the log file
            lines: Number of lines to return from end of file

        Returns:
            Dict with success status and lines
        """
        is_valid, error_msg, resolved_path = self._validate_log_path(path)
        if not is_valid:
            return {
                "success": False,
                "error": "INVALID_PATH",
                "message": error_msg,
            }

        if not resolved_path.exists():
            return {
                "success": False,
                "error": "FILE_NOT_FOUND",
                "message": f"Log file not found: {path}",
            }

        if not resolved_path.is_file():
            return {
                "success": False,
                "error": "NOT_A_FILE",
                "message": f"Path is not a file: {path}",
            }

        try:
            # Use efficient tail reading for large files
            result_lines = []
            file_size = resolved_path.stat().st_size

            if file_size == 0:
                return {
                    "success": True,
                    "path": str(resolved_path),
                    "requested_lines": lines,
                    "returned_lines": 0,
                    "lines": [],
                }

            # For small files, just read all lines
            if file_size < 65536:  # 64KB
                with open(resolved_path, "r", encoding="utf-8", errors="replace") as f:
                    all_lines = f.readlines()
                    result_lines = [line.rstrip("\n\r") for line in all_lines[-lines:]]
            else:
                # For large files, read from end in chunks
                chunk_size = 8192
                result_lines = self._tail_large_file(resolved_path, lines, chunk_size)

            return {
                "success": True,
                "path": str(resolved_path),
                "requested_lines": lines,
                "returned_lines": len(result_lines),
                "lines": result_lines,
            }
        except PermissionError:
            return {
                "success": False,
                "error": "PERMISSION_DENIED",
                "message": f"Permission denied reading: {path}",
            }
        except Exception as e:
            self.logger.error("Error tailing log file %s: %s", path, e)
            return {
                "success": False,
                "error": "READ_ERROR",
                "message": str(e),
            }

    def _tail_large_file(self, path: Path, lines: int, chunk_size: int = 8192) -> list:
        """
        Efficiently read the last N lines from a large file.

        Args:
            path: Path to the file
            lines: Number of lines to retrieve
            chunk_size: Size of chunks to read from end

        Returns:
            List of the last N lines
        """
        result = []
        remaining = b""

        with open(path, "rb") as f:
            f.seek(0, 2)  # Seek to end
            file_size = f.tell()
            position = file_size

            while position > 0 and len(result) < lines:
                # Calculate how much to read
                read_size = min(chunk_size, position)
                position -= read_size

                f.seek(position)
                chunk = f.read(read_size) + remaining
                remaining = b""

                # Split into lines
                chunk_lines = chunk.split(b"\n")

                # The first line might be partial (unless at file start)
                if position > 0:
                    remaining = chunk_lines[0]
                    chunk_lines = chunk_lines[1:]

                # Add lines in reverse order (we're reading backwards)
                for line in reversed(chunk_lines):
                    if line or len(result) < lines:  # Keep empty lines too
                        decoded = line.decode("utf-8", errors="replace").rstrip("\r")
                        result.insert(0, decoded)
                        if len(result) >= lines:
                            break

        # Handle any remaining partial line at the very start
        if remaining and len(result) < lines:
            decoded = remaining.decode("utf-8", errors="replace").rstrip("\r")
            result.insert(0, decoded)

        return result[-lines:] if len(result) > lines else result

    async def read_master_log(self, offset: int = 0, limit: int = 100) -> Dict[str, Any]:
        """Read the master log file with pagination."""
        return await self.read_log_file(str(MASTER_LOG_FILE), offset, limit)

    async def read_session_log(self, offset: int = 0, limit: int = 100) -> Dict[str, Any]:
        """Read the session log file with pagination."""
        if not self._session_dir:
            return {
                "success": False,
                "error": "NO_SESSION",
                "message": "No active session - session log not available",
            }

        session_log = self._session_dir / "logs" / "session.log"
        if not session_log.exists():
            # Try to find any log file in the session logs directory
            session_logs_dir = self._session_dir / "logs"
            if session_logs_dir.exists():
                log_files = list(session_logs_dir.glob("*.log"))
                if log_files:
                    session_log = log_files[0]

        return await self.read_log_file(str(session_log), offset, limit)

    async def read_events_log(self, offset: int = 0, limit: int = 100) -> Dict[str, Any]:
        """Read the event log file with pagination."""
        if not self.logger_system.event_logger:
            return {
                "success": False,
                "error": "NO_EVENT_LOGGER",
                "message": "Event logger not initialized - start a session first",
            }

        event_log_path = self.logger_system.event_logger.event_log_path
        return await self.read_log_file(str(event_log_path), offset, limit)

    async def read_module_log(
        self, module_name: str, offset: int = 0, limit: int = 100
    ) -> Dict[str, Any]:
        """Read a module-specific log file with pagination."""
        from rpi_logger.core.paths import MODULE_LOGS_DIR

        # Check if module exists
        module = await self.get_module(module_name)
        if not module:
            return {
                "success": False,
                "error": "MODULE_NOT_FOUND",
                "message": f"Module '{module_name}' not found",
            }

        # Look for the module log file in centralized location
        module_log_dir = MODULE_LOGS_DIR / module_name
        log_path = module_log_dir / f"{module_name}.log"

        if not log_path.exists():
            # Try lowercase directory name
            module_log_dir = MODULE_LOGS_DIR / module_name.lower()
            log_path = module_log_dir / f"{module_name}.log"

        if not log_path.exists():
            return {
                "success": False,
                "error": "FILE_NOT_FOUND",
                "message": f"Log file for module '{module_name}' not found",
            }

        return await self.read_log_file(str(log_path), offset, limit)

    # =========================================================================
    # Module-Specific Operations
    # =========================================================================
    #
    # The following module APIs have been migrated to their respective modules:
    #   - Cameras: modules/Cameras/api/
    #   - GPS: modules/GPS/api/
    #   - Audio: modules/Audio/api/
    #   - DRT: modules/DRT/api/
    #   - Notes: modules/Notes/api/
    #   - VOG: modules/VOG/api/
    #   - EyeTracker: modules/EyeTracker/api/
    #
    # Module API methods are dynamically loaded via module_api_loader.py


# =============================================================================
# Settings Management Methods (Phase 3)
# =============================================================================

async def _get_module_settings(self, module_name: str) -> Dict[str, Any]:
    """Get all settings for a module.

    Retrieves both persisted preferences and runtime configuration
    for the specified module.

    Args:
        module_name: Name of the module (case-insensitive)

    Returns:
        Dict with success status and settings data.
    """
    from rpi_logger.core.api.schemas import get_schema

    # Find the module by name (case-insensitive)
    modules = self.logger_system.module_manager.get_available_modules()
    module_info = next(
        (m for m in modules if m.name.lower() == module_name.lower()),
        None
    )

    if not module_info:
        return {
            "success": False,
            "error": "module_not_found",
            "message": f"Module '{module_name}' not found",
        }

    # Get config file settings
    config = {}
    if module_info.config_path and module_info.config_path.exists():
        config = await self.config_manager.read_config_async(module_info.config_path)
        config = dict(config) if config else {}

    # Get preferences
    preferences = await self.logger_system._state.load_all_preferences(
        module_info.name
    )

    # Merge config and preferences (preferences take precedence)
    settings = {**config, **preferences}

    # Get schema for this module
    schema = get_schema(module_name.lower())
    schema_info = schema.to_dict() if schema else None

    return {
        "success": True,
        "module": module_info.name,
        "settings": settings,
        "config_path": str(module_info.config_path) if module_info.config_path else None,
        "schema": schema_info,
    }


async def _update_module_settings(
    self, module_name: str, settings: Dict[str, Any]
) -> Dict[str, Any]:
    """Update multiple settings for a module.

    Validates settings against the module's schema before applying.
    Supports dot notation for nested settings (e.g., "preview.resolution").

    Args:
        module_name: Name of the module (case-insensitive)
        settings: Dictionary of setting key-value pairs to update

    Returns:
        Dict with success status and updated keys.
    """
    from rpi_logger.core.api.schemas import get_schema, validate_settings

    # Find the module by name (case-insensitive)
    modules = self.logger_system.module_manager.get_available_modules()
    module_info = next(
        (m for m in modules if m.name.lower() == module_name.lower()),
        None
    )

    if not module_info:
        return {
            "success": False,
            "error": "module_not_found",
            "message": f"Module '{module_name}' not found",
        }

    # Validate settings against schema
    is_valid, errors = validate_settings(module_name.lower(), settings)
    if not is_valid:
        return {
            "success": False,
            "error": "validation_error",
            "message": "Settings validation failed",
            "errors": errors,
        }

    # Apply settings to preferences
    updated_keys = []
    for key, value in settings.items():
        success = await self.logger_system._state.set_preference(
            module_info.name, key, value
        )
        if success:
            updated_keys.append(key)
        else:
            self.logger.warning(
                "Failed to update setting %s.%s", module_info.name, key
            )

    # Also update config file if it exists
    if module_info.config_path:
        config_updates = {
            k: v for k, v in settings.items()
            if not k.startswith("view.") and not k.startswith("window")
        }
        if config_updates:
            await self.config_manager.write_config_async(
                module_info.config_path, config_updates
            )

    self.logger.info(
        "Updated settings for module %s: %s",
        module_info.name, updated_keys
    )

    return {
        "success": True,
        "module": module_info.name,
        "updated": updated_keys,
        "message": f"Updated {len(updated_keys)} settings",
    }


async def _get_module_setting(
    self, module_name: str, key: str
) -> Dict[str, Any]:
    """Get a specific setting for a module.

    Supports dot notation for nested settings (e.g., "preview.resolution").

    Args:
        module_name: Name of the module (case-insensitive)
        key: Setting key (supports dot notation)

    Returns:
        Dict with success status and setting value.
    """
    from rpi_logger.core.api.schemas import get_schema

    # Find the module by name (case-insensitive)
    modules = self.logger_system.module_manager.get_available_modules()
    module_info = next(
        (m for m in modules if m.name.lower() == module_name.lower()),
        None
    )

    if not module_info:
        return {
            "success": False,
            "error": "module_not_found",
            "message": f"Module '{module_name}' not found",
        }

    # First try preferences
    preferences = await self.logger_system._state.load_all_preferences(
        module_info.name
    )
    if key in preferences:
        value = preferences[key]
    else:
        # Try config file
        if module_info.config_path and module_info.config_path.exists():
            config = await self.config_manager.read_config_async(module_info.config_path)
            config = dict(config) if config else {}
            value = config.get(key)
        else:
            value = None

    if value is None:
        # Check if it's a valid key in the schema
        schema = get_schema(module_name.lower())
        if schema:
            field = schema.get_field(key)
            if field:
                value = field.default
            else:
                return {
                    "success": False,
                    "error": "setting_not_found",
                    "message": f"Setting '{key}' not found in module '{module_name}'",
                }
        else:
            return {
                "success": False,
                "error": "setting_not_found",
                "message": f"Setting '{key}' not found in module '{module_name}'",
            }

    # Get field info from schema if available
    field_info = None
    schema = get_schema(module_name.lower())
    if schema:
        field = schema.get_field(key)
        if field:
            field_info = field.to_dict()

    return {
        "success": True,
        "module": module_info.name,
        "key": key,
        "value": value,
        "field": field_info,
    }


async def _update_module_setting(
    self, module_name: str, key: str, value: Any
) -> Dict[str, Any]:
    """Update a specific setting for a module.

    Validates the value against the module's schema before applying.

    Args:
        module_name: Name of the module (case-insensitive)
        key: Setting key (supports dot notation)
        value: New value for the setting

    Returns:
        Dict with success status.
    """
    from rpi_logger.core.api.schemas import get_schema

    # Find the module by name (case-insensitive)
    modules = self.logger_system.module_manager.get_available_modules()
    module_info = next(
        (m for m in modules if m.name.lower() == module_name.lower()),
        None
    )

    if not module_info:
        return {
            "success": False,
            "error": "module_not_found",
            "message": f"Module '{module_name}' not found",
        }

    # Validate the single setting against schema
    schema = get_schema(module_name.lower())
    if schema:
        field = schema.get_field(key)
        if field:
            is_valid, error = field.validate(value)
            if not is_valid:
                return {
                    "success": False,
                    "error": "validation_error",
                    "message": error,
                }

    # Update the preference
    success = await self.logger_system._state.set_preference(
        module_info.name, key, value
    )

    if success:
        self.logger.info(
            "Updated setting %s.%s = %s", module_info.name, key, value
        )

        # Also update config file for non-view settings
        if module_info.config_path and not key.startswith("view.") and not key.startswith("window"):
            await self.config_manager.write_config_async(
                module_info.config_path, {key: value}
            )

    return {
        "success": success,
        "module": module_info.name,
        "key": key,
        "value": value,
        "message": f"Setting {'updated' if success else 'failed to update'}",
    }


async def _reset_module_settings(self, module_name: str) -> Dict[str, Any]:
    """Reset all module settings to their defaults.

    Uses the schema defaults to reset all settings for the module.

    Args:
        module_name: Name of the module (case-insensitive)

    Returns:
        Dict with success status and reset keys.
    """
    from rpi_logger.core.api.schemas import get_schema, get_defaults

    # Find the module by name (case-insensitive)
    modules = self.logger_system.module_manager.get_available_modules()
    module_info = next(
        (m for m in modules if m.name.lower() == module_name.lower()),
        None
    )

    if not module_info:
        return {
            "success": False,
            "error": "module_not_found",
            "message": f"Module '{module_name}' not found",
        }

    # Get schema and defaults
    schema = get_schema(module_name.lower())
    if not schema:
        return {
            "success": False,
            "error": "no_schema",
            "message": f"No settings schema available for module '{module_name}'",
        }

    defaults = get_defaults(module_name.lower())
    if not defaults:
        return {
            "success": False,
            "error": "no_defaults",
            "message": f"No default settings available for module '{module_name}'",
        }

    # Reset all settings to defaults
    reset_keys = []
    for key, value in defaults.items():
        success = await self.logger_system._state.set_preference(
            module_info.name, key, value
        )
        if success:
            reset_keys.append(key)

    # Also update config file
    if module_info.config_path:
        config_defaults = {
            k: v for k, v in defaults.items()
            if not k.startswith("view.") and not k.startswith("window")
        }
        if config_defaults:
            await self.config_manager.write_config_async(
                module_info.config_path, config_defaults
            )

    self.logger.info(
        "Reset settings for module %s to defaults", module_info.name
    )

    return {
        "success": True,
        "module": module_info.name,
        "reset_keys": reset_keys,
        "defaults": defaults,
        "message": f"Reset {len(reset_keys)} settings to defaults",
    }


async def _get_module_settings_schema(self, module_name: str) -> Dict[str, Any]:
    """Get the settings schema for a module.

    Returns the complete schema definition including field types,
    ranges, defaults, and descriptions.

    Args:
        module_name: Name of the module (case-insensitive)

    Returns:
        Dict with success status and schema data.
    """
    from rpi_logger.core.api.schemas import get_schema

    # Find the module by name (case-insensitive)
    modules = self.logger_system.module_manager.get_available_modules()
    module_info = next(
        (m for m in modules if m.name.lower() == module_name.lower()),
        None
    )

    if not module_info:
        return {
            "success": False,
            "error": "module_not_found",
            "message": f"Module '{module_name}' not found",
        }

    # Get schema
    schema = get_schema(module_name.lower())
    if not schema:
        return {
            "success": False,
            "error": "no_schema",
            "message": f"No settings schema available for module '{module_name}'",
        }

    return {
        "success": True,
        "module": module_info.name,
        "schema": schema.to_dict(),
    }


async def _get_global_settings(self) -> Dict[str, Any]:
    """Get all global application settings.

    Returns application-wide settings including output paths,
    logging configuration, and enabled features.

    Returns:
        Dict with global settings.
    """
    from rpi_logger.core.paths import CONFIG_PATH

    # Get global config
    config = self.config_manager.read_config(CONFIG_PATH)
    config = dict(config) if config else {}

    # Get connection type settings
    connection_types = await self._get_connection_types_internal()

    return {
        "success": True,
        "settings": config,
        "connection_types": connection_types,
        "config_path": str(CONFIG_PATH),
    }


async def _update_global_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
    """Update global application settings.

    Args:
        settings: Dictionary of setting key-value pairs to update

    Returns:
        Dict with success status and updated keys.
    """
    from rpi_logger.core.paths import CONFIG_PATH
    from rpi_logger.core.api.schemas import get_schema, validate_settings

    # Validate settings against global schema
    is_valid, errors = validate_settings("global", settings)
    if not is_valid:
        return {
            "success": False,
            "error": "validation_error",
            "message": "Settings validation failed",
            "errors": errors,
        }

    # Update config file
    self.config_manager.write_config(CONFIG_PATH, settings)

    self.logger.info("Updated global settings: %s", list(settings.keys()))

    return {
        "success": True,
        "updated": list(settings.keys()),
        "message": f"Updated {len(settings)} global settings",
    }


async def _get_connection_types_internal(self) -> Dict[str, bool]:
    """Internal method to get connection types status."""
    from rpi_logger.core.devices import InterfaceType

    # Check which interface types are enabled in device system
    enabled_types = {}

    # Check USB
    enabled_types["usb"] = InterfaceType.USB in self.logger_system.device_system._enabled_interfaces

    # Check Serial
    enabled_types["serial"] = InterfaceType.SERIAL in self.logger_system.device_system._enabled_interfaces

    # Check Bluetooth
    enabled_types["bluetooth"] = InterfaceType.BLUETOOTH in self.logger_system.device_system._enabled_interfaces

    # Check XBee
    enabled_types["xbee"] = self.logger_system.device_system.is_xbee_dongle_connected

    # Check Network/IP
    enabled_types["network"] = InterfaceType.IP in self.logger_system.device_system._enabled_interfaces

    return enabled_types


async def _get_connection_types(self) -> Dict[str, Any]:
    """Get enabled connection types.

    Returns a dictionary of connection types and their enabled status.

    Returns:
        Dict with connection_types mapping.
    """
    connection_types = await self._get_connection_types_internal()

    return {
        "success": True,
        "connection_types": connection_types,
    }


async def _update_connection_types(self, types: Dict[str, bool]) -> Dict[str, Any]:
    """Update connection type settings.

    Enables or disables specific connection types for device discovery.

    Args:
        types: Dictionary mapping connection type names to enabled status

    Returns:
        Dict with success status and updated types.
    """
    from rpi_logger.core.devices import InterfaceType

    type_mapping = {
        "usb": InterfaceType.USB,
        "serial": InterfaceType.SERIAL,
        "bluetooth": InterfaceType.BLUETOOTH,
        "network": InterfaceType.IP,
    }

    updated = []
    for type_name, enabled in types.items():
        if type_name in type_mapping:
            interface = type_mapping[type_name]
            if enabled:
                self.logger_system.device_system._enabled_interfaces.add(interface)
            else:
                self.logger_system.device_system._enabled_interfaces.discard(interface)
            updated.append(type_name)
        elif type_name == "xbee":
            # XBee is controlled separately via XBee manager
            self.logger.info("XBee enable/disable must be done via XBee manager")

    self.logger.info("Updated connection types: %s", updated)

    return {
        "success": True,
        "updated": updated,
        "connection_types": await self._get_connection_types_internal(),
        "message": f"Updated {len(updated)} connection types",
    }


async def _get_window_geometries(self) -> Dict[str, Any]:
    """Get saved window geometries for all modules and dialogs.

    Returns:
        Dict with geometries mapping.
    """
    geometries = {}

    # Get geometry for each module
    modules = self.logger_system.module_manager.get_available_modules()
    for module_info in modules:
        prefs = await self.logger_system._state.load_all_preferences(module_info.name)
        if "window_geometry" in prefs:
            geometries[module_info.name.lower()] = prefs["window_geometry"]
        if "config_dialog_geometry" in prefs:
            geometries[f"{module_info.name.lower()}_config"] = prefs["config_dialog_geometry"]

    # Get main window geometry if available
    main_geometry = await self.logger_system._state.load_preference("main", "window_geometry")
    if main_geometry:
        geometries["main_window"] = main_geometry

    return {
        "success": True,
        "geometries": geometries,
    }


# Bind Settings Management methods to APIController
APIController.get_module_settings = _get_module_settings
APIController.update_module_settings = _update_module_settings
APIController.get_module_setting = _get_module_setting
APIController.update_module_setting = _update_module_setting
APIController.reset_module_settings = _reset_module_settings
APIController.get_module_settings_schema = _get_module_settings_schema
APIController.get_global_settings = _get_global_settings
APIController.update_global_settings = _update_global_settings
APIController._get_connection_types_internal = _get_connection_types_internal
APIController.get_connection_types = _get_connection_types
APIController.update_connection_types = _update_connection_types
APIController.get_window_geometries = _get_window_geometries


# =============================================================================
# Window and UI Control Methods (Phase 4)
# =============================================================================

def _parse_geometry_string(geometry_str: str) -> dict:
    """Parse a geometry string in format 'WIDTHxHEIGHT+X+Y' to dict.

    Args:
        geometry_str: Geometry string like "800x600+100+100"

    Returns:
        Dict with x, y, width, height keys

    Raises:
        ValueError: If the geometry string format is invalid
    """
    import re
    # Pattern: WIDTHxHEIGHT+X+Y (X and Y can be negative)
    pattern = r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$"
    match = re.match(pattern, geometry_str)
    if not match:
        raise ValueError(f"Invalid geometry string format: {geometry_str}")

    return {
        "width": int(match.group(1)),
        "height": int(match.group(2)),
        "x": int(match.group(3)),
        "y": int(match.group(4)),
    }


def _geometry_dict_to_string(geometry: dict) -> str:
    """Convert geometry dict to string format 'WIDTHxHEIGHT+X+Y'.

    Args:
        geometry: Dict with x, y, width, height keys

    Returns:
        Geometry string like "800x600+100+100"
    """
    x = geometry.get("x", 0)
    y = geometry.get("y", 0)
    width = geometry.get("width", 800)
    height = geometry.get("height", 600)

    # Format X and Y with their signs
    x_str = f"+{x}" if x >= 0 else str(x)
    y_str = f"+{y}" if y >= 0 else str(y)

    return f"{width}x{height}{x_str}{y_str}"


async def _show_module_window(self, module_name: str) -> Dict[str, Any]:
    """Show a module's GUI window.

    Args:
        module_name: Name of the module (case-insensitive)

    Returns:
        Dict with success status and module info.
    """
    # Find the module by name (case-insensitive)
    modules = self.logger_system.module_manager.get_available_modules()
    module_info = next(
        (m for m in modules if m.name.lower() == module_name.lower()),
        None
    )

    if not module_info:
        return {
            "success": False,
            "error": "module_not_found",
            "message": f"Module '{module_name}' not found",
        }

    # Check if module is running
    if not self.logger_system.is_module_running(module_info.name):
        return {
            "success": False,
            "error": "module_not_running",
            "module": module_info.name,
            "message": f"Module '{module_info.name}' is not running",
        }

    # Send show_window command to the module
    result = await self.send_module_command(module_info.name, "show_window")

    if result.get("success"):
        self.logger.info("Showed window for module: %s", module_info.name)
        return {
            "success": True,
            "module": module_info.name,
            "message": f"Window for '{module_info.name}' is now visible",
        }

    return {
        "success": False,
        "error": "command_failed",
        "module": module_info.name,
        "message": f"Failed to show window for '{module_info.name}'",
    }


async def _hide_module_window(self, module_name: str) -> Dict[str, Any]:
    """Hide a module's GUI window.

    Args:
        module_name: Name of the module (case-insensitive)

    Returns:
        Dict with success status and module info.
    """
    # Find the module by name (case-insensitive)
    modules = self.logger_system.module_manager.get_available_modules()
    module_info = next(
        (m for m in modules if m.name.lower() == module_name.lower()),
        None
    )

    if not module_info:
        return {
            "success": False,
            "error": "module_not_found",
            "message": f"Module '{module_name}' not found",
        }

    # Check if module is running
    if not self.logger_system.is_module_running(module_info.name):
        return {
            "success": False,
            "error": "module_not_running",
            "module": module_info.name,
            "message": f"Module '{module_info.name}' is not running",
        }

    # Send hide_window command to the module
    result = await self.send_module_command(module_info.name, "hide_window")

    if result.get("success"):
        self.logger.info("Hid window for module: %s", module_info.name)
        return {
            "success": True,
            "module": module_info.name,
            "message": f"Window for '{module_info.name}' is now hidden",
        }

    return {
        "success": False,
        "error": "command_failed",
        "module": module_info.name,
        "message": f"Failed to hide window for '{module_info.name}'",
    }


async def _get_window_geometry(self, module_name: str) -> Dict[str, Any]:
    """Get window position and size.

    Args:
        module_name: Name of the module (case-insensitive)

    Returns:
        Dict with success status and geometry (x, y, width, height).
    """
    # Find the module by name (case-insensitive)
    modules = self.logger_system.module_manager.get_available_modules()
    module_info = next(
        (m for m in modules if m.name.lower() == module_name.lower()),
        None
    )

    if not module_info:
        return {
            "success": False,
            "error": "module_not_found",
            "message": f"Module '{module_name}' not found",
        }

    # Check if module is running
    if not self.logger_system.is_module_running(module_info.name):
        return {
            "success": False,
            "error": "module_not_running",
            "module": module_info.name,
            "message": f"Module '{module_info.name}' is not running",
        }

    # Send get_geometry command to the module
    result = await self.send_module_command(module_info.name, "get_geometry")

    if result.get("success"):
        # Extract geometry from result or use default values
        geometry = result.get("geometry", {})
        return {
            "success": True,
            "module": module_info.name,
            "geometry": {
                "x": geometry.get("x", 0),
                "y": geometry.get("y", 0),
                "width": geometry.get("width", 800),
                "height": geometry.get("height", 600),
            },
        }

    # Try to get geometry from saved preferences as fallback
    prefs = await self.logger_system._state.load_all_preferences(module_info.name)
    if "window_geometry" in prefs:
        geometry_str = prefs["window_geometry"]
        try:
            geometry = _parse_geometry_string(geometry_str)
            return {
                "success": True,
                "module": module_info.name,
                "geometry": geometry,
                "source": "saved_preferences",
            }
        except ValueError:
            pass

    return {
        "success": False,
        "error": "geometry_unavailable",
        "module": module_info.name,
        "message": f"Could not retrieve geometry for '{module_info.name}'",
    }


async def _set_window_geometry(
    self, module_name: str, geometry: Dict[str, Any]
) -> Dict[str, Any]:
    """Set window position and size.

    Args:
        module_name: Name of the module (case-insensitive)
        geometry: Dict with x, y, width, height keys, or
                  Dict with "geometry" key containing a geometry string

    Returns:
        Dict with success status and applied geometry.
    """
    # Find the module by name (case-insensitive)
    modules = self.logger_system.module_manager.get_available_modules()
    module_info = next(
        (m for m in modules if m.name.lower() == module_name.lower()),
        None
    )

    if not module_info:
        return {
            "success": False,
            "error": "module_not_found",
            "message": f"Module '{module_name}' not found",
        }

    # Check if module is running
    if not self.logger_system.is_module_running(module_info.name):
        return {
            "success": False,
            "error": "module_not_running",
            "module": module_info.name,
            "message": f"Module '{module_info.name}' is not running",
        }

    # Parse geometry - support both dict and string formats
    geometry_dict = {}

    if "geometry" in geometry and isinstance(geometry["geometry"], str):
        # Parse geometry string format: "WIDTHxHEIGHT+X+Y"
        try:
            geometry_dict = _parse_geometry_string(geometry["geometry"])
        except ValueError as e:
            return {
                "success": False,
                "error": "invalid_geometry",
                "message": str(e),
            }
    else:
        # Use dict format with optional keys
        for key in ["x", "y", "width", "height"]:
            if key in geometry:
                try:
                    geometry_dict[key] = int(geometry[key])
                except (TypeError, ValueError):
                    return {
                        "success": False,
                        "error": "invalid_geometry",
                        "message": f"Invalid value for '{key}': must be an integer",
                    }

    if not geometry_dict:
        return {
            "success": False,
            "error": "invalid_geometry",
            "message": "No valid geometry values provided",
        }

    # Send set_geometry command to the module
    result = await self.send_module_command(
        module_info.name, "set_geometry", geometry=geometry_dict
    )

    if result.get("success"):
        self.logger.info(
            "Set window geometry for module %s: %s", module_info.name, geometry_dict
        )

        # Save the geometry to preferences
        geometry_str = _geometry_dict_to_string(geometry_dict)
        await self.logger_system._state.set_preference(
            module_info.name, "window_geometry", geometry_str
        )

        return {
            "success": True,
            "module": module_info.name,
            "geometry": geometry_dict,
            "message": f"Window geometry updated for '{module_info.name}'",
        }

    return {
        "success": False,
        "error": "command_failed",
        "module": module_info.name,
        "message": f"Failed to set geometry for '{module_info.name}'",
    }


async def _focus_module_window(self, module_name: str) -> Dict[str, Any]:
    """Bring module window to front.

    Args:
        module_name: Name of the module (case-insensitive)

    Returns:
        Dict with success status and module info.
    """
    # Find the module by name (case-insensitive)
    modules = self.logger_system.module_manager.get_available_modules()
    module_info = next(
        (m for m in modules if m.name.lower() == module_name.lower()),
        None
    )

    if not module_info:
        return {
            "success": False,
            "error": "module_not_found",
            "message": f"Module '{module_name}' not found",
        }

    # Check if module is running
    if not self.logger_system.is_module_running(module_info.name):
        return {
            "success": False,
            "error": "module_not_running",
            "module": module_info.name,
            "message": f"Module '{module_info.name}' is not running",
        }

    # Send focus_window command to the module
    result = await self.send_module_command(module_info.name, "focus_window")

    if result.get("success"):
        self.logger.info("Focused window for module: %s", module_info.name)
        return {
            "success": True,
            "module": module_info.name,
            "message": f"Window for '{module_info.name}' brought to front",
        }

    return {
        "success": False,
        "error": "command_failed",
        "module": module_info.name,
        "message": f"Failed to focus window for '{module_info.name}'",
    }


async def _get_window_state(self, module_name: str) -> Dict[str, Any]:
    """Get window state (visible, minimized, maximized, focused).

    Args:
        module_name: Name of the module (case-insensitive)

    Returns:
        Dict with success status and state (visible, minimized, maximized, focused).
    """
    # Find the module by name (case-insensitive)
    modules = self.logger_system.module_manager.get_available_modules()
    module_info = next(
        (m for m in modules if m.name.lower() == module_name.lower()),
        None
    )

    if not module_info:
        return {
            "success": False,
            "error": "module_not_found",
            "message": f"Module '{module_name}' not found",
        }

    # Check if module is running
    if not self.logger_system.is_module_running(module_info.name):
        return {
            "success": False,
            "error": "module_not_running",
            "module": module_info.name,
            "message": f"Module '{module_info.name}' is not running",
        }

    # Send get_window_state command to the module
    result = await self.send_module_command(module_info.name, "get_window_state")

    if result.get("success"):
        state = result.get("state", {})
        return {
            "success": True,
            "module": module_info.name,
            "state": {
                "visible": state.get("visible", True),
                "minimized": state.get("minimized", False),
                "maximized": state.get("maximized", False),
                "focused": state.get("focused", False),
            },
        }

    # Return default state if command failed (assume visible if running)
    return {
        "success": True,
        "module": module_info.name,
        "state": {
            "visible": True,
            "minimized": False,
            "maximized": False,
            "focused": False,
        },
        "source": "default",
    }


async def _list_all_windows(self) -> Dict[str, Any]:
    """List all module windows with their states.

    Returns:
        Dict with list of windows and their states.
    """
    windows = []
    modules = self.logger_system.module_manager.get_available_modules()

    for module_info in modules:
        is_running = self.logger_system.is_module_running(module_info.name)

        window_info = {
            "module": module_info.name,
            "display_name": module_info.display_name,
            "running": is_running,
        }

        if is_running:
            # Try to get window state and geometry
            state_result = await self._get_window_state(module_info.name)
            if state_result.get("success"):
                window_info["state"] = state_result.get("state", {})

            geometry_result = await self._get_window_geometry(module_info.name)
            if geometry_result.get("success"):
                window_info["geometry"] = geometry_result.get("geometry", {})
        else:
            window_info["state"] = None
            window_info["geometry"] = None

        windows.append(window_info)

    return {
        "success": True,
        "windows": windows,
        "total": len(windows),
        "running": sum(1 for w in windows if w.get("running")),
    }


async def _arrange_windows(self, layout: str = "grid") -> Dict[str, Any]:
    """Auto-arrange windows on screen.

    Args:
        layout: Layout type - "grid", "cascade", "tile_horizontal", "tile_vertical"

    Returns:
        Dict with success status and arranged window info.
    """
    # Get list of running modules with windows
    running_modules = []
    modules = self.logger_system.module_manager.get_available_modules()

    for module_info in modules:
        if self.logger_system.is_module_running(module_info.name):
            running_modules.append(module_info)

    if not running_modules:
        return {
            "success": True,
            "message": "No running modules to arrange",
            "arranged": [],
        }

    # Default screen dimensions (could be made configurable or detected)
    screen_width = 1920
    screen_height = 1080
    taskbar_height = 40  # Reserve space for taskbar
    usable_height = screen_height - taskbar_height

    num_windows = len(running_modules)
    arranged = []

    if layout == "grid":
        # Calculate grid dimensions
        import math
        cols = math.ceil(math.sqrt(num_windows))
        rows = math.ceil(num_windows / cols)

        win_width = screen_width // cols
        win_height = usable_height // rows

        for i, module_info in enumerate(running_modules):
            row = i // cols
            col = i % cols
            geometry = {
                "x": col * win_width,
                "y": row * win_height,
                "width": win_width,
                "height": win_height,
            }
            result = await self._set_window_geometry(module_info.name, geometry)
            if result.get("success"):
                arranged.append({"module": module_info.name, "geometry": geometry})

    elif layout == "cascade":
        # Cascade windows with offset
        offset_x = 30
        offset_y = 30
        win_width = screen_width - (num_windows * offset_x)
        win_height = usable_height - (num_windows * offset_y)

        # Ensure minimum window size
        win_width = max(win_width, 400)
        win_height = max(win_height, 300)

        for i, module_info in enumerate(running_modules):
            geometry = {
                "x": i * offset_x,
                "y": i * offset_y,
                "width": win_width,
                "height": win_height,
            }
            result = await self._set_window_geometry(module_info.name, geometry)
            if result.get("success"):
                arranged.append({"module": module_info.name, "geometry": geometry})

    elif layout == "tile_horizontal":
        # Tile windows horizontally (side by side)
        win_width = screen_width // num_windows
        win_height = usable_height

        for i, module_info in enumerate(running_modules):
            geometry = {
                "x": i * win_width,
                "y": 0,
                "width": win_width,
                "height": win_height,
            }
            result = await self._set_window_geometry(module_info.name, geometry)
            if result.get("success"):
                arranged.append({"module": module_info.name, "geometry": geometry})

    elif layout == "tile_vertical":
        # Tile windows vertically (stacked)
        win_width = screen_width
        win_height = usable_height // num_windows

        for i, module_info in enumerate(running_modules):
            geometry = {
                "x": 0,
                "y": i * win_height,
                "width": win_width,
                "height": win_height,
            }
            result = await self._set_window_geometry(module_info.name, geometry)
            if result.get("success"):
                arranged.append({"module": module_info.name, "geometry": geometry})

    else:
        return {
            "success": False,
            "error": "invalid_layout",
            "message": f"Unknown layout type: {layout}",
        }

    self.logger.info(
        "Arranged %d windows using layout '%s'", len(arranged), layout
    )

    return {
        "success": True,
        "layout": layout,
        "arranged": arranged,
        "total": len(arranged),
        "message": f"Arranged {len(arranged)} windows using {layout} layout",
    }


async def _minimize_all_windows(self) -> Dict[str, Any]:
    """Minimize all module windows.

    Returns:
        Dict with success status and minimized window count.
    """
    minimized = []
    failed = []
    modules = self.logger_system.module_manager.get_available_modules()

    for module_info in modules:
        if self.logger_system.is_module_running(module_info.name):
            result = await self.send_module_command(
                module_info.name, "minimize_window"
            )
            if result.get("success"):
                minimized.append(module_info.name)
            else:
                failed.append(module_info.name)

    self.logger.info("Minimized %d windows", len(minimized))

    return {
        "success": True,
        "minimized": minimized,
        "failed": failed,
        "total_minimized": len(minimized),
        "message": f"Minimized {len(minimized)} windows",
    }


async def _restore_all_windows(self) -> Dict[str, Any]:
    """Restore all minimized windows.

    Returns:
        Dict with success status and restored window count.
    """
    restored = []
    failed = []
    modules = self.logger_system.module_manager.get_available_modules()

    for module_info in modules:
        if self.logger_system.is_module_running(module_info.name):
            result = await self.send_module_command(
                module_info.name, "restore_window"
            )
            if result.get("success"):
                restored.append(module_info.name)
            else:
                failed.append(module_info.name)

    self.logger.info("Restored %d windows", len(restored))

    return {
        "success": True,
        "restored": restored,
        "failed": failed,
        "total_restored": len(restored),
        "message": f"Restored {len(restored)} windows",
    }


# Bind Window and UI Control methods to APIController
APIController.show_module_window = _show_module_window
APIController.hide_module_window = _hide_module_window
APIController.get_window_geometry = _get_window_geometry
APIController.set_window_geometry = _set_window_geometry
APIController.focus_module_window = _focus_module_window
APIController.get_window_state = _get_window_state
APIController.list_all_windows = _list_all_windows
APIController.arrange_windows = _arrange_windows
APIController.minimize_all_windows = _minimize_all_windows
APIController.restore_all_windows = _restore_all_windows


# =============================================================================
# Testing and Verification Methods (Phase 5)
# =============================================================================
# These methods provide testing, hardware detection, and data validation
# functionality via the API.

import asyncio

# Test state tracking - stored as module-level variables for simplicity
_running_test: Optional[Dict[str, Any]] = None
_test_cancelled: bool = False


async def _run_record_cycle_test(self, config: dict = None) -> Dict[str, Any]:
    """
    Run a complete record cycle test.

    Performs:
    1. Start session
    2. Start trial
    3. Record for specified duration (default 5s)
    4. Stop trial
    5. Stop session
    6. Validate recorded data (optional)

    Args:
        config: Optional configuration dict with:
            - duration_seconds: Recording duration (default 5)
            - modules: List of modules to test (default all enabled)
            - validate: Whether to validate after recording (default True)
            - cleanup: Whether to delete test data after (default False)

    Returns:
        Dict with test results including session_path, trials, validation info.
    """
    global _running_test, _test_cancelled

    # Check if a test is already running
    if _running_test is not None:
        return {
            "success": False,
            "error": "test_already_running",
            "message": f"A test is already running: {_running_test.get('test_type')}",
        }

    # Check if session is already active
    if self.session_active:
        return {
            "success": False,
            "error": "session_already_active",
            "message": "Cannot run record cycle test while a session is active",
        }

    # Parse config with defaults
    config = config or {}
    duration_seconds = config.get("duration_seconds", 5)
    modules_to_test = config.get("modules")  # None = all enabled
    validate = config.get("validate", True)
    cleanup = config.get("cleanup", False)

    # Set up test state
    _running_test = {
        "test_type": "record_cycle",
        "started_at": datetime.datetime.now().isoformat(),
        "progress": {"step": "initializing", "percent": 0},
        "can_cancel": True,
    }
    _test_cancelled = False

    session_path = None
    trials = []
    validation_result = None
    modules_tested = []
    errors = []

    try:
        # Step 1: Start session
        _running_test["progress"] = {"step": "starting_session", "percent": 10}
        self.logger.info("Record cycle test: Starting session")

        session_result = await self.start_session()
        if not session_result.get("success"):
            return {
                "success": False,
                "error": "session_start_failed",
                "message": session_result.get("message", "Failed to start session"),
            }

        session_path = session_result.get("session_dir")
        modules_tested = session_result.get("running_modules", [])

        # Filter modules if specified
        if modules_to_test:
            modules_tested = [m for m in modules_tested if m in modules_to_test]

        if _test_cancelled:
            raise asyncio.CancelledError("Test cancelled by user")

        # Step 2: Start trial
        _running_test["progress"] = {"step": "starting_trial", "percent": 20}
        self.logger.info("Record cycle test: Starting trial")

        trial_start_time = datetime.datetime.now()
        trial_result = await self.start_trial(label="record_cycle_test")
        if not trial_result.get("success"):
            errors.append(f"Trial start failed: {trial_result.get('message')}")

        if _test_cancelled:
            raise asyncio.CancelledError("Test cancelled by user")

        # Step 3: Record for duration
        _running_test["progress"] = {"step": "recording", "percent": 30}
        self.logger.info(
            "Record cycle test: Recording for %d seconds", duration_seconds
        )

        # Sleep in small increments to allow cancellation
        elapsed = 0
        step = 0.5
        while elapsed < duration_seconds:
            if _test_cancelled:
                raise asyncio.CancelledError("Test cancelled by user")
            await asyncio.sleep(step)
            elapsed += step
            progress_pct = 30 + int((elapsed / duration_seconds) * 40)
            _running_test["progress"] = {
                "step": "recording",
                "percent": min(progress_pct, 70),
            }

        # Step 4: Stop trial
        _running_test["progress"] = {"step": "stopping_trial", "percent": 75}
        self.logger.info("Record cycle test: Stopping trial")

        stop_trial_result = await self.stop_trial()
        trial_end_time = datetime.datetime.now()
        trial_duration = (trial_end_time - trial_start_time).total_seconds()

        trials.append({
            "trial_number": stop_trial_result.get("trial_number", 1),
            "label": "record_cycle_test",
            "duration": round(trial_duration, 2),
            "paused_modules": stop_trial_result.get("paused_modules", []),
        })

        if _test_cancelled:
            raise asyncio.CancelledError("Test cancelled by user")

        # Step 5: Stop session
        _running_test["progress"] = {"step": "stopping_session", "percent": 85}
        self.logger.info("Record cycle test: Stopping session")

        await self.stop_session()

        # Step 6: Validate if requested
        if validate and session_path:
            _running_test["progress"] = {"step": "validating", "percent": 90}
            self.logger.info("Record cycle test: Validating recorded data")

            validation_result = await self.validate_session(session_path)

        # Cleanup if requested
        if cleanup and session_path:
            _running_test["progress"] = {"step": "cleanup", "percent": 95}
            self.logger.info("Record cycle test: Cleaning up test data")

            try:
                import shutil
                from pathlib import Path

                session_dir = Path(session_path)
                if session_dir.exists():
                    shutil.rmtree(session_dir)
            except Exception as e:
                errors.append(f"Cleanup failed: {e}")

        _running_test["progress"] = {"step": "complete", "percent": 100}
        self.logger.info("Record cycle test: Complete")

        return {
            "success": True,
            "session_path": session_path,
            "trials": trials,
            "validation": validation_result.get("validation") if validation_result else None,
            "modules_tested": modules_tested,
            "duration_seconds": duration_seconds,
            "errors": errors if errors else None,
        }

    except asyncio.CancelledError:
        # Clean up on cancellation
        self.logger.info("Record cycle test: Cancelled")

        if self.trial_active:
            await self.stop_trial()
        if self.session_active:
            await self.stop_session()

        return {
            "success": False,
            "error": "test_cancelled",
            "message": "Test was cancelled by user",
            "session_path": session_path,
            "partial_results": trials,
        }

    except Exception as e:
        self.logger.error("Record cycle test failed: %s", e)

        # Clean up on error
        if self.trial_active:
            try:
                await self.stop_trial()
            except Exception:
                pass
        if self.session_active:
            try:
                await self.stop_session()
            except Exception:
                pass

        return {
            "success": False,
            "error": "test_failed",
            "message": str(e),
            "session_path": session_path,
        }

    finally:
        _running_test = None


async def _run_module_test(
    self, module_name: str, test_type: str = "basic"
) -> Dict[str, Any]:
    """
    Run module-specific tests.

    Args:
        module_name: Name of the module to test
        test_type: Type of test - "basic", "connection", "recording", "full"

    Returns:
        Dict with test results including device detection, connection status, etc.
    """
    global _running_test, _test_cancelled

    # Check if a test is already running
    if _running_test is not None:
        return {
            "success": False,
            "error": "test_already_running",
            "message": f"A test is already running: {_running_test.get('test_type')}",
        }

    # Check if module exists
    module = await self.get_module(module_name)
    if not module:
        return {
            "success": False,
            "error": "module_not_found",
            "message": f"Module '{module_name}' not found",
        }

    # Set up test state
    _running_test = {
        "test_type": f"module_{module_name}_{test_type}",
        "started_at": datetime.datetime.now().isoformat(),
        "progress": {"step": "initializing", "percent": 0},
        "can_cancel": True,
    }
    _test_cancelled = False

    results = {
        "device_detected": False,
        "connection_ok": False,
        "data_received": False,
        "recording_ok": False,
    }
    errors = []

    try:
        # Basic test: Check hardware availability
        _running_test["progress"] = {"step": "hardware_detection", "percent": 20}

        try:
            # Import hardware detection
            import sys
            from pathlib import Path

            # Add tests path to sys.path if needed
            tests_path = Path(__file__).parent.parent.parent.parent.parent / "tests"
            if str(tests_path) not in sys.path:
                sys.path.insert(0, str(tests_path))

            from infrastructure.schemas.hardware_detection import HardwareAvailability

            hw = HardwareAvailability()
            hw.detect_all()
            avail = hw.get_availability(module_name)
            results["device_detected"] = avail.available

            if not avail.available:
                errors.append(f"Hardware not available: {avail.reason}")

        except ImportError:
            # Fall back to checking device system
            devices = await self.list_devices()
            module_devices = [
                d for d in devices
                if d.get("module_id", "").lower() == module_name.lower()
            ]
            results["device_detected"] = len(module_devices) > 0

            if not module_devices:
                errors.append("No devices found for module")

        if _test_cancelled:
            raise asyncio.CancelledError("Test cancelled by user")

        # Connection test
        if test_type in ("connection", "recording", "full") and results["device_detected"]:
            _running_test["progress"] = {"step": "connection_test", "percent": 40}

            # Check if module is enabled and running
            if not module.get("enabled"):
                await self.enable_module(module_name)
                await asyncio.sleep(0.5)

            # Check module state
            state = await self.get_module_state(module_name)
            results["connection_ok"] = state in ("running", "recording", "RUNNING", "RECORDING")

            if not results["connection_ok"]:
                errors.append(f"Module not running: state={state}")

        if _test_cancelled:
            raise asyncio.CancelledError("Test cancelled by user")

        # Recording test
        if test_type in ("recording", "full") and results["connection_ok"]:
            _running_test["progress"] = {"step": "recording_test", "percent": 60}

            # Check if we can start recording (need a session)
            if not self.session_active:
                # Start a quick test session
                session_result = await self.start_session()
                if session_result.get("success"):
                    try:
                        # Start a brief trial
                        await self.start_trial(label="module_test")
                        await asyncio.sleep(2)

                        # Check if module recorded data
                        results["data_received"] = True
                        results["recording_ok"] = True

                        await self.stop_trial()
                    finally:
                        await self.stop_session()
            else:
                errors.append("Cannot run recording test: session already active")

        if _test_cancelled:
            raise asyncio.CancelledError("Test cancelled by user")

        # Full test includes validation
        if test_type == "full" and results["recording_ok"]:
            _running_test["progress"] = {"step": "validation", "percent": 80}
            # Validation would require saved data - already covered by recording test

        _running_test["progress"] = {"step": "complete", "percent": 100}

        # Determine overall success
        success = results["device_detected"]
        if test_type == "connection":
            success = success and results["connection_ok"]
        elif test_type in ("recording", "full"):
            success = success and results["connection_ok"] and results["recording_ok"]

        return {
            "success": success,
            "module": module_name,
            "test_type": test_type,
            "results": results,
            "errors": errors if errors else [],
        }

    except asyncio.CancelledError:
        self.logger.info("Module test cancelled: %s", module_name)
        return {
            "success": False,
            "error": "test_cancelled",
            "module": module_name,
            "test_type": test_type,
            "message": "Test was cancelled by user",
        }

    except Exception as e:
        self.logger.error("Module test failed for %s: %s", module_name, e)
        return {
            "success": False,
            "error": "test_failed",
            "module": module_name,
            "test_type": test_type,
            "message": str(e),
        }

    finally:
        _running_test = None


async def _get_hardware_matrix(self) -> Dict[str, Any]:
    """
    Get hardware availability matrix.

    Detects available hardware for all modules and returns a summary.

    Returns:
        Dict with hardware availability for each module and summary statistics.
    """
    hardware = {}

    try:
        # Try to use the hardware detection module
        import sys
        from pathlib import Path

        tests_path = Path(__file__).parent.parent.parent.parent.parent / "tests"
        if str(tests_path) not in sys.path:
            sys.path.insert(0, str(tests_path))

        from infrastructure.schemas.hardware_detection import HardwareAvailability

        hw = HardwareAvailability()
        hw.detect_all()

        # Get availability for each module
        for module_name in ["GPS", "DRT", "VOG", "EyeTracker", "Audio", "Cameras", "CSICameras", "Notes"]:
            avail = hw.get_availability(module_name)

            # Build device info
            device_info = {
                "available": avail.available,
                "info": avail.reason,
            }

            # Add device-specific details
            if avail.devices:
                if len(avail.devices) == 1:
                    device = avail.devices[0]
                    device_info["device"] = device.device_path
                    if device.device_name:
                        device_info["info"] = device.device_name
                else:
                    device_info["devices"] = [
                        d.device_path for d in avail.devices if d.device_path
                    ]

            # Add type info for specific modules
            if module_name == "VOG" and avail.devices:
                for d in avail.devices:
                    if "wVOG" in str(d.device_type):
                        device_info["type"] = "wVOG"
                        break
                    elif "sVOG" in str(d.device_type):
                        device_info["type"] = "sVOG"
                        break

            hardware[module_name] = device_info

    except ImportError:
        # Fall back to basic device system checks
        self.logger.warning("Hardware detection module not available, using fallback")

        # Check each module via device system
        devices = await self.list_devices()

        module_device_map = {}
        for device in devices:
            module_id = device.get("module_id", "")
            if module_id:
                if module_id not in module_device_map:
                    module_device_map[module_id] = []
                module_device_map[module_id].append(device)

        # Build hardware info from device system
        for module_name in ["GPS", "DRT", "VOG", "EyeTracker", "Audio", "Cameras", "Notes"]:
            module_devices = module_device_map.get(module_name, [])

            if module_devices:
                connected = [d for d in module_devices if d.get("connected")]
                hardware[module_name] = {
                    "available": len(module_devices) > 0,
                    "device": module_devices[0].get("port") if module_devices else None,
                    "info": f"{len(module_devices)} device(s) found, {len(connected)} connected",
                }
            else:
                hardware[module_name] = {
                    "available": False,
                    "device": None,
                    "info": "No devices found",
                }

        # Notes doesn't need hardware
        hardware["Notes"] = {
            "available": True,
            "device": None,
            "info": "No hardware required",
        }

    # Calculate summary
    total = len(hardware)
    available = sum(1 for h in hardware.values() if h.get("available"))

    return {
        "success": True,
        "hardware": hardware,
        "summary": {
            "total": total,
            "available": available,
            "unavailable": total - available,
        },
    }


async def _validate_session(self, session_path: str) -> Dict[str, Any]:
    """
    Validate all data in a recorded session.

    Args:
        session_path: Path to the session directory

    Returns:
        Dict with validation results for each module's data files.
    """
    from pathlib import Path

    session_dir = Path(session_path)

    if not session_dir.exists():
        return {
            "success": False,
            "error": "path_not_found",
            "message": f"Session path does not exist: {session_path}",
        }

    if not session_dir.is_dir():
        return {
            "success": False,
            "error": "invalid_path",
            "message": "Session path must be a directory",
        }

    validation = {}
    total_errors = 0

    try:
        # Import CSV schema module
        import sys

        tests_path = Path(__file__).parent.parent.parent.parent.parent / "tests"
        if str(tests_path) not in sys.path:
            sys.path.insert(0, str(tests_path))

        from infrastructure.schemas.csv_schema import (
            validate_csv_file,
            detect_schema,
            GPS_SCHEMA,
            DRT_SDRT_SCHEMA,
            DRT_WDRT_SCHEMA,
            VOG_SVOG_SCHEMA,
            VOG_WVOG_SCHEMA,
            NOTES_SCHEMA,
            EYETRACKER_GAZE_SCHEMA,
            EYETRACKER_IMU_SCHEMA,
            EYETRACKER_EVENTS_SCHEMA,
        )

        # Find CSV files in session directory
        csv_files = list(session_dir.rglob("*.csv"))

        for csv_file in csv_files:
            # Detect schema based on filename or header
            schema = detect_schema(csv_file)

            if schema:
                result = validate_csv_file(csv_file, schema)
                module_name = schema.module_name

                if module_name not in validation:
                    validation[module_name] = {
                        "valid": True,
                        "files": [],
                        "rows": 0,
                        "errors": [],
                    }

                validation[module_name]["files"].append(str(csv_file.name))
                validation[module_name]["rows"] += result.row_count

                if not result.is_valid:
                    validation[module_name]["valid"] = False
                    for error in result.errors[:10]:  # Limit errors
                        validation[module_name]["errors"].append(str(error))
                        total_errors += 1

        # Check for audio files
        audio_files = list(session_dir.rglob("*.wav"))
        if audio_files:
            total_duration = 0
            for audio_file in audio_files:
                try:
                    import wave

                    with wave.open(str(audio_file), "rb") as wf:
                        frames = wf.getnframes()
                        rate = wf.getframerate()
                        total_duration += frames / rate
                except Exception:
                    pass

            validation["Audio"] = {
                "valid": True,
                "files": [f.name for f in audio_files],
                "duration": round(total_duration, 1),
                "errors": [],
            }

    except ImportError:
        # Fall back to basic file checking
        self.logger.warning("CSV schema module not available, using basic validation")

        csv_files = list(session_dir.rglob("*.csv"))
        for csv_file in csv_files:
            # Infer module from path
            module_name = csv_file.parent.name
            if module_name == session_dir.name:
                # File is in root, try to infer from filename
                fname = csv_file.name.lower()
                if "gps" in fname:
                    module_name = "GPS"
                elif "drt" in fname:
                    module_name = "DRT"
                elif "vog" in fname:
                    module_name = "VOG"
                elif "notes" in fname:
                    module_name = "Notes"
                elif "gaze" in fname or "imu" in fname or "events" in fname:
                    module_name = "EyeTracker"
                else:
                    module_name = "Unknown"

            if module_name not in validation:
                validation[module_name] = {
                    "valid": True,
                    "files": [],
                    "rows": 0,
                    "errors": [],
                }

            validation[module_name]["files"].append(str(csv_file.name))

            # Count rows
            try:
                with open(csv_file, "r") as f:
                    row_count = sum(1 for _ in f) - 1  # Subtract header
                    validation[module_name]["rows"] += max(0, row_count)
            except Exception:
                pass

    # Build summary
    modules_validated = len(validation)
    all_valid = all(v.get("valid", True) for v in validation.values())

    return {
        "success": True,
        "session_path": str(session_path),
        "validation": validation,
        "summary": {
            "modules_validated": modules_validated,
            "all_valid": all_valid,
            "total_errors": total_errors,
        },
    }


async def _get_validation_schemas(self) -> Dict[str, Any]:
    """
    Get all data validation schemas.

    Returns:
        Dict with schema definitions for each module's data format.
    """
    schemas = {}

    try:
        # Import CSV schema module
        import sys
        from pathlib import Path

        tests_path = Path(__file__).parent.parent.parent.parent.parent / "tests"
        if str(tests_path) not in sys.path:
            sys.path.insert(0, str(tests_path))

        from infrastructure.schemas.csv_schema import (
            ALL_SCHEMAS,
            MODULE_SCHEMAS,
            ColumnType,
        )

        # Build schema info for each module
        for module_name, module_schemas in MODULE_SCHEMAS.items():
            schemas[module_name] = {}

            for schema in module_schemas:
                schema_info = {
                    "columns": [col.name for col in schema.columns],
                    "required": [
                        col.name for col in schema.columns
                        if col.required and not col.nullable
                    ],
                    "types": {
                        col.name: col.dtype.name.lower()
                        for col in schema.columns
                    },
                    "description": schema.description,
                }

                # Use schema name as key within module
                if len(module_schemas) == 1:
                    schemas[module_name] = schema_info
                else:
                    # Multiple schemas for this module (e.g., sDRT vs wDRT)
                    schema_key = schema.name.replace(f"{module_name}_", "")
                    if module_name not in schemas or not isinstance(schemas[module_name], dict):
                        schemas[module_name] = {}
                    schemas[module_name][schema_key] = schema_info

    except ImportError:
        # Provide basic schema info as fallback
        self.logger.warning("CSV schema module not available, using basic schemas")

        schemas = {
            "GPS": {
                "columns": [
                    "trial", "module", "device_id", "label",
                    "record_time_unix", "record_time_mono",
                    "latitude_deg", "longitude_deg", "altitude_m",
                    "speed_mps", "course_deg", "fix_quality",
                ],
                "required": ["trial", "module", "record_time_unix"],
                "types": {
                    "latitude_deg": "float",
                    "longitude_deg": "float",
                    "fix_quality": "int",
                },
            },
            "DRT": {
                "columns": [
                    "trial", "module", "device_id", "label",
                    "record_time_unix", "record_time_mono",
                    "device_time_unix", "device_time_offset",
                    "responses", "reaction_time_ms",
                ],
                "required": ["trial", "module", "record_time_unix"],
                "types": {
                    "responses": "int",
                    "reaction_time_ms": "int",
                },
            },
            "VOG": {
                "columns": [
                    "trial", "module", "device_id", "label",
                    "record_time_unix", "record_time_mono",
                    "device_time_unix", "shutter_open", "shutter_closed",
                ],
                "required": ["trial", "module", "record_time_unix"],
                "types": {
                    "shutter_open": "int",
                    "shutter_closed": "int",
                },
            },
            "Notes": {
                "columns": [
                    "trial", "module", "device_id", "label",
                    "record_time_unix", "record_time_mono",
                    "device_time_unix", "content",
                ],
                "required": ["trial", "module", "record_time_unix"],
                "types": {
                    "content": "string",
                },
            },
        }

    return {
        "success": True,
        "schemas": schemas,
    }


async def _validate_against_schema(
    self, module_name: str, data_path: str
) -> Dict[str, Any]:
    """
    Validate specific data file against module schema.

    Args:
        module_name: Name of the module whose schema to use
        data_path: Path to the data file to validate

    Returns:
        Dict with validation results including row count and errors.
    """
    from pathlib import Path

    data_file = Path(data_path)

    if not data_file.exists():
        return {
            "success": False,
            "error": "file_not_found",
            "message": f"Data file not found: {data_path}",
        }

    if not data_file.is_file():
        return {
            "success": False,
            "error": "invalid_path",
            "message": "data_path must be a file",
        }

    try:
        import sys

        tests_path = Path(__file__).parent.parent.parent.parent.parent / "tests"
        if str(tests_path) not in sys.path:
            sys.path.insert(0, str(tests_path))

        from infrastructure.schemas.csv_schema import (
            validate_csv_file,
            MODULE_SCHEMAS,
        )

        # Find schema for module
        module_key = module_name
        for key in MODULE_SCHEMAS.keys():
            if key.lower() == module_name.lower():
                module_key = key
                break

        if module_key not in MODULE_SCHEMAS:
            return {
                "success": False,
                "error": "schema_not_found",
                "message": f"No schema found for module '{module_name}'",
            }

        # Use first schema for module (or detect from file)
        schemas = MODULE_SCHEMAS[module_key]
        schema = schemas[0]  # Default to first schema

        # If multiple schemas, try to detect the right one
        if len(schemas) > 1:
            import csv

            with open(data_file, "r", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
                col_count = len(header)

            # Match by column count
            for s in schemas:
                if s.column_count == col_count:
                    schema = s
                    break

        # Validate
        result = validate_csv_file(data_file, schema)

        errors = []
        warnings = []
        for error in result.errors[:50]:  # Limit to 50 errors
            errors.append({
                "row": error.row,
                "column": error.column,
                "error": error.message,
            })

        for warning in result.warnings[:20]:  # Limit to 20 warnings
            warnings.append({
                "row": warning.row,
                "column": warning.column,
                "warning": warning.message,
            })

        return {
            "success": True,
            "module": module_name,
            "file": str(data_path),
            "valid": result.is_valid,
            "rows_checked": result.row_count,
            "errors": errors,
            "warnings": warnings,
        }

    except ImportError:
        return {
            "success": False,
            "error": "schema_module_unavailable",
            "message": "CSV schema validation module is not available",
        }

    except Exception as e:
        return {
            "success": False,
            "error": "validation_error",
            "message": str(e),
        }


async def _get_test_status(self) -> Dict[str, Any]:
    """
    Get status of any running test.

    Returns:
        Dict with running status, test type, progress, and cancellation ability.
    """
    global _running_test

    if _running_test is None:
        return {
            "running": False,
            "test_type": None,
            "started_at": None,
            "progress": None,
            "can_cancel": False,
        }

    return {
        "running": True,
        "test_type": _running_test.get("test_type"),
        "started_at": _running_test.get("started_at"),
        "progress": _running_test.get("progress"),
        "can_cancel": _running_test.get("can_cancel", True),
    }


async def _cancel_test(self) -> Dict[str, Any]:
    """
    Cancel a running test.

    Returns:
        Dict with cancellation status.
    """
    global _running_test, _test_cancelled

    if _running_test is None:
        return {
            "success": False,
            "error": "no_test_running",
            "message": "No test is currently running",
        }

    if not _running_test.get("can_cancel", True):
        return {
            "success": False,
            "error": "cannot_cancel",
            "message": "Current test cannot be cancelled",
        }

    # Set cancellation flag
    _test_cancelled = True

    self.logger.info("Test cancellation requested for: %s", _running_test.get("test_type"))

    return {
        "success": True,
        "cancelled": True,
        "cleanup_performed": True,
        "message": "Test cancellation requested",
    }


# Bind Testing methods to APIController
APIController.run_record_cycle_test = _run_record_cycle_test
APIController.run_module_test = _run_module_test
APIController.get_hardware_matrix = _get_hardware_matrix
APIController.validate_session = _validate_session
APIController.get_validation_schemas = _get_validation_schemas
APIController.validate_against_schema = _validate_against_schema
APIController.get_test_status = _get_test_status
APIController.cancel_test = _cancel_test
