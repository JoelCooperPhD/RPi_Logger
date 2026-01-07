
import asyncio
from rpi_logger.core.logging_utils import get_module_logger
import sys
from enum import Enum
from pathlib import Path
from typing import Awaitable, Callable, Optional

from .commands import CommandMessage, StatusMessage, StatusType
from .module_discovery import ModuleInfo
from .config_manager import get_config_manager
from .platform_info import get_platform_info
from .window_manager import WindowGeometry
from .paths import PROJECT_ROOT, _is_frozen
from rpi_logger.modules.base import gui_utils


class ModuleState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    INITIALIZING = "initializing"
    IDLE = "idle"
    RECORDING = "recording"
    STOPPING = "stopping"
    ERROR = "error"
    CRASHED = "crashed"


class ModuleProcess:

    def __init__(
        self,
        module_info: ModuleInfo,
        output_dir: Path,
        session_prefix: str = "session",
        status_callback: Optional[Callable] = None,
        log_level: str = "info",
        window_geometry: Optional[WindowGeometry] = None,
        instance_id: Optional[str] = None,
        config_path: Optional[Path] = None,
        camera_index: Optional[int] = None,
    ):
        self.module_info = module_info
        self.output_dir = Path(output_dir)
        self.session_prefix = session_prefix
        self.status_callback = status_callback
        self.log_level = log_level
        self.window_geometry = window_geometry
        self.instance_id = instance_id
        self.config_path = config_path
        self.camera_index = camera_index

        self.logger = get_module_logger(f"ModuleProcess.{module_info.name}")

        self.process: Optional[asyncio.subprocess.Process] = None
        self.state = ModuleState.STOPPED
        self.last_status = None
        self.error_message = None
        self.window_visible = False

        self.stdout_task: Optional[asyncio.Task] = None
        self.stderr_task: Optional[asyncio.Task] = None
        self.monitor_task: Optional[asyncio.Task] = None

        # Bounded queue to prevent memory exhaustion (100 commands should be plenty)
        self.command_queue: asyncio.Queue = asyncio.Queue(maxsize=100)

        self.shutdown_event = asyncio.Event()
        self._was_forcefully_stopped = False

        # XBee send callback (set by logger system for routing XBee sends)
        self._xbee_send_callback: Optional[Callable[[str, bytes], Awaitable[bool]]] = None

        # Shutdown coordinator (active only during stop())
        self._shutdown_coordinator = None

    async def start(self) -> bool:
        if self.process is not None:
            self.logger.warning("Process already running")
            return False

        self.logger.info("Starting module: %s", self.module_info.name)
        self.state = ModuleState.STARTING

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)

            base_args = [
                "--output-dir", str(self.output_dir),
                "--session-prefix", self.session_prefix,
                "--log-level", self.log_level,
                "--no-console",
                "--enable-commands",
            ]

            if self.window_geometry:
                # Pass raw Tk geometry - no denormalization needed
                geometry_str = gui_utils.format_geometry_string(
                    self.window_geometry.width,
                    self.window_geometry.height,
                    self.window_geometry.x,
                    self.window_geometry.y,
                )
                base_args.extend([
                    "--window-geometry", geometry_str
                ])

            # Pass instance ID to subprocess for multi-instance modules
            if self.instance_id:
                base_args.extend(["--instance-id", self.instance_id])

            # Pass instance-specific config path for multi-instance modules
            if self.config_path:
                base_args.extend(["--config-path", str(self.config_path)])

            # Pass camera index for CSI camera modules (enables direct init without assign_device)
            if self.camera_index is not None:
                base_args.extend(["--camera-index", str(self.camera_index)])

            # Pass platform information to subprocess
            platform_info = get_platform_info()
            base_args.extend(platform_info.to_cli_args())

            # Determine how to run the module
            if _is_frozen():
                # In PyInstaller bundle, use the frozen executable with --run-module
                # This routes through __main__.py which dispatches to the correct module
                module_id = self.module_info.module_id
                self.logger.info("Running in frozen mode, launching module: %s", module_id)
                cmd = [sys.executable, "--run-module", module_id] + base_args
            else:
                # Normal development mode - use venv python if available
                venv_python = self._find_venv_python()
                if venv_python:
                    cmd = [venv_python, str(self.module_info.entry_point)] + base_args
                else:
                    cmd = [sys.executable, str(self.module_info.entry_point)] + base_args

            self.logger.debug("Command: %s", ' '.join(cmd))

            import os
            env = os.environ.copy()
            pythonpath_root = PROJECT_ROOT
            # Add the stub directory to PYTHONPATH to support vmc module
            stub_path = PROJECT_ROOT / "rpi_logger" / "modules" / "stub (codex)"
            
            paths_to_add = [str(pythonpath_root)]
            if stub_path.exists():
                paths_to_add.append(str(stub_path))
                
            existing_pythonpath = env.get('PYTHONPATH')
            if existing_pythonpath:
                paths_to_add.append(existing_pythonpath)
                
            env['PYTHONPATH'] = os.pathsep.join(paths_to_add)

            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            self.logger.info("Process started with PID: %d", self.process.pid)

            self.stdout_task = asyncio.create_task(self._stdout_reader())
            self.stderr_task = asyncio.create_task(self._stderr_reader())
            self.monitor_task = asyncio.create_task(self._process_monitor())

            asyncio.create_task(self._stdin_writer())

            self._was_forcefully_stopped = False
            return True

        except Exception as e:
            self.logger.error("Failed to start process: %s", e, exc_info=True)
            self.state = ModuleState.ERROR
            self.error_message = str(e)
            return False

    def _find_venv_python(self) -> Optional[str]:
        venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
        if venv_python.exists():
            return str(venv_python)

        return None

    def _find_uv(self) -> Optional[str]:
        import shutil
        uv = shutil.which("uv")
        if uv:
            return uv

        user_uv = Path.home() / ".local" / "bin" / "uv"
        if user_uv.exists():
            return str(user_uv)

        return None

    async def _stdout_reader(self) -> None:
        if not self.process or not self.process.stdout:
            return

        try:
            while not self.shutdown_event.is_set():
                line = await self.process.stdout.readline()
                if not line:
                    break

                # Always decode defensively so a single bad byte doesn't stop
                # draining the pipe (which can deadlock a chatty subprocess).
                line_str = line.decode("utf-8", errors="replace").strip()
                if line_str:
                    status = StatusMessage(line_str)
                    if status.is_valid():
                        await self._handle_status(status)
                    else:
                        self.logger.debug("Module output: %s", line_str)

        except Exception as e:
            self.logger.error("stdout reader error: %s", e, exc_info=True)

    async def _stderr_reader(self) -> None:
        if not self.process or not self.process.stderr:
            return

        try:
            while not self.shutdown_event.is_set():
                line = await self.process.stderr.readline()
                if not line:
                    break

                # Always decode defensively so a single bad byte doesn't stop
                # draining the pipe (which can deadlock a chatty subprocess).
                line_str = line.decode("utf-8", errors="replace").strip()
                if line_str:
                    self.logger.warning("Module stderr: %s", line_str)

        except Exception as e:
            self.logger.error("stderr reader error: %s", e, exc_info=True)

    async def _stdin_writer(self) -> None:
        if not self.process or not self.process.stdin:
            return

        try:
            while not self.shutdown_event.is_set():
                try:
                    command = await asyncio.wait_for(
                        self.command_queue.get(),
                        timeout=0.1
                    )

                    self.process.stdin.write(command.encode())
                    await self.process.stdin.drain()
                    self.logger.debug("Sent command: %s", command.strip())

                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    self.logger.error("stdin writer error: %s", e)
                    break

        except Exception as e:
            self.logger.error("stdin writer task error: %s", e, exc_info=True)

    async def _process_monitor(self) -> None:
        if not self.process:
            return

        try:
            returncode = await self.process.wait()

            if not self.shutdown_event.is_set():
                if returncode == 0:
                    self.logger.info("Process exited normally (user closed window)")
                    self.state = ModuleState.STOPPED
                else:
                    self.logger.error("Process crashed with exit code: %d", returncode)
                    self.state = ModuleState.CRASHED
                    self.error_message = f"Process exited with code {returncode}"
                    self._was_forcefully_stopped = True

                if self.status_callback:
                    await self.status_callback(self, None)
            else:
                self.logger.info("Process exited normally (quit command)")
                self.state = ModuleState.STOPPED

                if self.status_callback:
                    await self.status_callback(self, None)

        except Exception as e:
            self.logger.error("Process monitor error: %s", e, exc_info=True)

    async def _handle_status(self, status: StatusMessage) -> None:
        self.last_status = status
        status_type = status.get_status_type()

        self.logger.info("Status: %s - %s", status_type, status.get_payload())

        if status_type == "ready":
            self.state = ModuleState.IDLE
        elif status_type == "recording_started":
            self.state = ModuleState.RECORDING
        elif status_type == "recording_stopped":
            self.state = ModuleState.IDLE
        # Note: geometry_changed is handled by LoggerSystem via status_callback
        elif status_type == "error":
            self.state = ModuleState.ERROR
            self.error_message = status.get_error_message()
        elif status_type == "quitting":
            self.state = ModuleState.STOPPED
            # This prevents _process_monitor() from marking it as CRASHED
            self.shutdown_event.set()
            self._was_forcefully_stopped = False
            # Note: Do NOT update enabled state here - the module type stays enabled
            # The user just closed the window, they can click the device tile to reopen
            # The device section remains visible and device scanning continues
        elif status_type == "window_hidden":
            self.window_visible = False
        elif status_type == "window_shown":
            self.window_visible = True
        elif status_type == StatusType.XBEE_SEND:
            # Module wants to send data via XBee
            await self._handle_xbee_send(status.get_payload())
        elif status_type == StatusType.DEVICE_UNASSIGNED:
            # Route to shutdown coordinator if active
            command_id = status.get_command_id()
            if command_id and hasattr(self, '_shutdown_coordinator') and self._shutdown_coordinator:
                self._shutdown_coordinator.on_device_unassigned(
                    command_id=command_id,
                    data=status.get_payload(),
                )

        if self.status_callback:
            try:
                await self.status_callback(self, status)
            except Exception as e:
                self.logger.error("Status callback error: %s", e)

    async def send_command(self, command: str) -> None:
        if self.state in (ModuleState.STOPPED, ModuleState.CRASHED):
            self.logger.warning("Cannot send command - process not running")
            return

        try:
            # Use wait_for to avoid blocking indefinitely if queue is full
            await asyncio.wait_for(self.command_queue.put(command), timeout=5.0)
        except asyncio.TimeoutError:
            self.logger.error(
                "Command queue full after 5s timeout, dropping command: %s",
                command[:100]
            )

    async def start_session(self) -> None:
        await self.send_command(CommandMessage.start_session(session_dir=str(self.output_dir)))

    async def stop_session(self) -> None:
        await self.send_command(CommandMessage.stop_session())

    async def record(self, trial_number: int = None, trial_label: str = None) -> None:
        await self.send_command(CommandMessage.record(session_dir=str(self.output_dir), trial_number=trial_number, trial_label=trial_label))

    async def pause(self) -> None:
        await self.send_command(CommandMessage.pause())

    async def start_recording(self, trial_number: int = None, trial_label: str = None) -> None:
        await self.record(trial_number, trial_label)

    async def stop_recording(self) -> None:
        await self.pause()

    async def get_status(self) -> None:
        await self.send_command(CommandMessage.get_status())

    async def take_snapshot(self) -> None:
        await self.send_command(CommandMessage.take_snapshot())

    # =========================================================================
    # XBee Wireless Communication
    # =========================================================================

    def set_xbee_send_callback(self, callback: Callable[[str, bytes], Awaitable[bool]]) -> None:
        """Set callback for handling XBee send requests from this module."""
        self._xbee_send_callback = callback

    async def send_xbee_data(self, node_id: str, data: str) -> None:
        """Forward XBee data to this module."""
        await self.send_command(CommandMessage.xbee_data(node_id, data))

    async def _handle_xbee_send(self, payload: dict) -> None:
        """Handle xbee_send status from module - forward to XBee manager."""
        node_id = payload.get("node_id")
        data = payload.get("data")

        if not node_id or not data:
            self.logger.warning("Invalid xbee_send payload: %s", payload)
            return

        success = False
        if self._xbee_send_callback:
            try:
                success = await self._xbee_send_callback(node_id, data.encode())
            except Exception as e:
                self.logger.error("XBee send callback error: %s", e)
                success = False

        # Send result back to module
        await self.send_command(CommandMessage.xbee_send_result(node_id, success))

    async def stop(self, timeout: float = 3.0) -> None:
        """
        Stop the module process with ACK-based device unassignment.

        This replaces the previous blind sleep with proper acknowledgment:
        1. Send unassign_all_devices with command_id
        2. Wait for device_unassigned ACK (or timeout)
        3. Send quit command
        4. Wait for graceful exit, escalate to SIGTERM/SIGKILL if needed
        5. Drain pipes and clean up reader tasks
        """
        from rpi_logger.core.connection import ShutdownCoordinator

        if self.process is None:
            self.logger.debug("Process not running")
            return

        self.logger.info("Stopping module: %s", self.module_info.name)
        self.state = ModuleState.STOPPING

        # Create shutdown coordinator for ACK-based unassignment
        self._shutdown_coordinator = ShutdownCoordinator()

        try:
            # Phase 1: Request device unassignment with ACK
            unassign_timeout = min(3.0, timeout * 0.3)
            self.logger.debug("Phase 1: Requesting device unassignment (timeout=%.1fs)", unassign_timeout)

            try:
                acknowledged, ack_data = await self._shutdown_coordinator.request_device_unassign(
                    send_func=self.send_command,
                    timeout=unassign_timeout,
                    instance_id=self.instance_id or self.module_info.name,
                )
                if acknowledged:
                    port_released = ack_data.get("port_released", False) if ack_data else False
                    self.logger.info("Device unassignment confirmed (port_released=%s)", port_released)
                else:
                    self.logger.warning("Device unassign not acknowledged, continuing shutdown")
            except Exception as e:
                self.logger.warning("Error during device unassign: %s", e)

            # Phase 2: Send quit command
            self.logger.debug("Phase 2: Sending quit command")
            try:
                await self.send_command(CommandMessage.quit())
            except Exception as e:
                self.logger.warning("Error sending quit command: %s", e)

            # Phase 3: Wait for graceful exit
            quit_timeout = timeout - unassign_timeout - 2.0  # Reserve time for SIGTERM
            quit_timeout = max(quit_timeout, 2.0)
            self.logger.debug("Phase 3: Waiting for graceful exit (timeout=%.1fs)", quit_timeout)

            try:
                await asyncio.wait_for(self.process.wait(), timeout=quit_timeout)
                self.logger.info("Process stopped gracefully")
            except asyncio.TimeoutError:
                # Phase 4: SIGTERM
                self.logger.warning("Process did not exit gracefully, sending SIGTERM")
                self._was_forcefully_stopped = True
                self.process.terminate()

                try:
                    await asyncio.wait_for(self.process.wait(), timeout=2.0)
                    self.logger.info("Process terminated after SIGTERM")
                except asyncio.TimeoutError:
                    # Phase 5: SIGKILL
                    self.logger.error("Process did not terminate, sending SIGKILL")
                    self.process.kill()
                    await self.process.wait()
                    self.logger.info("Process killed")

        except Exception as e:
            self.logger.error("Error stopping process: %s", e, exc_info=True)
            self._was_forcefully_stopped = True
        finally:
            self.shutdown_event.set()
            await self._cleanup_reader_tasks()
            self._shutdown_coordinator = None
            self.process = None
            self.state = ModuleState.STOPPED
            self.logger.info("Module stopped: %s", self.module_info.name)

    async def _cleanup_reader_tasks(self) -> None:
        """Clean up reader tasks with proper error handling."""
        for task in [self.stdout_task, self.stderr_task, self.monitor_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=1.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
                except Exception as e:
                    self.logger.debug("Error cleaning up task: %s", e)

    async def kill(self) -> None:
        """Force kill the module process without graceful shutdown."""
        if self.process is None:
            self.logger.debug("Process not running")
            return

        self.logger.warning("Force killing module: %s", self.module_info.name)
        self.state = ModuleState.STOPPING
        self._was_forcefully_stopped = True

        try:
            self.process.kill()
            await self.process.wait()
        except Exception as e:
            self.logger.error("Error killing process: %s", e)
        finally:
            self.shutdown_event.set()
            await self._cleanup_reader_tasks()
            self.process = None
            self.state = ModuleState.STOPPED
            self.logger.info("Module killed: %s", self.module_info.name)

    def get_state(self) -> ModuleState:
        return self.state

    def is_running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    @property
    def was_forcefully_stopped(self) -> bool:
        return self._was_forcefully_stopped

    def is_initialized(self) -> bool:
        return self.state in (ModuleState.IDLE, ModuleState.RECORDING)

    def is_recording(self) -> bool:
        return self.state == ModuleState.RECORDING

    def get_error_message(self) -> Optional[str]:
        return self.error_message

    async def _update_enabled_state(self, enabled: bool) -> None:
        try:
            config_path = self.module_info.config_path
            if config_path:
                config_manager = get_config_manager()
                success = await config_manager.write_config_async(config_path, {'enabled': enabled})
                if success:
                    self.logger.info("Updated enabled state to %s in config", enabled)
                else:
                    self.logger.warning("Failed to update enabled state in config")
            else:
                self.logger.warning("No config path available to update enabled state")

        except Exception as e:
            self.logger.error("Error updating enabled state: %s", e, exc_info=True)

    async def load_module_config(self) -> dict:
        if not self.module_info.config_path:
            self.logger.debug("No config file for module %s", self.module_info.name)
            return {}

        config_manager = get_config_manager()
        return await config_manager.read_config_async(self.module_info.config_path)

    async def get_enabled_state(self) -> bool:
        config = await self.load_module_config()
        config_manager = get_config_manager()
        return config_manager.get_bool(config, 'enabled', default=True)

    async def update_enabled_state(self, enabled: bool) -> bool:
        if not self.module_info.config_path:
            self.logger.warning("No config file to update enabled state")
            return False

        config_manager = get_config_manager()
        return await config_manager.write_config_async(
            self.module_info.config_path,
            {'enabled': enabled}
        )
