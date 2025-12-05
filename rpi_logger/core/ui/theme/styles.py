"""
TTK style configuration for TheLogger dark theme.
"""

from tkinter import ttk
import tkinter as tk

from .colors import Colors


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

        # Section header frame and label (for USB/WIRELESS banners)
        style.configure(
            'SectionHeader.TFrame',
            background=Colors.BG_DARKER
        )
        style.configure(
            'SectionHeader.TLabel',
            background=Colors.BG_DARKER,
            foreground=Colors.FG_PRIMARY
        )

        # Inframe style (for frames inside labelframes)
        style.configure(
            'Inframe.TFrame',
            background=Colors.BG_FRAME
        )

        # Small button style (for compact buttons like Show)
        style.configure(
            'Small.TButton',
            background=Colors.BTN_DEFAULT_BG,
            foreground=Colors.BTN_DEFAULT_FG,
            borderwidth=0,
            relief='flat',
            padding=(6, 2)
        )
        style.map(
            'Small.TButton',
            background=[
                ('pressed', Colors.BTN_DEFAULT_PRESSED),
                ('active', Colors.BTN_DEFAULT_HOVER)
            ],
            foreground=[
                ('pressed', Colors.BTN_DEFAULT_FG),
                ('active', Colors.BTN_DEFAULT_FG)
            ]
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

        # Switch style checkbutton (for toggle switches in device tiles)
        style.configure(
            'Switch.TCheckbutton',
            background=Colors.BG_FRAME,
            foreground=Colors.FG_PRIMARY,
            indicatorbackground=Colors.BG_INPUT,
            indicatorforeground=Colors.SUCCESS
        )
        style.map(
            'Switch.TCheckbutton',
            background=[('active', Colors.BG_FRAME)],
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
            bordercolor=Colors.BORDER,
            lightcolor=Colors.BG_DARK,
            darkcolor=Colors.BG_DARK
        )
        style.configure(
            'TNotebook.Tab',
            background=Colors.BG_FRAME,
            foreground=Colors.FG_SECONDARY,
            padding=(12, 6),
            bordercolor=Colors.BORDER,
            lightcolor=Colors.BG_FRAME,
            darkcolor=Colors.BG_FRAME
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
            ],
            lightcolor=[
                ('selected', Colors.BG_DARK),
                ('active', Colors.BG_DARKER)
            ],
            darkcolor=[
                ('selected', Colors.BG_DARK),
                ('active', Colors.BG_DARKER)
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
