"""
Custom themed widgets for Logger UI.
"""

import tkinter as tk
from typing import Optional, Callable

from .colors import Colors
from .styles import Fonts


class RoundedButton(tk.Canvas):
    """
    A button widget with rounded corners, matching CustomTkinter style.

    Styles:
        'default' - Dark gray button (#404040)
        'primary' - Blue button (#3498db)
        'success' - Green button (#2ecc71)
        'danger'  - Red button (#e74c3c)
    """

    STYLES = {
        'default': {
            'bg': Colors.BTN_DEFAULT_BG,
            'hover': Colors.BTN_DEFAULT_HOVER,
            'pressed': Colors.BTN_DEFAULT_PRESSED,
            'fg': Colors.BTN_DEFAULT_FG,
        },
        'primary': {
            'bg': Colors.BTN_PRIMARY_BG,
            'hover': Colors.BTN_PRIMARY_HOVER,
            'pressed': Colors.PRIMARY_PRESSED,
            'fg': Colors.BTN_PRIMARY_FG,
        },
        'success': {
            'bg': Colors.BTN_ACTIVE_BG,
            'hover': Colors.BTN_ACTIVE_HOVER,
            'pressed': Colors.BTN_ACTIVE_PRESSED,
            'fg': Colors.BTN_ACTIVE_FG,
        },
        'danger': {
            'bg': Colors.ERROR,
            'hover': Colors.ERROR_HOVER,
            'pressed': '#a93226',
            'fg': '#ffffff',
        },
        'inactive': {
            'bg': Colors.BTN_INACTIVE_BG,
            'hover': Colors.BTN_INACTIVE_HOVER,
            'pressed': Colors.BTN_INACTIVE_BG,
            'fg': Colors.BTN_INACTIVE_FG,
        },
    }

    def __init__(
        self,
        parent: tk.Widget,
        text: str = "",
        command: Optional[Callable] = None,
        width: Optional[int] = None,
        height: int = 32,
        corner_radius: int = 8,
        style: str = 'default',
        **kwargs
    ):
        self._parent_bg = kwargs.pop('bg', Colors.BG_DARK)
        # Use default width if not specified, but allow None for auto-resize
        initial_width = width if width is not None else 100
        super().__init__(
            parent,
            width=initial_width,
            height=height,
            bg=self._parent_bg,
            highlightthickness=0,
            **kwargs
        )

        self.text = text
        self.command = command
        self._width = initial_width
        self._height = height
        self._corner_radius = corner_radius
        self._style = style
        self._state = 'normal'

        colors = self.STYLES.get(style, self.STYLES['default'])
        self._bg_color = colors['bg']
        self._hover_color = colors['hover']
        self._pressed_color = colors['pressed']
        self._fg_color = colors['fg']

        self._current_bg = self._bg_color

        self._draw()
        self._bind_events()

        # Bind to configure event for resize support
        self.bind("<Configure>", self._on_configure)

    def _draw(self) -> None:
        """Draw the rounded button."""
        self.delete("all")

        r = self._corner_radius
        w = self._width
        h = self._height

        # Draw rounded rectangle
        self.create_arc(0, 0, 2*r, 2*r, start=90, extent=90, fill=self._current_bg, outline=self._current_bg)
        self.create_arc(w-2*r, 0, w, 2*r, start=0, extent=90, fill=self._current_bg, outline=self._current_bg)
        self.create_arc(0, h-2*r, 2*r, h, start=180, extent=90, fill=self._current_bg, outline=self._current_bg)
        self.create_arc(w-2*r, h-2*r, w, h, start=270, extent=90, fill=self._current_bg, outline=self._current_bg)

        # Fill rectangles
        self.create_rectangle(r, 0, w-r, h, fill=self._current_bg, outline=self._current_bg)
        self.create_rectangle(0, r, w, h-r, fill=self._current_bg, outline=self._current_bg)

        # Draw text
        self.create_text(
            w // 2,
            h // 2,
            text=self.text,
            fill=self._fg_color,
            font=('TkDefaultFont', 10)
        )

    def _bind_events(self) -> None:
        """Bind mouse events."""
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _on_enter(self, event) -> None:
        if self._state == 'normal':
            self._current_bg = self._hover_color
            self._draw()

    def _on_leave(self, event) -> None:
        if self._state == 'normal':
            self._current_bg = self._bg_color
            self._draw()

    def _on_press(self, event) -> None:
        if self._state == 'normal':
            self._current_bg = self._pressed_color
            self._draw()

    def _on_release(self, event) -> None:
        if self._state == 'normal':
            self._current_bg = self._hover_color
            self._draw()
            if self.command:
                self.command()

    def _on_configure(self, event) -> None:
        """Handle widget resize."""
        new_width = event.width
        new_height = event.height
        # Only redraw if size actually changed
        if new_width != self._width or new_height != self._height:
            self._width = new_width
            self._height = new_height
            self._draw()

    def configure(self, **kwargs) -> None:
        """Configure button properties."""
        if 'text' in kwargs:
            self.text = kwargs.pop('text')
        if 'command' in kwargs:
            self.command = kwargs.pop('command')
        if 'style' in kwargs:
            self._style = kwargs.pop('style')
            colors = self.STYLES.get(self._style, self.STYLES['default'])
            self._bg_color = colors['bg']
            self._hover_color = colors['hover']
            self._pressed_color = colors['pressed']
            self._fg_color = colors['fg']
            self._current_bg = self._bg_color
        if 'state' in kwargs:
            state = kwargs.pop('state')
            if state == 'disabled':
                self._state = 'disabled'
                colors = self.STYLES['inactive']
                self._current_bg = colors['bg']
                self._fg_color = colors['fg']
            else:
                self._state = 'normal'
                colors = self.STYLES.get(self._style, self.STYLES['default'])
                self._bg_color = colors['bg']
                self._current_bg = self._bg_color
                self._fg_color = colors['fg']

        self._draw()
        super().configure(**kwargs)

    config = configure

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the button."""
        self.configure(state='normal' if enabled else 'disabled')


class MetricBar(tk.Canvas):
    """A progress bar style metric display with color thresholds."""

    def __init__(
        self,
        parent: tk.Widget,
        width: int = 100,
        height: int = 12,
        max_value: float = 100,
        warning_threshold: float = 80,
        critical_threshold: float = 95,
        invert: bool = False,
        **kwargs
    ):
        bg = kwargs.pop('bg', Colors.CARD_BG)
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=bg,
            highlightthickness=0,
            **kwargs
        )
        self._width = width
        self._height = height
        self._max_value = max_value
        self._warning_threshold = warning_threshold
        self._critical_threshold = critical_threshold
        self._invert = invert
        self._value = 0
        self._draw()

    def _get_color(self) -> str:
        if self._invert:
            # For inverted metrics (like disk space), low values are bad
            if self._value <= self._critical_threshold:
                return Colors.METRIC_CRITICAL
            elif self._value <= self._warning_threshold:
                return Colors.METRIC_WARNING
            return Colors.METRIC_NORMAL
        else:
            # For normal metrics (like CPU), high values are bad
            if self._value >= self._critical_threshold:
                return Colors.METRIC_CRITICAL
            elif self._value >= self._warning_threshold:
                return Colors.METRIC_WARNING
            return Colors.METRIC_NORMAL

    def _draw(self) -> None:
        self.delete("all")

        bar_height = self._height - 2
        bar_width = self._width - 4

        # Background bar
        self.create_rectangle(
            2, 1, bar_width + 2, bar_height + 1,
            fill=Colors.METRIC_BG, outline=""
        )

        # Fill bar
        fill_ratio = min(self._value / self._max_value, 1.0) if self._max_value > 0 else 0
        fill_width = int(bar_width * fill_ratio)
        if fill_width > 0:
            color = self._get_color()
            self.create_rectangle(
                2, 1, fill_width + 2, bar_height + 1,
                fill=color, outline=""
            )

    def set_value(self, value: float) -> None:
        self._value = value
        self._draw()


class RecordingBar(tk.Frame):
    """Prominent recording indicator bar shown at bottom of window during recording."""

    def __init__(self, parent):
        super().__init__(parent, bg=Colors.RECORDING_BG, height=28)
        self._pulse_after_id = None
        self._dot_visible = True

        self._dot = tk.Canvas(
            self, width=14, height=14,
            bg=Colors.RECORDING_BG, highlightthickness=0
        )
        self._dot.pack(side=tk.LEFT, padx=(10, 6), pady=7)
        self._draw_dot()

        self._label = tk.Label(
            self, text="RECORDING",
            bg=Colors.RECORDING_BG, fg=Colors.FG_PRIMARY,
            font=Fonts.HEADING
        )
        self._label.pack(side=tk.LEFT, pady=4)

    def _draw_dot(self) -> None:
        self._dot.delete("all")
        color = Colors.RECORDING_DOT if self._dot_visible else Colors.RECORDING_BG
        self._dot.create_oval(1, 1, 13, 13, fill=color, outline=color)

    def _pulse(self) -> None:
        self._dot_visible = not self._dot_visible
        self._draw_dot()
        self._pulse_after_id = self.after(500, self._pulse)

    def start(self) -> None:
        self._dot_visible = True
        self._draw_dot()
        self._pulse()

    def stop(self) -> None:
        if self._pulse_after_id:
            self.after_cancel(self._pulse_after_id)
            self._pulse_after_id = None

    def destroy(self) -> None:
        self.stop()
        super().destroy()
