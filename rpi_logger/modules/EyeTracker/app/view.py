"""Neon EyeTracker view factory for VMC integration.

Implements the EyeTracker GUI following DRT/VOG patterns with:
- StubCodexView for VMC compatibility
- LegacyTkViewBridge for Tkinter integration
- Real-time video preview with gaze overlay
- Stream viewers for eyes, IMU, events, and audio
- Device status and recording state display
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, TYPE_CHECKING

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:
    tk = None  # type: ignore
    ttk = None  # type: ignore

import numpy as np

from rpi_logger.core.logging_utils import ensure_structured_logger, get_module_logger
from rpi_logger.modules.base.preferences import ModulePreferences
from vmc import LegacyTkViewBridge, StubCodexView

try:
    from rpi_logger.core.ui.theme.styles import Theme
    from rpi_logger.core.ui.theme.colors import Colors
    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    Theme = None  # type: ignore
    Colors = None  # type: ignore

# Import stream viewers
from .stream_viewers import (
    VideoViewer,
    EyesViewer,
    IMUViewer,
    EventsViewer,
    AudioViewer,
    StreamControls,
)

if TYPE_CHECKING:
    from rpi_logger.modules.EyeTracker.app.eye_tracker_runtime import EyeTrackerRuntime

ActionCallback = Optional[Callable[..., Awaitable[None]]]
FrameProvider = Callable[[], Optional[np.ndarray]]
DataProvider = Callable[[], Optional[Any]]
MetricsProvider = Callable[[], dict]


def _format_fps(value: Any) -> str:
    """Format a FPS value for display."""
    if value is None:
        return "  --"
    try:
        return f"{float(value):5.1f}"
    except (ValueError, TypeError):
        return "  --"


def _fps_color(actual: Any, target: Any) -> Optional[str]:
    """Get color based on how close actual FPS is to target."""
    if not HAS_THEME or Colors is None:
        return None
    try:
        if actual is not None and target is not None and float(target) > 0:
            pct = (float(actual) / float(target)) * 100
            if pct >= 95:
                return Colors.SUCCESS   # Green - good
            elif pct >= 80:
                return Colors.WARNING   # Orange - warning
            else:
                return Colors.ERROR     # Red - bad
    except (ValueError, TypeError):
        pass
    return Colors.FG_PRIMARY


class _SystemPlaceholder:
    """Minimal stand-in until the runtime is bound to the GUI."""

    recording: bool = False

    def __init__(self, args=None):
        self.config = getattr(args, 'config', {})
        self.config_file_path = getattr(args, 'config_file_path', None)


class _LoopAsyncBridge:
    """Lightweight bridge that schedules coroutines on the active asyncio loop.

    Uses run_coroutine_threadsafe for thread-safe scheduling from Tkinter callbacks.
    """

    def __init__(self) -> None:
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def run_coroutine(self, coro):
        loop = self._resolve_loop()
        return asyncio.run_coroutine_threadsafe(coro, loop)

    def _resolve_loop(self) -> asyncio.AbstractEventLoop:
        if self.loop and not self.loop.is_closed():
            return self.loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as exc:
            raise RuntimeError("Tkinter bridge has no running event loop bound") from exc
        self.loop = loop
        return loop


class NeonEyeTrackerTkinterGUI:
    """Tkinter GUI for Neon EyeTracker with real-time video preview.

    Key features:
    - Real-time video preview with gaze overlay
    - Stream viewers for eyes, IMU, events, and audio
    - Device status display (connected/disconnected)
    - Recording state indicator
    """

    def __init__(
        self,
        args,
        action_callback: ActionCallback,
        logger: Optional[logging.Logger] = None,
        embedded_parent: Optional["tk.Widget"] = None,
    ):
        self._action_callback = action_callback
        self.system = _SystemPlaceholder(args)
        self.args = args
        self.logger = ensure_structured_logger(logger, fallback_name="NeonEyeTrackerGUI") if logger else get_module_logger("NeonEyeTrackerGUI")
        self.async_bridge: Optional[_LoopAsyncBridge] = None

        # Preview state
        self._preview_interval_ms = 100  # Default 10 Hz, overridden by view
        self._preview_after_handle: Optional[str] = None

        # Data providers
        self._frame_provider: Optional[FrameProvider] = None
        self._eyes_frame_provider: Optional[FrameProvider] = None
        self._gaze_provider: Optional[DataProvider] = None
        self._imu_provider: Optional[DataProvider] = None
        self._event_provider: Optional[DataProvider] = None
        self._audio_provider: Optional[DataProvider] = None
        self._metrics_provider: Optional[MetricsProvider] = None

        # Metrics display elements
        self._metrics_fields: dict = {}  # StringVars
        self._metrics_labels: dict = {}  # Labels for color

        # Stream viewers
        self._video_viewer: Optional[VideoViewer] = None
        self._eyes_viewer: Optional[EyesViewer] = None
        self._imu_viewer: Optional[IMUViewer] = None
        self._events_viewer: Optional[EventsViewer] = None
        self._audio_viewer: Optional[AudioViewer] = None
        self._stream_controls: Optional[StreamControls] = None

        # UI references
        self.root = embedded_parent
        self._frame: Optional[tk.Frame] = None
        self._content_frame: Optional[tk.Frame] = None
        self._video_eyes_frame: Optional[tk.Frame] = None
        self._viewers_container: Optional[tk.Frame] = None

        if embedded_parent:
            self._build_ui(embedded_parent)

    def _build_ui(self, parent: tk.Widget):
        """Build the embedded UI with preview canvas and stream viewers."""

        try:
            # Main frame
            self._frame = ttk.Frame(parent)
            self._frame.pack(fill=tk.BOTH, expand=True)
            self._frame.columnconfigure(0, weight=1)
            self._frame.rowconfigure(0, weight=1)

            # Content frame for preview and viewers
            self._content_frame = ttk.Frame(self._frame)
            self._content_frame.grid(row=0, column=0, sticky="NSEW")
            self._content_frame.columnconfigure(0, weight=1)
            self._content_frame.rowconfigure(0, weight=1)  # Main row (video + eyes) expands
            self._content_frame.rowconfigure(1, weight=0)  # Other viewers container

            # Video/eyes container with weighted columns
            self._video_eyes_frame = ttk.Frame(self._content_frame)
            self._video_eyes_frame.grid(row=0, column=0, sticky="nsew")
            self._video_eyes_frame.rowconfigure(0, weight=1)

            # Create video viewer (left side, 3/4 weight when eyes visible)
            canvas_width = getattr(self.args, 'preview_width', 640) or 640
            canvas_height = getattr(self.args, 'preview_height', 480) or 480

            self._video_viewer = VideoViewer(
                self._video_eyes_frame,
                self.logger.getChild("VideoViewer"),
                width=canvas_width,
                height=canvas_height,
                row=0,
            )
            video_frame = self._video_viewer.build_ui()
            video_frame.grid(row=0, column=0, sticky="nsew")
            # Video viewer is always enabled - set state to match gridded frame
            self._video_viewer._visible = True
            self._video_viewer._enabled = True

            # Create eyes viewer (right side of video, stacked vertically)
            # Eyes are hidden by default, shown when checkbox is checked
            self._eyes_viewer = EyesViewer(
                self._video_eyes_frame,
                self.logger.getChild("EyesViewer"),
                row=0,
                stacked=True,  # Stack left/right eyes vertically
            )
            self._eyes_viewer.build_ui()
            # Don't grid the eyes viewer here - it starts hidden

            # Set initial column weights (video gets all space when eyes hidden)
            self._update_video_eyes_layout(eyes_visible=False)

            # Container for other stream viewers (below video)
            self._viewers_container = ttk.Frame(self._content_frame)
            self._viewers_container.grid(row=1, column=0, sticky="ew")
            self._viewers_container.columnconfigure(0, weight=1)

            # Audio viewer first (right under videos)
            self._audio_viewer = AudioViewer(
                self._viewers_container,
                self.logger.getChild("AudioViewer"),
                row=0,
            )
            self._audio_viewer.build_ui()

            self._imu_viewer = IMUViewer(
                self._viewers_container,
                self.logger.getChild("IMUViewer"),
                row=1,
            )
            self._imu_viewer.build_ui()

            self._events_viewer = EventsViewer(
                self._viewers_container,
                self.logger.getChild("EventsViewer"),
                row=2,
            )
            self._events_viewer.build_ui()
        except Exception as e:
            self.logger.error("Failed to build GUI: %s", e, exc_info=True)

    def _update_video_eyes_layout(self, eyes_visible: bool) -> None:
        """Update the video/eyes layout based on eyes visibility.

        When eyes are visible: video gets 4/5 weight, eyes get 1/5 weight
        When eyes are hidden: video gets all the space

        Uses uniform column groups to ensure consistent ratios regardless of
        window size (grid weights only distribute extra space, not total space).

        Args:
            eyes_visible: Whether the eyes viewer should be visible
        """
        if not self._video_eyes_frame:
            return

        if eyes_visible:
            # Video 4/5, eyes 1/5 using uniform groups for true proportional sizing
            self._video_eyes_frame.columnconfigure(0, weight=4, uniform="video_eyes")
            self._video_eyes_frame.columnconfigure(1, weight=1, uniform="video_eyes")
            # Show eyes viewer
            if self._eyes_viewer and self._eyes_viewer._frame:
                self._eyes_viewer._frame.grid(row=0, column=1, sticky="nsew")
                self._eyes_viewer._visible = True
        else:
            # Video gets all space - remove uniform group
            self._video_eyes_frame.columnconfigure(0, weight=1, uniform="")
            self._video_eyes_frame.columnconfigure(1, weight=0, uniform="")
            # Hide eyes viewer
            if self._eyes_viewer and self._eyes_viewer._frame:
                self._eyes_viewer._frame.grid_forget()
                self._eyes_viewer._visible = False

    # ------------------------------------------------------------------
    # Provider setters

    def set_frame_provider(self, provider: FrameProvider) -> None:
        """Set the frame provider callback for preview updates."""
        self._frame_provider = provider

    def set_eyes_frame_provider(self, provider: FrameProvider) -> None:
        """Set the eyes frame provider callback for eye preview updates."""
        self._eyes_frame_provider = provider

    def set_gaze_provider(self, provider: DataProvider) -> None:
        """Set the gaze data provider callback."""
        self._gaze_provider = provider

    def set_imu_provider(self, provider: DataProvider) -> None:
        """Set the IMU data provider callback."""
        self._imu_provider = provider

    def set_event_provider(self, provider: DataProvider) -> None:
        """Set the eye event data provider callback."""
        self._event_provider = provider

    def set_audio_provider(self, provider: DataProvider) -> None:
        """Set the audio data provider callback."""
        self._audio_provider = provider

    def set_metrics_provider(self, provider: MetricsProvider) -> None:
        """Set the metrics provider callback for FPS display."""
        self._metrics_provider = provider

    def set_preview_interval(self, interval_ms: int) -> None:
        """Set preview update interval in milliseconds."""
        self._preview_interval_ms = max(50, interval_ms)

    # ------------------------------------------------------------------
    # Stream controls

    def set_stream_controls(self, controls: StreamControls) -> None:
        """Set the stream controls instance and register viewers.

        Args:
            controls: StreamControls instance managing checkbox state
        """
        self._stream_controls = controls

        # Register viewers with controls
        # Note: video viewer is NOT registered - it's always enabled as the core
        # purpose of the module. Eyes viewer is also not registered here - we
        # handle its visibility through _update_video_eyes_layout in _on_stream_change
        if self._imu_viewer:
            controls.register_viewer("imu", self._imu_viewer)
        if self._events_viewer:
            controls.register_viewer("events", self._events_viewer)
        if self._audio_viewer:
            controls.register_viewer("audio", self._audio_viewer)

        # Set up callback for stream changes (e.g., eyes visibility)
        controls.set_on_change_callback(self._on_stream_change)

    def _on_stream_change(self, stream: str, enabled: bool) -> None:
        """Handle stream state changes from controls.

        Args:
            stream: Name of the stream that changed
            enabled: New enabled state
        """
        # Handle eyes viewer layout change
        # We manage eyes visibility through layout, not set_enabled
        if stream == "eyes" and self._eyes_viewer:
            self._eyes_viewer._enabled = enabled  # For preview loop updates
            self._update_video_eyes_layout(eyes_visible=enabled)

    # ------------------------------------------------------------------
    # Preview loop

    def start_preview(self) -> None:
        """Start the preview update loop."""
        if self._video_viewer and self.root:
            self._schedule_preview()

    def _schedule_preview(self) -> None:
        """Schedule the next preview update."""
        if not self.root:
            return
        self._preview_after_handle = self.root.after(
            self._preview_interval_ms,
            self._preview_tick
        )

    def _preview_tick(self) -> None:
        """Update all enabled stream viewers with latest data."""
        # Update video viewer
        if self._video_viewer and self._video_viewer.enabled:
            frame = self._frame_provider() if self._frame_provider else None
            gaze = self._gaze_provider() if self._gaze_provider else None
            self._video_viewer.update(frame, gaze)

        # Update eyes viewer
        if self._eyes_viewer and self._eyes_viewer.enabled:
            eyes = self._eyes_frame_provider() if self._eyes_frame_provider else None
            self._eyes_viewer.update(eyes)

        # Update IMU viewer
        if self._imu_viewer and self._imu_viewer.enabled:
            imu = self._imu_provider() if self._imu_provider else None
            self._imu_viewer.update(imu)

        # Update events viewer (with gaze data for PERCLOS)
        if self._events_viewer and self._events_viewer.enabled:
            event = self._event_provider() if self._event_provider else None
            gaze = self._gaze_provider() if self._gaze_provider else None
            self._events_viewer.update(event, gaze)

        # Update audio viewer
        if self._audio_viewer and self._audio_viewer.enabled:
            audio = self._audio_provider() if self._audio_provider else None
            self._audio_viewer.update(audio)

        # Update metrics display
        if self._metrics_provider:
            metrics = self._metrics_provider()
            if metrics:
                self.update_metrics(metrics)

        self._schedule_preview()

    def stop_preview(self) -> None:
        """Stop the preview update loop."""
        if self._preview_after_handle and self.root:
            try:
                self.root.after_cancel(self._preview_after_handle)
            except tk.TclError:
                pass
            self._preview_after_handle = None

    def update_metrics(self, metrics: dict) -> None:
        """Update metrics display with FPS values."""
        if not self._metrics_fields:
            return

        # Capture metrics: fps_capture vs target_fps
        cap_actual = metrics.get("fps_capture")
        cap_target = metrics.get("target_fps")
        cap_str = f"{_format_fps(cap_actual)} / {_format_fps(cap_target)}"
        cap_color = _fps_color(cap_actual, cap_target)

        # Record metrics: fps_record vs target_record_fps
        rec_actual = metrics.get("fps_record")
        rec_target = metrics.get("target_record_fps")
        rec_str = f"{_format_fps(rec_actual)} / {_format_fps(rec_target)}"
        rec_color = _fps_color(rec_actual, rec_target)

        # Display metrics: fps_display vs target_display_fps
        disp_actual = metrics.get("fps_display")
        disp_target = metrics.get("target_display_fps")
        disp_str = f"{_format_fps(disp_actual)} / {_format_fps(disp_target)}"
        disp_color = _fps_color(disp_actual, disp_target)

        def update():
            try:
                # Update values
                if "cap_tgt" in self._metrics_fields:
                    self._metrics_fields["cap_tgt"].set(cap_str)
                if "rec_tgt" in self._metrics_fields:
                    self._metrics_fields["rec_tgt"].set(rec_str)
                if "disp_tgt" in self._metrics_fields:
                    self._metrics_fields["disp_tgt"].set(disp_str)

                # Update colors
                if "cap_tgt" in self._metrics_labels and cap_color:
                    self._metrics_labels["cap_tgt"].configure(fg=cap_color)
                if "rec_tgt" in self._metrics_labels and rec_color:
                    self._metrics_labels["rec_tgt"].configure(fg=rec_color)
                if "disp_tgt" in self._metrics_labels and disp_color:
                    self._metrics_labels["disp_tgt"].configure(fg=disp_color)
            except Exception:
                pass

        # Schedule on UI thread if needed
        if self.root:
            try:
                self.root.after(0, update)
            except Exception:
                pass
        else:
            update()

    # ------------------------------------------------------------------
    # Menu callbacks

    def _on_reconnect_clicked(self) -> None:
        """Handle reconnect button click."""
        if hasattr(self.system, 'request_reconnect') and self.async_bridge:
            self.async_bridge.run_coroutine(self.system.request_reconnect())

    def _on_configure_clicked(self) -> None:
        """Handle configure button click."""
        if not self.root:
            return

        try:
            from rpi_logger.modules.EyeTracker.tracker_core.interfaces.gui.config_window import EyeTrackerConfigWindow
            EyeTrackerConfigWindow(self.root, self.system)
        except ImportError as e:
            self.logger.warning("Config window not available: %s", e)
        except Exception as e:
            self.logger.error("Failed to create config window: %s", e, exc_info=True)

    # ------------------------------------------------------------------
    # Lifecycle

    def handle_window_close(self) -> None:
        """Handle window close event."""
        self.stop_preview()
        # Cleanup viewers
        for viewer in [self._video_viewer, self._eyes_viewer, self._imu_viewer,
                       self._events_viewer, self._audio_viewer]:
            if viewer:
                viewer.cleanup()


class NeonEyeTrackerView:
    """Adapter that exposes the Neon EyeTracker GUI through the VMC supervisor interface.

    Follows DRT/VOG patterns for:
    - StubCodexView integration
    - LegacyTkViewBridge mounting
    - Runtime binding
    - Model observation
    """

    def __init__(
        self,
        args,
        model,
        action_callback: Optional[Callable[[str], Awaitable[None]]] = None,
        *,
        display_name: str,
        logger: Optional[logging.Logger] = None,
        help_callback: Optional[Callable] = None,
    ) -> None:
        self.args = args
        self.model = model
        self.action_callback = action_callback
        self.display_name = display_name or "EyeTracker-Neon"
        self.logger = ensure_structured_logger(logger, fallback_name="NeonEyeTrackerView") if logger else get_module_logger("NeonEyeTrackerView")

        stub_logger = self.logger.getChild("Stub")
        self._stub_view = StubCodexView(
            args,
            model,
            action_callback=action_callback,
            display_name=self.display_name,
            logger=stub_logger,
            help_callback=help_callback,
        )
        self._bridge = LegacyTkViewBridge(self._stub_view, logger=self.logger.getChild("Bridge"))
        self.gui: Optional[NeonEyeTrackerTkinterGUI] = None
        self._runtime: Optional["EyeTrackerRuntime"] = None
        self._controls_menu: Optional[Any] = None
        self._stream_controls: Optional[StreamControls] = None

        # Initialize preferences for config persistence
        config_path = getattr(args, "config_file_path", None)
        if config_path:
            self._preferences = ModulePreferences(Path(config_path))
        else:
            self._preferences = None

        self._bridge.mount(self._build_embedded_gui)
        self._stub_view.set_preview_title("Preview")
        self.model.subscribe(self._on_model_change)
        self._override_help_menu()

    def _build_embedded_gui(self, parent) -> Optional[Any]:
        """Build the embedded GUI within the VMC container."""

        # Apply theme to root window
        try:
            root = parent.winfo_toplevel()
            if HAS_THEME and Theme is not None:
                Theme.apply(root)
        except Exception:
            pass

        if hasattr(parent, "columnconfigure"):
            try:
                parent.columnconfigure(0, weight=1)
                parent.rowconfigure(0, weight=1)
            except Exception:
                pass

        container = ttk.Frame(parent)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        gui = NeonEyeTrackerTkinterGUI(
            self.args,
            self._dispatch_action,
            logger=self.logger.getChild("GUI"),
            embedded_parent=container,
        )
        gui.async_bridge = _LoopAsyncBridge()
        loop = getattr(self._stub_view, "_event_loop", None)
        if loop and isinstance(gui.async_bridge, _LoopAsyncBridge):
            gui.async_bridge.bind_loop(loop)
        self.gui = gui

        # Create stream controls
        root = getattr(self._stub_view, "root", None)
        if root:
            self._stream_controls = StreamControls(root, self.logger)
            gui.set_stream_controls(self._stream_controls)

        # Apply pending runtime binding if bind_runtime was called before GUI created
        if self._runtime:
            self.bind_runtime(self._runtime)

        # Build IO stub content (status panel)
        self._build_io_stub_content()

        # Install Controls menu
        self._install_controls_menu()

        return container

    def _install_controls_menu(self) -> None:
        """Install the Controls menu with Configure, stream checkboxes, and Reconnect."""
        if self._controls_menu is not None:
            return

        menu = None
        add_menu = getattr(self._stub_view, "add_menu", None)
        menubar = getattr(self._stub_view, "menubar", None)

        if callable(add_menu):
            try:
                menu = add_menu("Controls")
            except Exception:
                menu = None
        if menu is None and menubar is not None:
            try:
                menu = tk.Menu(menubar, tearoff=0)
                menubar.add_cascade(label="Controls", menu=menu)
            except Exception:
                menu = None

        if menu is None:
            return

        self._controls_menu = menu

        # Configure option
        menu.add_command(
            label="Configure...",
            command=self._on_configure_menu,
        )

        # Add stream controls checkboxes
        if self._stream_controls:
            self._stream_controls.build_menu(menu)

        menu.add_separator()

        # Reconnect option
        menu.add_command(
            label="Reconnect",
            command=self._on_reconnect_menu,
        )

    def _on_configure_menu(self) -> None:
        """Handle Configure menu item click."""
        if self.gui:
            self.gui._on_configure_clicked()

    def _on_reconnect_menu(self) -> None:
        """Handle Reconnect menu item click."""
        if self.gui:
            self.gui._on_reconnect_clicked()

    def _build_io_stub_content(self) -> None:
        """Build the status panel in the IO stub area."""
        if not self.gui:
            return

        def builder(parent: tk.Widget) -> None:
            parent.columnconfigure(0, weight=1)

            # Capture Stats LabelFrame - 3-column layout matching Cameras module
            stats_lf = ttk.LabelFrame(parent, text="Capture Stats")
            stats_lf.grid(row=0, column=0, sticky="new", padx=4, pady=(4, 2))
            stats_lf.columnconfigure(0, weight=1)

            # Define the fields (matching Cameras pattern)
            fields = [
                ("cap_tgt", "Cap In/Tgt"),
                ("rec_tgt", "Rec Out/Tgt"),
                ("disp_tgt", "Disp/Tgt"),
            ]

            # Initialize StringVars for all fields
            for key, _ in fields:
                self.gui._metrics_fields[key] = tk.StringVar(
                    master=parent, value="  -- /   --"
                )

            # Build stats display
            bg = Colors.BG_FRAME if HAS_THEME and Colors else None
            fg1 = Colors.FG_SECONDARY if HAS_THEME and Colors else None
            fg2 = Colors.FG_PRIMARY if HAS_THEME and Colors else None

            if HAS_THEME and Colors:
                container = tk.Frame(stats_lf, bg=bg)
            else:
                container = ttk.Frame(stats_lf)
            container.grid(row=0, column=0, sticky="ew", padx=2, pady=2)

            # Configure 3 columns with uniform width
            for idx in range(len(fields)):
                container.columnconfigure(idx, weight=1, uniform="stats")

            # Create label and value widgets for each column
            for col, (key, label_text) in enumerate(fields):
                if HAS_THEME and Colors:
                    name = tk.Label(
                        container, text=label_text, anchor="center",
                        bg=bg, fg=fg1
                    )
                    val = tk.Label(
                        container, textvariable=self.gui._metrics_fields[key],
                        anchor="center", bg=bg, fg=fg2, font=("TkFixedFont", 9)
                    )
                else:
                    name = ttk.Label(container, text=label_text, anchor="center")
                    val = ttk.Label(
                        container, textvariable=self.gui._metrics_fields[key],
                        anchor="center"
                    )
                    try:
                        val.configure(font=("TkFixedFont", 9))
                    except Exception:
                        pass

                name.grid(row=0, column=col, sticky="ew", padx=2)
                val.grid(row=1, column=col, sticky="ew", padx=2)
                self.gui._metrics_labels[key] = val

        self._stub_view.set_io_stub_title("EyeTracker-Neon")
        self._stub_view.build_io_stub_content(builder)

    def bind_runtime(self, runtime: "EyeTrackerRuntime") -> None:
        """Bind runtime to view, enabling button callbacks and frame provider."""
        self._runtime = runtime
        if self.gui:
            self.gui.system = runtime

            # Bind async bridge loop
            if isinstance(self.gui.async_bridge, _LoopAsyncBridge):
                loop = getattr(runtime, "_loop", None)
                if loop:
                    self.gui.async_bridge.bind_loop(loop)

            # Set up frame provider (video with gaze overlay)
            if hasattr(runtime, '_get_latest_frame'):
                self.gui.set_frame_provider(runtime._get_latest_frame)

            # Set up eyes frame provider
            if hasattr(runtime, '_get_latest_eyes_frame'):
                self.gui.set_eyes_frame_provider(runtime._get_latest_eyes_frame)

            # Set up gaze provider
            if hasattr(runtime, '_get_latest_gaze'):
                self.gui.set_gaze_provider(runtime._get_latest_gaze)

            # Set up IMU provider
            if hasattr(runtime, '_get_latest_imu'):
                self.gui.set_imu_provider(runtime._get_latest_imu)

            # Set up event provider
            if hasattr(runtime, '_get_latest_event'):
                self.gui.set_event_provider(runtime._get_latest_event)

            # Set up audio provider
            if hasattr(runtime, '_get_latest_audio'):
                self.gui.set_audio_provider(runtime._get_latest_audio)

            # Set up metrics provider for FPS display
            if hasattr(runtime, '_get_metrics'):
                self.gui.set_metrics_provider(runtime._get_metrics)

            # Load stream states from config if available
            if self._stream_controls and hasattr(runtime, 'config'):
                self._stream_controls.load_from_config(runtime.config)
                # Handle eyes viewer state separately (not registered with controls)
                eyes_enabled = self._stream_controls.is_enabled("eyes")
                if self.gui and self.gui._eyes_viewer:
                    self.gui._eyes_viewer._enabled = eyes_enabled
                    self.gui._update_video_eyes_layout(eyes_visible=eyes_enabled)

            # Ensure video viewer is always enabled (no toggle for video)
            if self.gui._video_viewer:
                self.gui._video_viewer._enabled = True

            # Set preview interval from config
            preview_hz = max(1, int(getattr(self.args, "gui_preview_update_hz", 10)))
            self.gui.set_preview_interval(int(1000 / preview_hz))

            # Start preview loop
            self.gui.start_preview()

    def attach_logging_handler(self) -> None:
        """Attach logging handler to stub view."""
        self._stub_view.attach_logging_handler()

    def call_in_gui(self, func, *args, **kwargs) -> None:
        """Schedule a function call in the GUI thread."""
        root = getattr(self._stub_view, "root", None)
        if not root:
            return
        try:
            root.after(0, lambda: func(*args, **kwargs))
        except tk.TclError:
            return

    # ------------------------------------------------------------------
    # Runtime-to-view notifications (no-ops, device status UI removed)

    def on_device_connected(self, device_name: str) -> None:
        """Handle device connection (no-op)."""
        pass

    def on_device_disconnected(self) -> None:
        """Handle device disconnection (no-op)."""
        pass

    def set_device_status(self, text: str, *, connected: bool) -> None:
        """Update device status display (no-op)."""
        pass

    def set_device_info(self, device_name: str) -> None:
        """Update device name display (no-op)."""
        pass

    def set_recording_state(self, active: bool) -> None:
        """Update recording state display (no-op)."""
        pass

    def update_recording_state(self) -> None:
        """Sync recording state from model (no-op)."""
        pass

    # ------------------------------------------------------------------
    # Window control

    def set_window_title(self, title: str) -> None:
        """Delegate window title changes to the stub view."""
        self._stub_view.set_window_title(title)

    # ------------------------------------------------------------------
    # Lifecycle

    async def run(self) -> float:
        """Run the view event loop."""
        return await self._stub_view.run()

    async def cleanup(self) -> None:
        """Clean up view resources."""
        # Save stream states to config object and persist to disk
        if self._stream_controls and self._runtime and hasattr(self._runtime, 'config'):
            self._stream_controls.save_to_config(self._runtime.config)

            # Persist stream states to config file (video always enabled, not persisted)
            if self._preferences:
                config = self._runtime.config
                stream_updates = {
                    "stream_gaze_enabled": config.stream_gaze_enabled,
                    "stream_eyes_enabled": config.stream_eyes_enabled,
                    "stream_imu_enabled": config.stream_imu_enabled,
                    "stream_events_enabled": config.stream_events_enabled,
                    "stream_audio_enabled": config.stream_audio_enabled,
                }
                try:
                    await self._preferences.write_async(stream_updates)
                except Exception:
                    pass

        if self.gui:
            try:
                self.gui.handle_window_close()
            except Exception:
                pass
        self._bridge.cleanup()
        await self._stub_view.cleanup()
        self.gui = None

    @property
    def window_duration_ms(self) -> float:
        """Return window duration from stub view."""
        return getattr(self._stub_view, "window_duration_ms", 0.0)

    @property
    def root(self):
        """Return root window from stub view."""
        return getattr(self._stub_view, "root", None)

    # ------------------------------------------------------------------
    # Help menu

    def _override_help_menu(self) -> None:
        """Replace the generic help menu with EyeTracker-specific help."""
        help_menu = getattr(self._stub_view, 'help_menu', None)
        if help_menu is None:
            return
        try:
            help_menu.delete(0)
            help_menu.add_command(label="Quick Start Guide", command=self._show_help)
        except Exception:
            pass

    def _show_help(self) -> None:
        """Show EyeTracker-specific help dialog."""
        try:
            from rpi_logger.modules.EyeTracker.tracker_core.interfaces.gui.help_dialog import EyeTrackerHelpDialog
            root = getattr(self._stub_view, 'root', None)
            if root:
                EyeTrackerHelpDialog(root)
        except Exception as e:
            self.logger.error("Failed to show help dialog: %s", e)

    # ------------------------------------------------------------------
    # Internal helpers

    async def _dispatch_action(self, action: str, **kwargs) -> None:
        """Dispatch action callback."""
        if not self.action_callback:
            return
        await self.action_callback(action, **kwargs)

    def _on_model_change(self, prop: str, value) -> None:
        """Handle model property changes (no-op, device status UI removed)."""
        pass
