"""
Custom themed widgets for TheLogger UI.
"""

import tkinter as tk
from typing import Optional, Callable

from .colors import Colors


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
        width: int = 100,
        height: int = 32,
        corner_radius: int = 8,
        style: str = 'default',
        **kwargs
    ):
        self._parent_bg = kwargs.pop('bg', Colors.BG_DARK)
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=self._parent_bg,
            highlightthickness=0,
            **kwargs
        )

        self.text = text
        self.command = command
        self._width = width
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
