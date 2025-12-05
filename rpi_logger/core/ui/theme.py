"""
Centralized theme configuration for TheLogger UI.

Dark theme inspired by rei-simulator's design philosophy:
- Dark backgrounds for reduced eye strain
- Semantic color coding (green=good, red=error, orange=warning, blue=primary)
- High contrast text for readability
- Rounded button corners for modern look
"""

from tkinter import ttk
import tkinter as tk
from typing import Optional, Callable


class Colors:
    """Color palette for the application."""

    # Background colors (matching rei-simulator dark theme)
    BG_DARK = "#2b2b2b"          # Dark gray - primary background
    BG_DARKER = "#242424"        # Darker gray - secondary/inset areas
    BG_FRAME = "#363636"         # Frame backgrounds
    BG_INPUT = "#3d3d3d"         # Entry/input backgrounds
    BG_CANVAS = "#1e1e1e"        # Canvas backgrounds (black)

    # Foreground/text colors
    FG_PRIMARY = "#ecf0f1"       # Primary text (light gray/white)
    FG_SECONDARY = "#95a5a6"     # Secondary text (muted gray)
    FG_MUTED = "#6c7a89"         # Muted text (darker gray)

    # Accent colors
    PRIMARY = "#3498db"          # Blue - primary actions
    PRIMARY_HOVER = "#2980b9"    # Blue hover state
    PRIMARY_PRESSED = "#2471a3"  # Blue pressed state

    SUCCESS = "#2ecc71"          # Green - success, active, connected
    SUCCESS_HOVER = "#27ae60"    # Green hover
    SUCCESS_DARK = "#1e8449"     # Green pressed

    WARNING = "#f39c12"          # Orange - warnings, connecting
    WARNING_HOVER = "#e67e22"    # Orange hover

    ERROR = "#e74c3c"            # Red - errors, disconnected
    ERROR_HOVER = "#c0392b"      # Red hover

    # Status colors
    STATUS_READY = "#95a5a6"     # Gray - ready/idle
    STATUS_CONNECTING = "#f39c12"  # Orange - connecting
    STATUS_CONNECTED = "#2ecc71"   # Green - connected
    STATUS_ERROR = "#e74c3c"       # Red - error

    # Button colors (matching rei-simulator style)
    BTN_ACTIVE_BG = "#2ecc71"    # Green for active/start buttons
    BTN_ACTIVE_FG = "#ffffff"
    BTN_ACTIVE_HOVER = "#27ae60"
    BTN_ACTIVE_PRESSED = "#1e8449"

    BTN_INACTIVE_BG = "#404040"  # Dark gray for inactive/disabled
    BTN_INACTIVE_FG = "#808080"
    BTN_INACTIVE_HOVER = "#505050"

    BTN_DEFAULT_BG = "#404040"   # Dark gray default button (rei-simulator style)
    BTN_DEFAULT_FG = "#ecf0f1"
    BTN_DEFAULT_HOVER = "#505050"
    BTN_DEFAULT_PRESSED = "#353535"

    BTN_PRIMARY_BG = "#3498db"   # Blue for primary emphasis buttons
    BTN_PRIMARY_FG = "#ffffff"
    BTN_PRIMARY_HOVER = "#2980b9"

    # Border colors
    BORDER = "#404055"
    BORDER_LIGHT = "#505068"

    # Semantic aliases
    PROFIT = SUCCESS
    LOSS = ERROR
    NEUTRAL = FG_SECONDARY


class Theme:
    """Configure ttk styles for the dark theme."""

    @staticmethod
    def apply(root: tk.Tk) -> None:
        """Apply the dark theme to the application."""
        style = ttk.Style()
        style.theme_use('clam')

        # Configure root window
        root.configure(bg=Colors.BG_DARK)

        # TFrame
        style.configure(
            'TFrame',
            background=Colors.BG_DARK
        )

        # TLabelframe
        style.configure(
            'TLabelframe',
            background=Colors.BG_FRAME,
            bordercolor=Colors.BORDER,
            relief='solid'
        )
        style.configure(
            'TLabelframe.Label',
            background=Colors.BG_FRAME,
            foreground=Colors.FG_PRIMARY,
            font=('TkDefaultFont', 10, 'bold')
        )

        # TLabel
        style.configure(
            'TLabel',
            background=Colors.BG_DARK,
            foreground=Colors.FG_PRIMARY
        )

        # Labels inside labelframes (to match BG_FRAME)
        style.configure(
            'Inframe.TLabel',
            background=Colors.BG_FRAME,
            foreground=Colors.FG_PRIMARY
        )
        style.configure(
            'Inframe.Secondary.TLabel',
            background=Colors.BG_FRAME,
            foreground=Colors.FG_SECONDARY
        )

        # Secondary labels
        style.configure(
            'Secondary.TLabel',
            background=Colors.BG_DARK,
            foreground=Colors.FG_SECONDARY
        )

        # Muted labels
        style.configure(
            'Muted.TLabel',
            background=Colors.BG_DARK,
            foreground=Colors.FG_MUTED
        )

        # Status labels
        style.configure(
            'Status.Ready.TLabel',
            background=Colors.BG_DARK,
            foreground=Colors.STATUS_READY
        )
        style.configure(
            'Status.Connecting.TLabel',
            background=Colors.BG_DARK,
            foreground=Colors.STATUS_CONNECTING
        )
        style.configure(
            'Status.Connected.TLabel',
            background=Colors.BG_DARK,
            foreground=Colors.STATUS_CONNECTED
        )
        style.configure(
            'Status.Error.TLabel',
            background=Colors.BG_DARK,
            foreground=Colors.STATUS_ERROR
        )

        # TButton (default - dark gray like rei-simulator)
        style.configure(
            'TButton',
            background=Colors.BTN_DEFAULT_BG,
            foreground=Colors.BTN_DEFAULT_FG,
            borderwidth=0,
            relief='flat',
            padding=(10, 6)
        )
        style.map(
            'TButton',
            background=[
                ('pressed', Colors.BTN_DEFAULT_PRESSED),
                ('active', Colors.BTN_DEFAULT_HOVER)
            ],
            foreground=[
                ('pressed', Colors.BTN_DEFAULT_FG),
                ('active', Colors.BTN_DEFAULT_FG)
            ]
        )

        # Active button (green - for start/record actions)
        style.configure(
            'Active.TButton',
            background=Colors.BTN_ACTIVE_BG,
            foreground=Colors.BTN_ACTIVE_FG,
            borderwidth=0,
            relief='flat',
            padding=(10, 6)
        )
        style.map(
            'Active.TButton',
            background=[
                ('pressed', Colors.BTN_ACTIVE_PRESSED),
                ('active', Colors.BTN_ACTIVE_HOVER)
            ],
            foreground=[
                ('pressed', Colors.BTN_ACTIVE_FG),
                ('active', Colors.BTN_ACTIVE_FG)
            ]
        )

        # Inactive button (muted - for disabled state)
        style.configure(
            'Inactive.TButton',
            background=Colors.BTN_INACTIVE_BG,
            foreground=Colors.BTN_INACTIVE_FG,
            borderwidth=0,
            relief='flat',
            padding=(10, 6)
        )
        style.map(
            'Inactive.TButton',
            background=[
                ('pressed', Colors.BTN_INACTIVE_HOVER),
                ('active', Colors.BTN_INACTIVE_HOVER)
            ],
            foreground=[
                ('pressed', Colors.BTN_INACTIVE_FG),
                ('active', Colors.BTN_INACTIVE_FG)
            ]
        )

        # Primary button (blue - for emphasis actions)
        style.configure(
            'Primary.TButton',
            background=Colors.BTN_PRIMARY_BG,
            foreground=Colors.BTN_PRIMARY_FG,
            borderwidth=0,
            relief='flat',
            padding=(10, 6)
        )
        style.map(
            'Primary.TButton',
            background=[
                ('pressed', Colors.PRIMARY_PRESSED),
                ('active', Colors.BTN_PRIMARY_HOVER)
            ],
            foreground=[
                ('pressed', Colors.BTN_PRIMARY_FG),
                ('active', Colors.BTN_PRIMARY_FG)
            ]
        )

        # Stop button (red - for stop actions)
        style.configure(
            'Stop.TButton',
            background=Colors.ERROR,
            foreground='#ffffff',
            borderwidth=0,
            relief='flat',
            padding=(10, 6)
        )
        style.map(
            'Stop.TButton',
            background=[
                ('pressed', Colors.ERROR_HOVER),
                ('active', Colors.ERROR_HOVER)
            ]
        )

        # TEntry
        style.configure(
            'TEntry',
            fieldbackground=Colors.BG_INPUT,
            foreground=Colors.FG_PRIMARY,
            insertcolor=Colors.FG_PRIMARY,
            bordercolor=Colors.BORDER,
            relief='flat'
        )
        style.map(
            'TEntry',
            fieldbackground=[('focus', Colors.BG_FRAME)],
            bordercolor=[('focus', Colors.PRIMARY)]
        )

        # TCheckbutton
        style.configure(
            'TCheckbutton',
            background=Colors.BG_DARK,
            foreground=Colors.FG_PRIMARY,
            indicatorbackground=Colors.BG_INPUT,
            indicatorforeground=Colors.SUCCESS
        )
        style.map(
            'TCheckbutton',
            background=[('active', Colors.BG_DARK)],
            indicatorbackground=[
                ('selected', Colors.SUCCESS),
                ('!selected', Colors.BG_INPUT)
            ]
        )

        # TSeparator
        style.configure(
            'TSeparator',
            background=Colors.BORDER
        )

        # Vertical.TScrollbar
        style.configure(
            'Vertical.TScrollbar',
            background=Colors.BG_FRAME,
            troughcolor=Colors.BG_DARKER,
            bordercolor=Colors.BORDER,
            arrowcolor=Colors.FG_SECONDARY
        )
        style.map(
            'Vertical.TScrollbar',
            background=[('active', Colors.BORDER_LIGHT)]
        )

        # TNotebook (tabs)
        style.configure(
            'TNotebook',
            background=Colors.BG_DARK,
            bordercolor=Colors.BORDER
        )
        style.configure(
            'TNotebook.Tab',
            background=Colors.BG_FRAME,
            foreground=Colors.FG_SECONDARY,
            padding=(12, 6),
            bordercolor=Colors.BORDER
        )
        style.map(
            'TNotebook.Tab',
            background=[
                ('selected', Colors.BG_DARK),
                ('active', Colors.BG_DARKER)
            ],
            foreground=[
                ('selected', Colors.FG_PRIMARY),
                ('active', Colors.FG_PRIMARY)
            ]
        )

        # TCombobox
        style.configure(
            'TCombobox',
            fieldbackground=Colors.BG_INPUT,
            background=Colors.BG_FRAME,
            foreground=Colors.FG_PRIMARY,
            arrowcolor=Colors.FG_SECONDARY,
            bordercolor=Colors.BORDER
        )
        style.map(
            'TCombobox',
            fieldbackground=[('readonly', Colors.BG_INPUT)],
            selectbackground=[('readonly', Colors.PRIMARY)],
            selectforeground=[('readonly', Colors.FG_PRIMARY)]
        )

        # TSpinbox
        style.configure(
            'TSpinbox',
            fieldbackground=Colors.BG_INPUT,
            background=Colors.BG_FRAME,
            foreground=Colors.FG_PRIMARY,
            arrowcolor=Colors.FG_SECONDARY,
            bordercolor=Colors.BORDER
        )

        # TProgressbar
        style.configure(
            'TProgressbar',
            background=Colors.SUCCESS,
            troughcolor=Colors.BG_DARKER,
            bordercolor=Colors.BORDER
        )

        # Treeview (if used)
        style.configure(
            'Treeview',
            background=Colors.BG_DARKER,
            foreground=Colors.FG_PRIMARY,
            fieldbackground=Colors.BG_DARKER,
            bordercolor=Colors.BORDER
        )
        style.configure(
            'Treeview.Heading',
            background=Colors.BG_FRAME,
            foreground=Colors.FG_PRIMARY,
            bordercolor=Colors.BORDER
        )
        style.map(
            'Treeview',
            background=[('selected', Colors.PRIMARY)],
            foreground=[('selected', Colors.FG_PRIMARY)]
        )

    @staticmethod
    def configure_scrolled_text(widget, readonly: bool = True) -> None:
        """Configure a ScrolledText widget with dark theme colors."""
        widget.configure(
            bg=Colors.BG_DARKER,
            fg=Colors.FG_PRIMARY,
            insertbackground=Colors.FG_PRIMARY,
            selectbackground=Colors.PRIMARY,
            selectforeground=Colors.FG_PRIMARY,
            relief='flat',
            borderwidth=1,
            highlightbackground=Colors.BORDER,
            highlightcolor=Colors.PRIMARY,
            highlightthickness=1
        )
        if readonly:
            widget.configure(state='disabled')

    @staticmethod
    def configure_text(widget, readonly: bool = False) -> None:
        """Configure a Text widget with dark theme colors."""
        widget.configure(
            bg=Colors.BG_DARKER,
            fg=Colors.FG_PRIMARY,
            insertbackground=Colors.FG_PRIMARY,
            selectbackground=Colors.PRIMARY,
            selectforeground=Colors.FG_PRIMARY,
            relief='flat',
            borderwidth=1,
            highlightbackground=Colors.BORDER,
            highlightcolor=Colors.PRIMARY,
            highlightthickness=1
        )
        if readonly:
            widget.configure(state='disabled')

    @staticmethod
    def configure_canvas(widget, use_dark_bg: bool = False) -> None:
        """Configure a Canvas widget with dark theme colors.

        Args:
            widget: The canvas widget to configure
            use_dark_bg: If True, use BG_DARK for consistency with frames.
                        If False (default for plots), use BG_CANVAS (black).
        """
        bg = Colors.BG_DARK if use_dark_bg else Colors.BG_CANVAS
        widget.configure(
            bg=bg,
            highlightthickness=0,
            borderwidth=0
        )

    @staticmethod
    def configure_menu(widget) -> None:
        """Configure a Menu widget with dark theme colors."""
        widget.configure(
            bg=Colors.BG_FRAME,
            fg=Colors.FG_PRIMARY,
            activebackground=Colors.PRIMARY,
            activeforeground=Colors.FG_PRIMARY,
            borderwidth=0,
            relief='flat'
        )

    @staticmethod
    def configure_toplevel(widget) -> None:
        """Configure a Toplevel widget with dark theme."""
        widget.configure(bg=Colors.BG_DARK)

    @staticmethod
    def get_status_style(state: str) -> str:
        """Get the appropriate status label style for a connection state."""
        style_map = {
            'ready': 'Status.Ready.TLabel',
            'discovered': 'Status.Ready.TLabel',
            'connecting': 'Status.Connecting.TLabel',
            'connected': 'Status.Connected.TLabel',
            'active': 'Status.Connected.TLabel',
            'error': 'Status.Error.TLabel',
        }
        return style_map.get(state.lower(), 'TLabel')

    @staticmethod
    def get_status_color(state: str) -> str:
        """Get the appropriate color for a connection state."""
        color_map = {
            'ready': Colors.STATUS_READY,
            'discovered': Colors.STATUS_READY,
            'connecting': Colors.STATUS_CONNECTING,
            'connected': Colors.STATUS_CONNECTED,
            'active': Colors.STATUS_CONNECTED,
            'error': Colors.STATUS_ERROR,
        }
        return color_map.get(state.lower(), Colors.FG_SECONDARY)


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

    def set_style(self, style: str) -> None:
        """Change button style."""
        self.configure(style=style)
