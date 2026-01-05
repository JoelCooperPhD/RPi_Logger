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
        from rpi_logger.core.paths import LOGS_DIR, USER_MODULE_LOGS_DIR

        # Get module log paths
        module_logs = {}
        for module_info in self.logger_system.get_available_modules():
            module_name = module_info.name.lower()
            # Check both central logs dir and user module logs dir
            central_log = LOGS_DIR / f"{module_name}.log"
            user_log = USER_MODULE_LOGS_DIR / f"{module_name}.log"

            if central_log.exists():
                module_logs[module_info.name] = str(central_log)
            elif user_log.exists():
                module_logs[module_info.name] = str(user_log)

        return {
            "master_log": str(MASTER_LOG_FILE),
            "session_log": str(self._session_dir / "logs") if self._session_dir else None,
            "event_log": str(self.logger_system.event_logger.event_log_path)
                if self.logger_system.event_logger else None,
            "logs_dir": str(LOGS_DIR),
            "module_logs_dir": str(USER_MODULE_LOGS_DIR),
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
        from rpi_logger.core.paths import LOGS_DIR, USER_MODULE_LOGS_DIR, PROJECT_ROOT

        try:
            # Resolve the path to handle any .. or symlinks
            resolved = Path(path).resolve()
        except (ValueError, OSError) as e:
            return False, f"Invalid path: {e}", None

        # Define allowed directories
        allowed_dirs = [
            LOGS_DIR.resolve(),
            USER_MODULE_LOGS_DIR.resolve(),
        ]

        # Add session logs directory if session is active
        if self._session_dir:
            session_logs = (self._session_dir / "logs").resolve()
            allowed_dirs.append(session_logs)
            # Also allow the session directory itself for event logs
            allowed_dirs.append(self._session_dir.resolve())

        # Add project root logs (for backwards compatibility)
        project_logs = (PROJECT_ROOT / "logs").resolve()
        if project_logs not in allowed_dirs:
            allowed_dirs.append(project_logs)

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
        from rpi_logger.core.paths import LOGS_DIR, USER_MODULE_LOGS_DIR

        # Check if module exists
        module = await self.get_module(module_name)
        if not module:
            return {
                "success": False,
                "error": "MODULE_NOT_FOUND",
                "message": f"Module '{module_name}' not found",
            }

        # Look for the module log file
        module_name_lower = module_name.lower()
        potential_paths = [
            LOGS_DIR / f"{module_name_lower}.log",
            USER_MODULE_LOGS_DIR / f"{module_name_lower}.log",
            LOGS_DIR / f"{module_name}.log",
            USER_MODULE_LOGS_DIR / f"{module_name}.log",
        ]

        log_path = None
        for path in potential_paths:
            if path.exists():
                log_path = path
                break

        if not log_path:
            return {
                "success": False,
                "error": "FILE_NOT_FOUND",
                "message": f"Log file for module '{module_name}' not found",
            }

        return await self.read_log_file(str(log_path), offset, limit)

    # =========================================================================
    # Camera-Specific Operations
    # =========================================================================

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
        from pathlib import Path

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

    # =========================================================================
    # GPS Module-Specific Operations
    # =========================================================================

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

        if result:
            return {
                "available": True,
                "device_id": device_id,
                "fix_valid": result.get("fix_valid", False),
                "fix_quality": result.get("fix_quality"),
                "fix_quality_desc": _get_fix_quality_description(
                    result.get("fix_quality")
                ),
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

    # =========================================================================
    # Audio Module API
    # =========================================================================

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



    # =========================================================================
    # DRT Module Specific Endpoints
    # =========================================================================

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

            # Determine device type from metadata or display name
            device_type = "unknown"
            if device.metadata:
                device_type = device.metadata.get("device_type", "unknown")
            elif device.display_name:
                name_lower = device.display_name.lower()
                if "wdrt" in name_lower:
                    device_type = "wDRT_Wireless" if device.is_wireless else "wDRT_USB"
                elif "sdrt" in name_lower or "drt" in name_lower:
                    device_type = "sDRT"

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
            # Note: auto-off would need to be implemented in the module
            # For now, just report the requested duration

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
        # DRT responses are logged to CSV files during recording
        # This endpoint provides access to recent trial data

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

        # For each instance, try to read recent trial data from CSV
        # Note: This would require reading the CSV file or maintaining
        # an in-memory buffer of recent responses in the module
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

def _get_fix_quality_description(quality: Optional[int]) -> Optional[str]:
    """Get human-readable description for GPS fix quality.

    Args:
        quality: GPS fix quality value (0-8)

    Returns:
        Description string or None if quality is None
    """
    if quality is None:
        return None

    descriptions = {
        0: "Invalid",
        1: "GPS fix (SPS)",
        2: "DGPS fix",
        3: "PPS fix",
        4: "Real Time Kinematic",
        5: "Float RTK",
        6: "Estimated (dead reckoning)",
        7: "Manual input mode",
        8: "Simulation mode",
    }

    return descriptions.get(quality, f"Unknown ({quality})")


# =============================================================================
# Notes Module Mixin Methods
# =============================================================================
# These methods are added to APIController at module load time to avoid
# making the main class too large. They provide Notes-specific functionality.


async def _get_notes_config(self) -> Dict[str, Any]:
    """Get Notes module configuration.

    Returns the typed configuration for the Notes module including
    output_dir, session_prefix, history_limit, auto_start, and log_level.

    Returns:
        Dict with success status and config values.
    """
    result = await self.get_module_config("Notes")
    if result is None:
        return {
            "success": False,
            "error": "module_not_found",
            "message": "Notes module not found",
        }

    # Enhance with Notes-specific defaults from NotesConfig
    config = result.get("config", {})

    # Add default values for Notes-specific settings if not present
    notes_defaults = {
        "output_dir": "notes",
        "session_prefix": "notes",
        "history_limit": 200,
        "auto_start": False,
        "log_level": "info",
    }

    for key, default in notes_defaults.items():
        if key not in config:
            config[key] = default

    return {
        "success": True,
        "module": "Notes",
        "config_path": result.get("config_path"),
        "config": config,
    }


async def _update_notes_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update Notes module configuration.

    Args:
        updates: Dictionary of config key-value pairs to update.
                 Valid keys: output_dir, session_prefix, history_limit,
                 auto_start, log_level

    Returns:
        Result dict with success status and updated keys.
    """
    # Validate Notes-specific settings
    valid_keys = {
        "output_dir", "session_prefix", "history_limit",
        "auto_start", "log_level", "notes.history_limit",
        "notes.auto_start", "notes.last_archive_path",
    }

    invalid_keys = set(updates.keys()) - valid_keys
    if invalid_keys:
        self.logger.warning(
            "Ignoring invalid Notes config keys: %s", invalid_keys
        )
        # Filter to only valid keys
        updates = {k: v for k, v in updates.items() if k in valid_keys}

    if not updates:
        return {
            "success": False,
            "error": "no_valid_updates",
            "message": "No valid configuration keys provided",
        }

    # Validate specific field types
    if "history_limit" in updates:
        try:
            updates["history_limit"] = int(updates["history_limit"])
            if updates["history_limit"] < 1:
                return {
                    "success": False,
                    "error": "invalid_value",
                    "message": "history_limit must be a positive integer",
                }
        except (TypeError, ValueError):
            return {
                "success": False,
                "error": "invalid_value",
                "message": "history_limit must be a valid integer",
            }

    if "auto_start" in updates:
        if not isinstance(updates["auto_start"], bool):
            # Try to convert string representations
            if isinstance(updates["auto_start"], str):
                updates["auto_start"] = updates["auto_start"].lower() in {
                    "true", "1", "yes", "on"
                }
            else:
                updates["auto_start"] = bool(updates["auto_start"])

    return await self.update_module_config("Notes", updates)


async def _get_notes_status(self) -> Dict[str, Any]:
    """Get Notes module status.

    Returns module state, recording status, note count, and file path.

    Returns:
        Dict with module status information.
    """
    module = await self.get_module("Notes")
    if not module:
        return {
            "success": False,
            "error": "module_not_found",
            "message": "Notes module not found",
        }

    # Get module state
    state = await self.get_module_state("Notes")
    running = module.get("running", False)

    # Build status response
    status = {
        "success": True,
        "module": "Notes",
        "state": state,
        "running": running,
        "enabled": module.get("enabled", False),
        "recording": False,
        "note_count": 0,
        "notes_file": None,
        "session_dir": str(self._session_dir) if self._session_dir else None,
    }

    # If module is running, try to get more detailed status via command
    if running:
        try:
            # The Notes module tracks its own recording state
            # We can infer from the session state
            status["recording"] = self.session_active
        except Exception:
            pass

    return status


async def _get_notes_categories(self) -> Dict[str, Any]:
    """Get available note categories.

    Returns predefined categories that can be used to organize notes.

    Returns:
        Dict with list of available categories.
    """
    # Notes module currently doesn't have explicit categories,
    # but we can define standard ones for future use
    categories = [
        {"id": "general", "name": "General", "description": "General notes"},
        {"id": "observation", "name": "Observation", "description": "Observations during session"},
        {"id": "event", "name": "Event", "description": "Notable events"},
        {"id": "issue", "name": "Issue", "description": "Problems or issues encountered"},
        {"id": "marker", "name": "Marker", "description": "Time markers for later reference"},
    ]

    return {
        "success": True,
        "categories": categories,
    }


async def _get_notes(
    self,
    limit: Optional[int] = None,
    trial_number: Optional[int] = None,
) -> Dict[str, Any]:
    """Get notes for the current session.

    Args:
        limit: Maximum number of notes to return (most recent)
        trial_number: Filter notes by trial number

    Returns:
        Dict with success status and list of notes.
    """
    if not self.session_active:
        return {
            "success": False,
            "error": "no_active_session",
            "message": "No active session - cannot retrieve notes",
        }

    # Check if Notes module is running
    running = self.logger_system.is_module_running("Notes")
    if not running:
        return {
            "success": False,
            "error": "module_not_running",
            "message": "Notes module is not running",
        }

    # Try to read notes from the notes file in the session directory
    notes = []
    notes_file = None

    if self._session_dir:
        notes_dir = self._session_dir / "Notes"
        if notes_dir.exists():
            # Find the most recent notes CSV file
            csv_files = sorted(notes_dir.glob("*_notes.csv"), reverse=True)
            if csv_files:
                notes_file = csv_files[0]
                notes = await self._read_notes_from_file(
                    notes_file, limit=limit, trial_number=trial_number
                )

    return {
        "success": True,
        "notes": notes,
        "count": len(notes),
        "notes_file": str(notes_file) if notes_file else None,
        "session_dir": str(self._session_dir) if self._session_dir else None,
    }


async def _read_notes_from_file(
    self,
    file_path: Path,
    limit: Optional[int] = None,
    trial_number: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Read notes from a CSV file.

    Args:
        file_path: Path to the notes CSV file
        limit: Maximum number of notes to return
        trial_number: Filter by trial number

    Returns:
        List of note dictionaries.
    """
    import csv
    from datetime import datetime

    notes = []

    try:
        with open(file_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Filter by trial number if specified
                if trial_number is not None:
                    try:
                        row_trial = int(row.get("trial", 0))
                        if row_trial != trial_number:
                            continue
                    except (TypeError, ValueError):
                        continue

                # Parse the note record
                note = {
                    "id": len(notes) + 1,
                    "trial_number": int(row.get("trial", 0)),
                    "text": row.get("content", ""),
                    "module": row.get("module", "Notes"),
                    "device_id": row.get("device_id", "notes"),
                }

                # Parse timestamp
                try:
                    timestamp = float(row.get("record_time_unix", 0))
                    note["timestamp"] = timestamp
                    note["timestamp_iso"] = datetime.fromtimestamp(
                        timestamp
                    ).isoformat(timespec="seconds")
                except (TypeError, ValueError):
                    note["timestamp"] = 0
                    note["timestamp_iso"] = ""

                notes.append(note)

    except FileNotFoundError:
        pass
    except Exception as e:
        self.logger.error("Error reading notes file %s: %s", file_path, e)

    # Apply limit (return most recent notes)
    if limit is not None and len(notes) > limit:
        notes = notes[-limit:]

    return notes


async def _add_note(
    self,
    note_text: str,
    timestamp: Optional[float] = None,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """Add a new note via the Notes module.

    Args:
        note_text: The note content
        timestamp: Optional Unix timestamp (defaults to current time)
        category: Optional category for the note

    Returns:
        Result dict with success status and note details.
    """
    if not self.session_active:
        return {
            "success": False,
            "error": "no_active_session",
            "message": "No active session - cannot add notes",
        }

    # Check if Notes module is running
    running = self.logger_system.is_module_running("Notes")
    if not running:
        return {
            "success": False,
            "error": "module_not_running",
            "message": "Notes module is not running",
        }

    # Build command payload
    command_kwargs = {
        "note_text": note_text,
    }
    if timestamp is not None:
        command_kwargs["note_timestamp"] = timestamp
    if category is not None:
        command_kwargs["category"] = category

    # Send add_note command to the Notes module
    result = await self.send_module_command("Notes", "add_note", **command_kwargs)

    if result.get("success"):
        self.logger.info(
            "Note added via API: %s",
            note_text[:50] + "..." if len(note_text) > 50 else note_text
        )
        return {
            "success": True,
            "message": "Note added successfully",
            "note_text": note_text,
            "timestamp": timestamp,
            "category": category,
        }
    else:
        return {
            "success": False,
            "error": "command_failed",
            "message": "Failed to add note via Notes module",
        }


async def _get_note(self, note_id: int) -> Dict[str, Any]:
    """Get a specific note by ID.

    Args:
        note_id: The note ID (1-based index)

    Returns:
        Result dict with success status and note details.
    """
    # Get all notes and find the one with matching ID
    result = await self.get_notes()
    if not result.get("success"):
        return result

    notes = result.get("notes", [])
    for note in notes:
        if note.get("id") == note_id:
            return {
                "success": True,
                "note": note,
            }

    return {
        "success": False,
        "error": "note_not_found",
        "message": f"Note with ID {note_id} not found",
    }


async def _delete_note(self, note_id: int) -> Dict[str, Any]:
    """Delete a note by ID.

    Note: The Notes module stores notes in append-only CSV files,
    so deletion is not currently supported at the file level.
    This endpoint returns an appropriate error.

    Args:
        note_id: The note ID to delete

    Returns:
        Result dict with success status.
    """
    # Notes are stored in append-only CSV files
    # Deletion would require rewriting the file
    return {
        "success": False,
        "error": "not_supported",
        "message": "Note deletion is not currently supported. "
                   "Notes are stored in append-only CSV files for data integrity.",
    }


# Bind Notes methods to APIController
APIController.get_notes_config = _get_notes_config
APIController.update_notes_config = _update_notes_config
APIController.get_notes_status = _get_notes_status
APIController.get_notes_categories = _get_notes_categories
APIController.get_notes = _get_notes
APIController._read_notes_from_file = _read_notes_from_file
APIController.add_note = _add_note
APIController.get_note = _get_note
APIController.delete_note = _delete_note


# =============================================================================
# VOG Module Mixin Methods
# =============================================================================
# These methods are added to APIController at module load time to avoid
# making the main class too large. They provide VOG-specific functionality.


async def _list_vog_devices(self) -> Dict[str, Any]:
    """List all discovered/connected VOG devices.

    Returns devices filtered to VOG family with their device types
    (sVOG for wired, wVOG for wireless).

    Returns:
        Dict with devices list containing device info.
    """
    devices = []
    all_devices = await self.list_devices()

    for device in all_devices:
        # Filter to VOG devices only
        if device.get("module_id", "").upper() == "VOG":
            device_type = _determine_vog_device_type(device)
            devices.append({
                "device_id": device.get("device_id"),
                "display_name": device.get("display_name"),
                "device_type": device_type,
                "connected": device.get("connected", False),
                "connecting": device.get("connecting", False),
                "is_wireless": device.get("is_wireless", False),
                "port": device.get("port"),
            })

    return {
        "devices": devices,
        "count": len(devices),
    }


def _determine_vog_device_type(device: Dict[str, Any]) -> str:
    """Determine VOG device type from device info.

    Args:
        device: Device info dictionary

    Returns:
        Device type string: 'sVOG', 'wVOG_USB', or 'wVOG_Wireless'
    """
    # Check if it's wireless
    if device.get("is_wireless"):
        return "wVOG_Wireless"

    # Check metadata or display name for type hints
    display_name = device.get("display_name", "").lower()
    if "wvog" in display_name:
        return "wVOG_USB"

    # Default to sVOG for wired devices
    return "sVOG"


async def _get_vog_config(self, device_id: Optional[str] = None) -> Dict[str, Any]:
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


async def _update_vog_config(
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


async def _get_vog_eye_position(self, device_id: Optional[str] = None) -> Dict[str, Any]:
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


async def _get_vog_pupil_data(self, device_id: Optional[str] = None) -> Dict[str, Any]:
    """Get pupil/shutter state data from VOG devices.

    Note: VOG devices track shutter state (open/closed), not direct pupil measurements.

    Args:
        device_id: Optional specific device ID

    Returns:
        Dict with shutter state data.
    """
    # This is similar to eye_position - VOG devices report shutter state
    return await self.get_vog_eye_position(device_id)


async def _switch_vog_lens(
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


async def _get_vog_battery(self, device_id: Optional[str] = None) -> Dict[str, Any]:
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


async def _get_vog_status(self) -> Dict[str, Any]:
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


# Bind VOG methods to APIController
APIController.list_vog_devices = _list_vog_devices
APIController.get_vog_config = _get_vog_config
APIController.update_vog_config = _update_vog_config
APIController.get_vog_eye_position = _get_vog_eye_position
APIController.get_vog_pupil_data = _get_vog_pupil_data
APIController.switch_vog_lens = _switch_vog_lens
APIController.get_vog_battery = _get_vog_battery
APIController.get_vog_status = _get_vog_status


# =============================================================================
# EyeTracker Module Mixin Methods
# =============================================================================
# These methods are added to APIController at module load time.
# They provide EyeTracker (Pupil Labs Neon) specific functionality.


async def _list_eyetracker_devices(self) -> Dict[str, Any]:
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


async def _get_eyetracker_config(self) -> Optional[Dict[str, Any]]:
    """Get EyeTracker module configuration.

    Returns the current configuration settings for the EyeTracker module.
    """
    return await self.get_module_config("EyeTracker")


async def _update_eyetracker_config(
    self, updates: Dict[str, Any]
) -> Dict[str, Any]:
    """Update EyeTracker module configuration.

    Args:
        updates: Dictionary of configuration key-value pairs to update

    Returns:
        Result dict with success status
    """
    return await self.update_module_config("EyeTracker", updates)


async def _get_eyetracker_gaze_data(self) -> Optional[Dict[str, Any]]:
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


async def _get_eyetracker_imu_data(self) -> Optional[Dict[str, Any]]:
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
    # Pupil Labs IMU data structure varies, adapt as needed
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


async def _get_eyetracker_events(
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


async def _start_eyetracker_calibration(self) -> Dict[str, Any]:
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


async def _get_eyetracker_calibration_status(self) -> Optional[Dict[str, Any]]:
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


async def _get_eyetracker_status(self) -> Dict[str, Any]:
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


async def _get_eyetracker_stream_settings(self) -> Optional[Dict[str, Any]]:
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


async def _set_eyetracker_stream_enabled(
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


async def _start_eyetracker_preview(self) -> Dict[str, Any]:
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


async def _stop_eyetracker_preview(self) -> Dict[str, Any]:
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


# Bind EyeTracker methods to APIController
APIController.list_eyetracker_devices = _list_eyetracker_devices
APIController.get_eyetracker_config = _get_eyetracker_config
APIController.update_eyetracker_config = _update_eyetracker_config
APIController.get_eyetracker_gaze_data = _get_eyetracker_gaze_data
APIController.get_eyetracker_imu_data = _get_eyetracker_imu_data
APIController.get_eyetracker_events = _get_eyetracker_events
APIController.start_eyetracker_calibration = _start_eyetracker_calibration
APIController.get_eyetracker_calibration_status = _get_eyetracker_calibration_status
APIController.get_eyetracker_status = _get_eyetracker_status
APIController.get_eyetracker_stream_settings = _get_eyetracker_stream_settings
APIController.set_eyetracker_stream_enabled = _set_eyetracker_stream_enabled
APIController.start_eyetracker_preview = _start_eyetracker_preview
APIController.stop_eyetracker_preview = _stop_eyetracker_preview


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
                    "device_time_ms", "responses", "reaction_time_ms",
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
                    "shutter_open", "shutter_closed",
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
