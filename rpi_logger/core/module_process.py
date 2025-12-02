
import asyncio
from rpi_logger.core.logging_utils import get_module_logger
import sys
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from .commands import CommandMessage, StatusMessage, StatusType
from .module_discovery import ModuleInfo
from .config_manager import get_config_manager
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
    ):
        self.module_info = module_info
        self.output_dir = Path(output_dir)
        self.session_prefix = session_prefix
        self.status_callback = status_callback
        self.log_level = log_level
        self.window_geometry = window_geometry

        self.logger = get_module_logger(f"ModuleProcess.{module_info.name}")

        self.process: Optional[asyncio.subprocess.Process] = None
        self.state = ModuleState.STOPPED
        self.last_status = None
        self.error_message = None

        self.stdout_task: Optional[asyncio.Task] = None
        self.stderr_task: Optional[asyncio.Task] = None
        self.monitor_task: Optional[asyncio.Task] = None

        self.command_queue: asyncio.Queue = asyncio.Queue()

        self.shutdown_event = asyncio.Event()
        self._was_forcefully_stopped = False

    async def start(self) -> bool:
        if self.process is not None:
            self.logger.warning("Process already running")
            return False

        self.logger.info("Starting module: %s", self.module_info.name)
        self.state = ModuleState.STARTING

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)

            mode = await self._determine_start_mode()

            base_args = [
                "--mode", mode,
                "--output-dir", str(self.output_dir),
                "--session-prefix", self.session_prefix,
                "--log-level", self.log_level,
                "--no-console",
                "--enable-commands",
            ]

            if self.window_geometry and mode == "gui":
                geometry_str = gui_utils.build_geometry_string_from_normalized(
                    self.window_geometry.width,
                    self.window_geometry.height,
                    self.window_geometry.x,
                    self.window_geometry.y,
                )
                base_args.extend([
                    "--window-geometry", geometry_str
                ])

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

    async def _determine_start_mode(self) -> str:
        """Determine which --mode argument to pass when launching the module.

        Currently only the DRT module overrides the default GUI mode, so we keep
        the logic scoped to DRT to avoid impacting other modules.
        """
        if self.module_info.name != "DRT":
            return "gui"

        config = await self.load_module_config()
        if not config:
            return "gui"

        mode = config.get('default_mode', '').strip().lower()
        if not mode:
            return "gui"

        return mode

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

                line_str = line.decode().strip()
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

                line_str = line.decode().strip()
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

        if status_type == "initialized":
            self.state = ModuleState.IDLE
        elif status_type == "recording_started":
            self.state = ModuleState.RECORDING
        elif status_type == "recording_stopped":
            self.state = ModuleState.IDLE
        elif status_type == StatusType.GEOMETRY_CHANGED:
            await self._save_geometry(status.get_payload())
        elif status_type == "error":
            self.state = ModuleState.ERROR
            self.error_message = status.get_error_message()
        elif status_type == "quitting":
            self.state = ModuleState.STOPPED
            # This prevents _process_monitor() from marking it as CRASHED
            self.shutdown_event.set()
            self._was_forcefully_stopped = False
            await self._update_enabled_state(False)

        if self.status_callback:
            try:
                await self.status_callback(self, status)
            except Exception as e:
                self.logger.error("Status callback error: %s", e)

    async def send_command(self, command: str) -> None:
        if self.state in (ModuleState.STOPPED, ModuleState.CRASHED):
            self.logger.warning("Cannot send command - process not running")
            return

        await self.command_queue.put(command)

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

    async def stop(self, timeout: float = 10.0) -> None:
        if self.process is None:
            self.logger.debug("Process not running")
            return

        self.logger.info("Stopping module: %s", self.module_info.name)
        self.state = ModuleState.STOPPING

        try:
            await self.send_command(CommandMessage.quit())

            try:
                await asyncio.wait_for(self.process.wait(), timeout=timeout)
                self.logger.info("Process stopped gracefully")
            except asyncio.TimeoutError:
                self.logger.warning("Process did not exit gracefully, terminating...")
                self._was_forcefully_stopped = True
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    self.logger.error("Process did not terminate, killing...")
                    self._was_forcefully_stopped = True
                    self.process.kill()
                    await self.process.wait()

        except Exception as e:
            self.logger.error("Error stopping process: %s", e)
            self._was_forcefully_stopped = True
        finally:
            self.shutdown_event.set()
            for task in [self.stdout_task, self.stderr_task, self.monitor_task]:
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

            self.process = None
            self.state = ModuleState.STOPPED
            self.logger.info("Module stopped: %s", self.module_info.name)

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

    async def _save_geometry(self, payload: dict) -> None:
        try:
            self.logger.info("=" * 60)
            self.logger.info("GEOMETRY_SAVE (parent): Received geometry from module %s", self.module_info.name)
            self.logger.info("GEOMETRY_SAVE (parent): Payload: %s", payload)

            x = payload.get('x', 0)
            y = payload.get('y', 0)
            width = payload.get('width', 800)
            height = payload.get('height', 600)

            self.logger.info("GEOMETRY_SAVE (parent): Parsed: x=%d, y=%d, width=%d, height=%d", x, y, width, height)

            config_path = self.module_info.config_path
            if config_path:
                self.logger.info("GEOMETRY_SAVE (parent): Config path: %s", config_path)
                config_manager = get_config_manager()
                updates = {
                    'window_x': x,
                    'window_y': y,
                    'window_width': width,
                    'window_height': height,
                    'window_geometry': gui_utils.build_geometry_string_from_normalized(width, height, x, y),
                }
                self.logger.info("GEOMETRY_SAVE (parent): Writing updates: %s", updates)
                success = config_manager.write_config(config_path, updates)
                if success:
                    self.logger.info("GEOMETRY_SAVE (parent): ✓ Saved geometry: %dx%d+%d+%d", width, height, x, y)
                else:
                    self.logger.warning("GEOMETRY_SAVE (parent): ✗ Failed to save geometry to config")
            else:
                self.logger.warning("GEOMETRY_SAVE (parent): ✗ No config path available to save geometry")

            self.logger.info("=" * 60)

        except Exception as e:
            self.logger.error("GEOMETRY_SAVE (parent): Error saving geometry: %s", e, exc_info=True)

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

    async def load_window_geometry(self) -> Optional[WindowGeometry]:
        config = await self.load_module_config()
        if not config:
            return None

        config_manager = get_config_manager()
        x = config_manager.get_int(config, 'window_x', default=0)
        y = config_manager.get_int(config, 'window_y', default=0)
        width = config_manager.get_int(config, 'window_width', default=800)
        height = config_manager.get_int(config, 'window_height', default=600)

        if x != 0 or y != 0:
            return WindowGeometry(x=x, y=y, width=width, height=height)

        return None
