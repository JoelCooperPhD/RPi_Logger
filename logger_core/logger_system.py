
import asyncio
import datetime
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Callable

from .module_discovery import ModuleInfo, discover_modules
from .module_process import ModuleProcess, ModuleState
from .commands import StatusMessage, CommandMessage
from .window_manager import WindowManager, WindowGeometry
from .config_manager import get_config_manager


class LoggerSystem:
    def __init__(
        self,
        session_dir: Path,
        session_prefix: str = "session",
        log_level: str = "info",
        ui_callback: Optional[Callable] = None,
    ):
        self.logger = logging.getLogger("LoggerSystem")
        self.session_dir = Path(session_dir)
        self.session_prefix = session_prefix
        self.log_level = log_level
        self.ui_callback = ui_callback

        self.available_modules: List[ModuleInfo] = []
        self.selected_modules: Set[str] = set()
        self.module_processes: Dict[str, ModuleProcess] = {}

        self.window_manager = WindowManager()
        self.config_manager = get_config_manager()

        self.recording = False
        self.shutdown_event = asyncio.Event()

        self._discover_modules()
        self._load_enabled_modules()

    def _discover_modules(self) -> None:
        self.logger.info("Discovering modules...")
        self.available_modules = discover_modules()
        self.logger.info("Found %d modules: %s",
                        len(self.available_modules),
                        [m.name for m in self.available_modules])

    def _load_enabled_modules(self) -> None:
        self.selected_modules.clear()

        state_file = Path(__file__).parent.parent / "data" / "running_modules.json"
        running_modules_from_last_session = None

        if state_file.exists():
            try:
                with open(state_file, 'r') as f:
                    state = json.load(f)
                    running_modules_from_last_session = set(state.get('running_modules', []))
                    self.logger.info("Loaded running modules from last session: %s", running_modules_from_last_session)
                    # Delete the state file after reading it (one-time use)
                    state_file.unlink()
            except Exception as e:
                self.logger.error("Failed to load running modules state: %s", e)

        if running_modules_from_last_session:
            for module_name in running_modules_from_last_session:
                if any(m.name == module_name for m in self.available_modules):
                    self.selected_modules.add(module_name)
                    self.logger.info("Module %s will be restored from last session", module_name)
                else:
                    self.logger.warning("Module %s from last session not found", module_name)
        else:
            for module_info in self.available_modules:
                if not module_info.config_path:
                    self.selected_modules.add(module_info.name)
                    self.logger.debug("Module %s has no config, defaulting to enabled", module_info.name)
                    continue

                config = self.config_manager.read_config(module_info.config_path)
                enabled = self.config_manager.get_bool(config, 'enabled', default=True)

                if enabled:
                    self.selected_modules.add(module_info.name)
                    self.logger.info("Module %s enabled in config", module_info.name)
                else:
                    self.logger.info("Module %s disabled in config", module_info.name)

    def get_available_modules(self) -> List[ModuleInfo]:
        return self.available_modules

    def select_module(self, module_name: str) -> bool:
        if not any(m.name == module_name for m in self.available_modules):
            self.logger.warning("Module not found: %s", module_name)
            return False

        self.selected_modules.add(module_name)
        self.logger.info("Selected module: %s", module_name)
        return True

    def deselect_module(self, module_name: str) -> None:
        self.selected_modules.discard(module_name)
        self.logger.info("Deselected module: %s", module_name)

    def get_selected_modules(self) -> List[str]:
        return list(self.selected_modules)

    def is_module_selected(self, module_name: str) -> bool:
        return module_name in self.selected_modules

    def toggle_module_enabled(self, module_name: str, enabled: bool) -> bool:
        module_info = next(
            (m for m in self.available_modules if m.name == module_name),
            None
        )
        if not module_info or not module_info.config_path:
            self.logger.warning("Cannot update enabled state - no config for %s", module_name)
            return False

        success = self.config_manager.write_config(
            module_info.config_path,
            {'enabled': enabled}
        )

        if success:
            self.logger.info("Updated %s enabled state to %s", module_name, enabled)
        else:
            self.logger.error("Failed to update %s enabled state", module_name)

        return success

    def is_module_running(self, module_name: str) -> bool:
        process = self.module_processes.get(module_name)
        return process is not None and process.is_running()

    async def start_module(self, module_name: str) -> bool:
        if module_name in self.module_processes:
            process = self.module_processes[module_name]

            if process.is_running():
                self.logger.info("Module %s still running, waiting for stop to complete...", module_name)

                for _ in range(50):  # 50 * 0.1s = 5s
                    if not process.is_running():
                        break
                    await asyncio.sleep(0.1)

                # If still running after timeout, force stop
                if process.is_running():
                    self.logger.warning("Module %s still running after timeout, forcing stop", module_name)
                    await process.stop()
                    await asyncio.sleep(0.5)

            self.module_processes.pop(module_name, None)
            self.selected_modules.discard(module_name)

        module_info = next(
            (m for m in self.available_modules if m.name == module_name),
            None
        )
        if not module_info:
            self.logger.error("Module info not found: %s", module_name)
            return False

        module_dir = self.session_dir / module_name
        module_dir.mkdir(parents=True, exist_ok=True)
        self.logger.info("Created module directory: %s", module_dir)

        window_geometry = None
        self.logger.info("=" * 60)
        self.logger.info("GEOMETRY_LOAD: Loading geometry for %s", module_name)
        if module_info.config_path:
            self.logger.info("GEOMETRY_LOAD: Config path: %s", module_info.config_path)
            config = self.config_manager.read_config(module_info.config_path)
            x = self.config_manager.get_int(config, 'window_x', default=None)
            y = self.config_manager.get_int(config, 'window_y', default=None)
            width = self.config_manager.get_int(config, 'window_width', default=None)
            height = self.config_manager.get_int(config, 'window_height', default=None)

            self.logger.info("GEOMETRY_LOAD: Read from config: x=%s, y=%s, width=%s, height=%s", x, y, width, height)

            if all(v is not None for v in [x, y, width, height]):
                window_geometry = WindowGeometry(x=x, y=y, width=width, height=height)
                self.logger.info("GEOMETRY_LOAD: ✓ Using saved geometry: %s", window_geometry.to_geometry_string())
            else:
                self.logger.info("GEOMETRY_LOAD: ✗ Incomplete geometry data, using defaults")
        else:
            self.logger.info("GEOMETRY_LOAD: No config path available")
        self.logger.info("=" * 60)

        process = ModuleProcess(
            module_info,
            module_dir,
            session_prefix=self.session_prefix,
            status_callback=self._module_status_callback,
            log_level=self.log_level,
            window_geometry=window_geometry,
        )

        try:
            success = await process.start()
            if success:
                self.module_processes[module_name] = process
                self.selected_modules.add(module_name)
                self.logger.info("Module %s started successfully", module_name)
            else:
                self.logger.error("Module %s failed to start", module_name)
            return success
        except Exception as e:
            self.logger.error("Exception starting %s: %s", module_name, e, exc_info=True)
            return False

    async def stop_module(self, module_name: str) -> bool:
        process = self.module_processes.get(module_name)
        if not process:
            self.logger.warning("Module %s not found in processes", module_name)
            return False

        if not process.is_running():
            self.logger.warning("Module %s not running", module_name)
            self.module_processes.pop(module_name, None)
            self.selected_modules.discard(module_name)
            return True

        try:
            if process.is_recording():
                await process.stop_recording()
                await asyncio.sleep(0.5)  # Give it time to stop recording

            await process.stop()

            self.module_processes.pop(module_name, None)
            self.selected_modules.discard(module_name)

            self.logger.info("Module %s stopped successfully", module_name)
            return True
        except Exception as e:
            self.logger.error("Error stopping %s: %s", module_name, e, exc_info=True)
            return False

    async def _module_status_callback(self, process: ModuleProcess, status: Optional[StatusMessage]) -> None:
        module_name = process.module_info.name

        if status:
            self.logger.info("Module %s status: %s", module_name, status.get_status_type())

            if status.get_status_type() == "recording_started":
                self.logger.info("Module %s started recording", module_name)
            elif status.get_status_type() == "recording_stopped":
                self.logger.info("Module %s stopped recording", module_name)
            elif status.is_error():
                self.logger.error("Module %s error: %s",
                                module_name,
                                status.get_error_message())

        if self.ui_callback:
            try:
                await self.ui_callback(module_name, process.get_state(), status)
            except Exception as e:
                self.logger.error("UI callback error: %s", e)

    async def start_all(self) -> Dict[str, bool]:
        self.logger.info("Starting all selected modules: %s", self.selected_modules)

        if not self.selected_modules:
            self.logger.warning("No modules selected")
            return {}

        results = {}

        for module_name in self.selected_modules:
            module_dir = self.session_dir / module_name
            module_dir.mkdir(parents=True, exist_ok=True)
            self.logger.info("Created module directory: %s", module_dir)

        saved_geometries: Dict[str, WindowGeometry] = {}
        modules_needing_tiling: List[str] = []

        for module_name in self.selected_modules:
            module_info = next(
                (m for m in self.available_modules if m.name == module_name),
                None
            )
            if not module_info or not module_info.config_path:
                modules_needing_tiling.append(module_name)
                continue

            config = self.config_manager.read_config(module_info.config_path)
            x = self.config_manager.get_int(config, 'window_x', default=0)
            y = self.config_manager.get_int(config, 'window_y', default=0)
            width = self.config_manager.get_int(config, 'window_width', default=800)
            height = self.config_manager.get_int(config, 'window_height', default=600)

            if x != 0 or y != 0:
                saved_geometries[module_name] = WindowGeometry(x=x, y=y, width=width, height=height)
                self.logger.info("Using saved geometry for %s", module_name)
            else:
                modules_needing_tiling.append(module_name)

        tiling_geometries: Dict[str, WindowGeometry] = {}
        if modules_needing_tiling:
            self.logger.info("Calculating tiling layout for %d modules", len(modules_needing_tiling))
            tiling_layout = self.window_manager.calculate_tiling_layout(
                len(modules_needing_tiling),
                saved_geometries=saved_geometries
            )
            for idx, module_name in enumerate(modules_needing_tiling):
                tiling_geometries[module_name] = tiling_layout.get(str(idx))

        start_tasks = []

        for module_name in self.selected_modules:
            module_info = next(
                (m for m in self.available_modules if m.name == module_name),
                None
            )
            if not module_info:
                self.logger.error("Module info not found: %s", module_name)
                results[module_name] = False
                continue

            window_geometry = saved_geometries.get(module_name) or tiling_geometries.get(module_name)

            module_dir = self.session_dir / module_name
            process = ModuleProcess(
                module_info,
                module_dir,
                session_prefix=self.session_prefix,
                status_callback=self._module_status_callback,
                log_level=self.log_level,
                window_geometry=window_geometry,
            )

            self.module_processes[module_name] = process

            start_tasks.append(self._start_module(module_name, process))

        start_results = await asyncio.gather(*start_tasks, return_exceptions=True)

        for module_name, result in zip(self.selected_modules, start_results):
            if isinstance(result, Exception):
                self.logger.error("Failed to start %s: %s", module_name, result)
                results[module_name] = False
            else:
                results[module_name] = result

        self.logger.info("Waiting for modules to initialize...")
        await asyncio.sleep(2.0)  # Give modules time to initialize

        success_count = sum(1 for v in results.values() if v)
        self.logger.info("Started %d/%d modules", success_count, len(results))

        return results

    async def _start_module(self, module_name: str, process: ModuleProcess) -> bool:
        try:
            success = await process.start()
            if success:
                self.logger.info("Module %s started", module_name)
            else:
                self.logger.error("Module %s failed to start", module_name)
            return success
        except Exception as e:
            self.logger.error("Exception starting %s: %s", module_name, e, exc_info=True)
            return False

    async def start_recording_all(self) -> Dict[str, bool]:
        self.logger.info("Starting recording on all modules")

        if self.recording:
            self.logger.warning("Already recording")
            return {}

        results = {}

        tasks = []
        for module_name, process in self.module_processes.items():
            if process.is_running():
                tasks.append(self._start_recording_module(module_name, process))
            else:
                self.logger.warning("Module %s not running, skipping", module_name)
                results[module_name] = False

        if tasks:
            task_results = await asyncio.gather(*tasks, return_exceptions=True)
            for module_name, result in zip(self.module_processes.keys(), task_results):
                if isinstance(result, Exception):
                    self.logger.error("Error starting recording for %s: %s",
                                    module_name, result)
                    results[module_name] = False
                else:
                    results[module_name] = result

        self.recording = True
        return results

    async def _start_recording_module(self, module_name: str, process: ModuleProcess) -> bool:
        try:
            await process.start_recording()
            self.logger.info("Sent start_recording to %s", module_name)
            return True
        except Exception as e:
            self.logger.error("Error starting recording for %s: %s", module_name, e)
            return False

    async def stop_recording_all(self) -> Dict[str, bool]:
        self.logger.info("Stopping recording on all modules")

        if not self.recording:
            self.logger.warning("Not recording")
            return {}

        results = {}

        tasks = []
        for module_name, process in self.module_processes.items():
            if process.is_running():
                tasks.append(self._stop_recording_module(module_name, process))
            else:
                results[module_name] = False

        if tasks:
            task_results = await asyncio.gather(*tasks, return_exceptions=True)
            for module_name, result in zip(self.module_processes.keys(), task_results):
                if isinstance(result, Exception):
                    self.logger.error("Error stopping recording for %s: %s",
                                    module_name, result)
                    results[module_name] = False
                else:
                    results[module_name] = result

        self.recording = False
        return results

    async def _stop_recording_module(self, module_name: str, process: ModuleProcess) -> bool:
        try:
            await process.stop_recording()
            self.logger.info("Sent stop_recording to %s", module_name)
            return True
        except Exception as e:
            self.logger.error("Error stopping recording for %s: %s", module_name, e)
            return False

    async def get_status_all(self) -> Dict[str, ModuleState]:
        results = {}

        for module_name, process in self.module_processes.items():
            if process.is_running():
                try:
                    await process.get_status()
                    results[module_name] = process.get_state()
                except Exception as e:
                    self.logger.error("Error getting status from %s: %s",
                                    module_name, e)
                    results[module_name] = ModuleState.ERROR
            else:
                results[module_name] = process.get_state()

        return results

    async def stop_all(self) -> None:
        self.logger.info("Stopping all modules")

        if self.recording:
            await self.stop_recording_all()
            await asyncio.sleep(1.0)

        # Request geometry from all running modules BEFORE shutting them down
        await self._request_geometries_from_all()

        stop_tasks = []
        for module_name, process in self.module_processes.items():
            if process.is_running():
                stop_tasks.append(self._stop_module(module_name, process))

        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)

        self.module_processes.clear()
        self.logger.info("All modules stopped")

    async def _request_geometries_from_all(self) -> None:
        self.logger.info("Requesting geometry from all running modules...")

        get_geometry_tasks = []
        for module_name, process in self.module_processes.items():
            if process.is_running():
                async def request_geometry(name: str, proc: ModuleProcess):
                    try:
                        await proc.send_command(CommandMessage.get_geometry())
                        self.logger.debug("Requested geometry from %s", name)
                    except Exception as e:
                        self.logger.warning("Failed to request geometry from %s: %s", name, e)

                get_geometry_tasks.append(request_geometry(module_name, process))

        if get_geometry_tasks:
            await asyncio.gather(*get_geometry_tasks, return_exceptions=True)
            await asyncio.sleep(0.3)

    async def _stop_module(self, module_name: str, process: ModuleProcess) -> None:
        try:
            await process.stop()
            self.logger.info("Module %s stopped", module_name)
        except Exception as e:
            self.logger.error("Error stopping %s: %s", module_name, e)

    def get_module_state(self, module_name: str) -> Optional[ModuleState]:
        process = self.module_processes.get(module_name)
        if process:
            return process.get_state()
        return None

    def is_any_recording(self) -> bool:
        return any(p.is_recording() for p in self.module_processes.values())

    def get_session_info(self) -> dict:
        return {
            "session_dir": str(self.session_dir),
            "session_name": self.session_dir.name,
            "recording": self.recording,
            "selected_modules": list(self.selected_modules),
            "running_modules": [
                name for name, proc in self.module_processes.items()
                if proc.is_running()
            ],
        }

    async def save_running_modules_state(self) -> bool:
        try:
            running_modules = [
                name for name, process in self.module_processes.items()
                if process.is_running()
            ]

            if not running_modules:
                self.logger.info("No running modules to save")
                return True

            state_file = Path(__file__).parent.parent / "data" / "running_modules.json"
            await asyncio.to_thread(state_file.parent.mkdir, parents=True, exist_ok=True)

            state = {
                'timestamp': datetime.datetime.now().isoformat(),
                'running_modules': running_modules,
            }

            # Offload JSON file write to thread pool to avoid blocking
            def write_json():
                with open(state_file, 'w') as f:
                    json.dump(state, f, indent=2)

            await asyncio.to_thread(write_json)

            self.logger.info("Saved running modules state: %s", running_modules)
            return True

        except Exception as e:
            self.logger.error("Failed to save running modules state: %s", e, exc_info=True)
            return False

    async def cleanup(self) -> None:
        self.logger.info("Cleaning up logger system")
        await self.stop_all()
        self.shutdown_event.set()
