"""
Camera/Sensor Information Dialog.

Displays detailed technical information about a camera sensor including
shutter type, intended use, hardware vs software capabilities, and
other characteristics that cannot be discovered through software probing.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:
    tk = None
    ttk = None

try:
    from rpi_logger.core.ui.theme.styles import Theme
    from rpi_logger.core.ui.theme.colors import Colors

    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    Theme = None
    Colors = None


class SensorInfoDialog:
    """Dialog showing detailed camera/sensor information."""

    def __init__(self, parent: tk.Widget, sensor_info: Dict[str, Any], camera_name: str):
        """
        Create the sensor info dialog.

        Args:
            parent: Parent widget
            sensor_info: Dictionary containing sensor information from camera_models.json
            camera_name: Display name of the camera
        """
        if tk is None:
            return

        self.dialog = tk.Toplevel(parent)
        self.dialog.title(f"Sensor Info - {camera_name}")

        try:
            self.dialog.transient(parent)
        except Exception:
            pass

        if HAS_THEME and Theme is not None:
            try:
                Theme.configure_toplevel(self.dialog)
            except Exception:
                pass

        self.dialog.geometry("480x520")
        self.dialog.minsize(400, 400)

        self._build_ui(sensor_info, camera_name)

        # Center on parent
        self.dialog.update_idletasks()
        try:
            x = parent.winfo_rootx() + (parent.winfo_width() // 2) - 240
            y = parent.winfo_rooty() + (parent.winfo_height() // 2) - 260
            self.dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

        # Make window visible first, then grab focus
        self.dialog.deiconify()
        self.dialog.lift()
        self.dialog.focus_force()

        # Grab after window is visible
        self.dialog.after(10, self._try_grab)

    def _try_grab(self) -> None:
        """Try to grab focus after window is visible."""
        try:
            self.dialog.grab_set()
        except Exception:
            pass

    def _build_ui(self, sensor_info: Dict[str, Any], camera_name: str) -> None:
        """Build the dialog UI."""
        # Get theme colors
        bg_color = Colors.BG_DARK if HAS_THEME and Colors else None

        main_frame = ttk.Frame(self.dialog, padding=12)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)

        # Header
        header_frame = ttk.Frame(main_frame)
        header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        title = ttk.Label(header_frame, text=camera_name, font=("TkDefaultFont", 11, "bold"))
        title.pack(anchor="w")

        if sensor_info.get("sensor_model"):
            subtitle = ttk.Label(
                header_frame,
                text=f"Sensor: {sensor_info.get('sensor_model')}",
            )
            subtitle.pack(anchor="w")

        # Scrollable content area using canvas
        canvas_frame = ttk.Frame(main_frame)
        canvas_frame.grid(row=1, column=0, sticky="nsew")
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)

        canvas = tk.Canvas(canvas_frame, highlightthickness=0, bd=0)
        if bg_color:
            canvas.configure(bg=bg_color)

        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)

        # Inner frame for content
        content_frame = ttk.Frame(canvas)

        # Create window in canvas
        canvas_window = canvas.create_window((0, 0), window=content_frame, anchor="nw")

        # Configure canvas scrolling
        def configure_scroll(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            # Make content frame fill canvas width
            canvas.itemconfig(canvas_window, width=event.width)

        canvas.bind("<Configure>", configure_scroll)
        content_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        # Build info sections
        self._build_sections(content_frame, sensor_info)

        # Mouse wheel scrolling
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def on_scroll_up(event):
            canvas.yview_scroll(-1, "units")

        def on_scroll_down(event):
            canvas.yview_scroll(1, "units")

        canvas.bind_all("<MouseWheel>", on_mousewheel)
        canvas.bind_all("<Button-4>", on_scroll_up)
        canvas.bind_all("<Button-5>", on_scroll_down)

        # Store cleanup function
        def cleanup():
            try:
                canvas.unbind_all("<MouseWheel>")
                canvas.unbind_all("<Button-4>")
                canvas.unbind_all("<Button-5>")
            except Exception:
                pass
            self.dialog.destroy()

        self.dialog.protocol("WM_DELETE_WINDOW", cleanup)

        # Close button
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=2, column=0, sticky="e", pady=(12, 0))

        close_btn = ttk.Button(btn_frame, text="Close", command=cleanup)
        close_btn.pack()

    def _build_sections(self, parent: ttk.Frame, sensor_info: Dict[str, Any]) -> None:
        """Build the information sections."""
        row = 0

        # If sensor_info is empty or None, show a message
        if not sensor_info:
            ttk.Label(parent, text="No sensor information available.").grid(
                row=0, column=0, padx=10, pady=10
            )
            return

        # Sensor Characteristics
        sensor_data = self._get_sensor_section(sensor_info)
        if sensor_data:
            row = self._add_section(parent, "Sensor Characteristics", sensor_data, row)

        # Capabilities
        caps_data = self._get_capabilities_section(sensor_info)
        if caps_data:
            row = self._add_section(parent, "Capabilities", caps_data, row)

        # Intended Use
        use_data = self._get_use_section(sensor_info)
        if use_data:
            row = self._add_section(parent, "Intended Use", use_data, row)

        # Hardware vs Software
        hw_sw_data = self._get_hw_sw_section(sensor_info)
        if hw_sw_data:
            row = self._add_section(parent, "Hardware vs Software", hw_sw_data, row)

        # Additional Notes
        if sensor_info.get("notes"):
            row = self._add_section(
                parent, "Notes", [("", sensor_info.get("notes"))], row
            )

        # Fallback if no sections were added
        if row == 0:
            # Show raw data as fallback
            all_data = [(k, v) for k, v in sensor_info.items() if v is not None]
            if all_data:
                self._add_section(parent, "Sensor Information", all_data, 0)

    def _get_sensor_section(self, info: Dict[str, Any]) -> list:
        """Extract sensor characteristics data."""
        data = []
        if info.get("sensor_model"):
            data.append(("Sensor Model", info["sensor_model"]))
        if info.get("sensor_type"):
            data.append(("Sensor Type", info["sensor_type"]))
        if info.get("sensor_format"):
            data.append(("Sensor Format", info["sensor_format"]))
        if info.get("pixel_size"):
            data.append(("Pixel Size", info["pixel_size"]))
        if info.get("shutter_type"):
            data.append(("Shutter Type", info["shutter_type"]))
        if info.get("native_resolution"):
            data.append(("Native Resolution", info["native_resolution"]))
        if info.get("max_fps"):
            data.append(("Max Frame Rate", info["max_fps"]))
        return data

    def _get_capabilities_section(self, info: Dict[str, Any]) -> list:
        """Extract capabilities data."""
        data = []
        if info.get("autofocus") is not None:
            data.append(("Autofocus", self._format_bool(info["autofocus"])))
        if info.get("auto_exposure") is not None:
            data.append(("Auto Exposure", self._format_bool(info["auto_exposure"])))
        if info.get("auto_white_balance") is not None:
            data.append(("Auto White Balance", self._format_bool(info["auto_white_balance"])))
        if info.get("manual_controls"):
            data.append(("Manual Controls", info["manual_controls"]))
        if info.get("color_formats"):
            data.append(("Color Formats", info["color_formats"]))
        return data

    def _get_use_section(self, info: Dict[str, Any]) -> list:
        """Extract intended use data."""
        data = []
        if info.get("intended_use"):
            data.append(("Primary Use", info["intended_use"]))
        if info.get("best_for"):
            data.append(("Best For", info["best_for"]))
        if info.get("limitations"):
            data.append(("Limitations", info["limitations"]))
        return data

    def _get_hw_sw_section(self, info: Dict[str, Any]) -> list:
        """Extract hardware vs software feature data."""
        data = []
        if info.get("hw_fps_control") is not None:
            val = "Hardware" if info["hw_fps_control"] else "Software"
            data.append(("FPS Control", val))
        if info.get("hw_resolution_control") is not None:
            val = "Hardware" if info["hw_resolution_control"] else "Software"
            data.append(("Resolution Control", val))
        if info.get("hw_exposure_control") is not None:
            val = "Hardware" if info["hw_exposure_control"] else "Software"
            data.append(("Exposure Control", val))
        if info.get("hw_timestamp") is not None:
            val = "Yes (Sensor)" if info["hw_timestamp"] else "No (Software Only)"
            data.append(("Hardware Timestamps", val))
        if info.get("onboard_isp") is not None:
            data.append(("Onboard ISP", self._format_bool(info["onboard_isp"])))
        if info.get("compression"):
            data.append(("Compression", info["compression"]))
        return data

    def _format_bool(self, value: Any) -> str:
        """Format boolean value for display."""
        if isinstance(value, bool):
            return "Yes" if value else "No"
        return str(value)

    def _add_section(
        self, parent: ttk.Frame, title: str, data: list, start_row: int
    ) -> int:
        """Add a section with a title and key-value pairs."""
        if not data:
            return start_row

        # Use Inframe styles for proper theme integration
        key_style = "Inframe.Secondary.TLabel" if HAS_THEME else ""
        value_style = "Inframe.TLabel" if HAS_THEME else ""

        # Section title
        section_frame = ttk.LabelFrame(parent, text=title, padding=8)
        section_frame.grid(row=start_row, column=0, sticky="ew", pady=(0, 8), padx=4)
        section_frame.columnconfigure(1, weight=1)

        for i, (key, value) in enumerate(data):
            if key:
                key_label = ttk.Label(section_frame, text=f"{key}:", style=key_style)
                key_label.grid(row=i, column=0, sticky="nw", padx=(0, 8), pady=2)

                val_label = ttk.Label(section_frame, text=str(value), wraplength=280, style=value_style)
                val_label.grid(row=i, column=1, sticky="nw", pady=2)
            else:
                # Full-width text (for notes)
                text_label = ttk.Label(section_frame, text=str(value), wraplength=380, style=value_style)
                text_label.grid(row=i, column=0, columnspan=2, sticky="nw", pady=2)

        return start_row + 1


def show_sensor_info(parent: tk.Widget, sensor_info: Dict[str, Any], camera_name: str) -> None:
    """
    Show the sensor info dialog.

    Args:
        parent: Parent widget
        sensor_info: Dictionary containing sensor information
        camera_name: Display name of the camera
    """
    if tk is None:
        return
    SensorInfoDialog(parent, sensor_info, camera_name)
