"""Textual dashboard for the RPi Logger modules."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Dict, Optional

from rich.table import Table

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    Log,
    Static,
)

from ui.backend import (
    AudioRecorderService,
    BaseModuleService,
    CameraProcessService,
    DashboardBackend,
    ModuleLog,
    ModuleState,
    ModuleStatus,
)


STATE_CLASS_MAP = {
    ModuleState.OFFLINE: "state-offline",
    ModuleState.STARTING: "state-starting",
    ModuleState.RECONNECTING: "state-reconnecting",
    ModuleState.READY: "state-ready",
    ModuleState.RECORDING: "state-recording",
    ModuleState.ERROR: "state-error",
}

LOG_LEVEL_COLOURS = {
    "debug": "#7d7f8a",
    "info": "#9ad8ff",
    "warning": "#ffcc6f",
    "error": "#ff7a7a",
    "critical": "#ff4d4d",
}


class ModuleCard(Static):
    """Compact summary card rendered inside the module list."""

    module_name: str

    def __init__(self, module_name: str) -> None:
        super().__init__(classes="module-card")
        self.module_name = module_name
        self.state_label = Label("OFFLINE", classes="card-state")
        self.summary_label = Label("Module idle", classes="card-summary")

    def compose(self) -> ComposeResult:
        yield Label(self.module_name.title(), classes="card-title")
        yield self.state_label
        yield self.summary_label

    def update_status(self, status: ModuleStatus) -> None:
        for class_name in STATE_CLASS_MAP.values():
            self.remove_class(class_name)
        self.add_class(STATE_CLASS_MAP.get(status.state, ""))
        self.state_label.update(status.state.value.upper())
        summary = status.summary or "Awaiting update"
        self.summary_label.update(summary)


class ModuleDetailPanel(Static):
    """Detailed view of the currently selected module."""

    def __init__(self) -> None:
        super().__init__(id="module-detail")
        self.module_name: Optional[str] = None
        self.name_label = Label("Select a module", classes="detail-title")
        self.state_chip = Label("OFFLINE", classes="detail-chip")
        self.summary_label = Label("", classes="detail-summary")
        self.detail_view = Static("", classes="detail-table")
        self.buttons: Dict[str, Button] = {}

    def compose(self) -> ComposeResult:
        with Container(classes="detail-header"):
            yield self.name_label
            yield self.state_chip
            yield self.summary_label
        with Horizontal(classes="detail-actions"):
            self.buttons["start"] = Button("Start Module", id="btn-start", variant="success")
            self.buttons["stop"] = Button("Stop Module", id="btn-stop", variant="warning")
            self.buttons["record"] = Button("Start Recording", id="btn-record", variant="primary")
            self.buttons["stop_record"] = Button("Stop Recording", id="btn-stop-record", variant="error")
            for button in self.buttons.values():
                yield button
        yield self.detail_view

    def update_status(self, status: ModuleStatus) -> None:
        self.module_name = status.name
        self.name_label.update(status.name.replace("_", " ").title())
        self.state_chip.update(status.state.value.upper())
        for class_name in STATE_CLASS_MAP.values():
            self.state_chip.remove_class(class_name)
        self.state_chip.add_class(STATE_CLASS_MAP.get(status.state, ""))

        summary = status.summary or "Awaiting status"
        self.summary_label.update(summary)

        table = Table.grid(padding=(0, 1))
        table.add_column("Key", style="bold #9ad8ff")
        table.add_column("Value", style="#e1e5f2")
        for key, value in sorted(status.details.items()):
            pretty = self._format_value(value)
            table.add_row(str(key), pretty)
        if not status.details:
            table.add_row("status", "No details reported yet")
        self.detail_view.update(table)

        is_running = status.state in {
            ModuleState.STARTING,
            ModuleState.RECONNECTING,
            ModuleState.READY,
            ModuleState.RECORDING,
        }
        self.buttons["start"].disabled = is_running
        self.buttons["stop"].disabled = not is_running
        self.buttons["record"].disabled = status.recording or not is_running
        self.buttons["stop_record"].disabled = not status.recording

    def _format_value(self, value: object) -> str:
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(item) for item in value) or "—"
        if value is None:
            return "—"
        return str(value)

    def clear(self) -> None:
        self.module_name = None
        self.name_label.update("Select a module")
        self.state_chip.update("—")
        self.summary_label.update("Use the list to choose a module")
        self.detail_view.update("")
        for button in self.buttons.values():
            button.disabled = True


class DeviceSelectScreen(ModalScreen[Optional[set[int]]]):
    """Modal for choosing active audio devices."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, devices: Dict[int, Dict[str, object]], selected: set[int]) -> None:
        super().__init__()
        self.devices = devices
        self.selected = set(selected)

    def compose(self) -> ComposeResult:
        with Container(id="device-modal"):
            yield Label("Select microphones", classes="modal-title")
            with Vertical(id="device-list"):
                for device_id, info in sorted(self.devices.items()):
                    name = info.get("name", f"Device {device_id}")
                    channels = info.get("channels", "?")
                    rate = info.get("sample_rate", "?")
                    label = f"{device_id}: {name} ({channels} ch @ {rate} Hz)"
                    yield Checkbox(label, value=device_id in self.selected, id=f"device-{device_id}")
            with Horizontal(id="device-actions"):
                yield Button("Cancel", id="device-cancel", variant="default")
                yield Button("Save", id="device-save", variant="primary")

    def on_mount(self) -> None:
        first_checkbox = self.query_one(Checkbox)
        self.set_focus(first_checkbox)

    async def action_cancel(self) -> None:  # type: ignore[override]
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:  # type: ignore[override]
        if event.button.id == "device-cancel":
            self.dismiss(None)
        elif event.button.id == "device-save":
            selections = {
                int(checkbox.id.split("-")[1])
                for checkbox in self.query(Checkbox)
                if checkbox.value
            }
            self.dismiss(selections)


@dataclass
class ModuleContext:
    name: str
    service: BaseModuleService
    card: ModuleCard


class RPiLoggerDashboard(App):
    """High-contrast dashboard for monitoring the logger modules."""

    CSS_PATH = "dashboard.css"
    TITLE = "RPi Logger Control Center"
    SUB_TITLE = "Async device orchestration"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("s", "start_module", "Start"),
        Binding("x", "stop_module", "Stop"),
        Binding("space", "toggle_recording", "Rec/Stop"),
        Binding("r", "refresh_module", "Refresh"),
        Binding("d", "manage_devices", "Audio Devices"),
        Binding("ctrl+l", "clear_logs", "Clear Logs", show=False),
    ]

    selected_module = reactive[Optional[str]](None)

    def __init__(self, backend: Optional[DashboardBackend] = None) -> None:
        super().__init__()
        self.backend = backend or DashboardBackend()
        self.modules: Dict[str, ModuleContext] = {}
        self.status_cache: Dict[str, ModuleStatus] = {}
        self.status_task: Optional[asyncio.Task[None]] = None
        self.log_task: Optional[asyncio.Task[None]] = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="dashboard"):
            yield ListView(id="module-list")
            with Container(id="content"):
                yield ModuleDetailPanel()
                yield Log(id="module-log", highlight=True)
        yield Footer()

    async def on_mount(self) -> None:
        list_view = self.query_one("#module-list", ListView)
        detail_panel = self.query_one(ModuleDetailPanel)
        log_widget = self.query_one(Log)
        log_widget.write_line("Awaiting module activity…")

        await self.backend.setup()
        for name, service in self.backend.modules.items():
            card = ModuleCard(name)
            item = ListItem(card)
            list_view.append(item)
            self.modules[name] = ModuleContext(name=name, service=service, card=card)

        if list_view.children:
            list_view.index = 0
            first_card = list_view.children[0].query_one(ModuleCard)
            self.selected_module = first_card.module_name
        else:
            detail_panel.clear()

        self.status_task = self.create_background_task(self._consume_status_updates())
        self.log_task = self.create_background_task(self._consume_logs())

        # Start audio monitor by default for quicker feedback
        audio_service = self.backend.audio
        try:
            await audio_service.start()
        except Exception as exc:  # pragma: no cover - defensive logging
            self.notify(f"Audio monitor failed to start: {exc}", severity="error")

    async def on_unmount(self) -> None:
        for task in (self.status_task, self.log_task):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        await self.backend.shutdown()

    async def _consume_status_updates(self) -> None:
        while True:
            status = await self.backend.supervisor.status_queue.get()
            self.status_cache[status.name] = status
            context = self.modules.get(status.name)
            if context:
                context.card.update_status(status)
            if self.selected_module == status.name:
                detail_panel = self.query_one(ModuleDetailPanel)
                detail_panel.update_status(status)

    async def _consume_logs(self) -> None:
        log_widget = self.query_one(Log)
        while True:
            log = await self.backend.supervisor.log_queue.get()
            colour = LOG_LEVEL_COLOURS.get(log.level.lower(), "#9ad8ff")
            rendered = f"[{colour}]{log.name.upper():>10}[/] │ {log.message}"
            log_widget.write_line(rendered)
            log_widget.scroll_end(animate=False)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        card = event.item.query_one(ModuleCard)
        self.selected_module = card.module_name
        status = self.status_cache.get(card.module_name)
        detail_panel = self.query_one(ModuleDetailPanel)
        if status:
            detail_panel.update_status(status)
        else:
            detail_panel.clear()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_map = {
            "btn-start": self.action_start_module,
            "btn-stop": self.action_stop_module,
            "btn-record": self.action_toggle_recording,
            "btn-stop-record": self.action_toggle_recording,
        }
        handler = button_map.get(event.button.id)
        if handler:
            self.create_background_task(handler())

    async def action_start_module(self) -> None:
        service = self._current_service()
        if not service:
            return
        try:
            await service.start()
            self.notify(f"Started {service.name}")
        except Exception as exc:
            self.notify(f"Failed to start {service.name}: {exc}", severity="error")

    async def action_stop_module(self) -> None:
        service = self._current_service()
        if not service:
            return
        try:
            await service.stop()
            self.notify(f"Stopped {service.name}")
        except Exception as exc:
            self.notify(f"Failed to stop {service.name}: {exc}", severity="error")

    async def action_toggle_recording(self) -> None:
        service = self._current_service()
        if not service:
            return
        try:
            status = self.status_cache.get(service.name)
            if status and status.recording:
                await service.stop_recording()
                self.notify(f"Stopped recording on {service.name}")
            else:
                await service.start_recording()
                self.notify(f"Started recording on {service.name}")
        except Exception as exc:
            self.notify(f"Recording toggle failed: {exc}", severity="error")

    async def action_refresh_module(self) -> None:
        service = self._current_service()
        if not service:
            return
        try:
            refresh = getattr(service, "refresh", None)
            if callable(refresh):
                await refresh()
                self.notify(f"Refreshed {service.name}", severity="information")
            else:
                self.notify("Module does not support refresh", severity="warning")
        except Exception as exc:
            self.notify(f"Refresh failed: {exc}", severity="error")

    async def action_manage_devices(self) -> None:
        service = self._current_service()
        if not isinstance(service, AudioRecorderService):
            self.notify("Audio device selection is only available for the audio module", severity="warning")
            return
        await service.refresh()
        devices = dict(service.available_devices)
        if not devices:
            self.notify("No microphones detected", severity="warning")
            return
        selected = set(service.selected_devices)
        selection = await self.push_screen_wait(DeviceSelectScreen(devices, selected))
        if selection is None:
            return
        removed = selected - selection
        added = selection - selected
        for device_id in removed:
            await service.toggle_device(device_id)
        for device_id in added:
            await service.toggle_device(device_id)
        await service.refresh()
        self.notify("Updated microphone selection", severity="information")

    async def action_clear_logs(self) -> None:
        log_widget = self.query_one(Log)
        log_widget.clear()

    def _current_service(self) -> Optional[BaseModuleService]:
        if not self.selected_module:
            self.notify("Select a module first", severity="warning")
            return None
        return self.modules[self.selected_module].service

    def watch_selected_module(self, old: Optional[str], new: Optional[str]) -> None:
        list_view = self.query_one("#module-list", ListView)
        if new is None:
            return
        for index, item in enumerate(list_view.children):
            card = item.query_one(ModuleCard)
            item.highlight = card.module_name == new
            if card.module_name == new:
                list_view.index = index


if __name__ == "__main__":
    RPiLoggerDashboard().run()
