"""
Connections Menu - Clean UI component for connection type selection.

This component renders the Connections menu based on data from
DeviceUIController. It has no domain knowledge - it just renders
MenuSectionData and wires callbacks.

Structure:
    Connections
    ├─ VOG
    │  ├─ ☑ USB
    │  └─ ☑ XBee
    ├─ DRT
    │  ├─ ☑ USB
    │  └─ ☑ XBee
    ...
"""

import tkinter as tk
from typing import TYPE_CHECKING, Callable, Optional

from rpi_logger.core.logging_utils import get_module_logger
from .device_controller import DeviceUIController, MenuSectionData, MenuItemData

if TYPE_CHECKING:
    from .theme.styles import Theme

logger = get_module_logger("ConnectionsMenu")


class ConnectionsMenu:
    """
    Renders the Connections menu from controller data.

    This component:
    - Gets menu structure from DeviceUIController
    - Renders tkinter Menu widgets
    - Wires checkbox callbacks to controller
    - Re-renders when controller notifies of changes

    No domain logic - just UI rendering.
    """

    def __init__(
        self,
        parent_menu: tk.Menu,
        controller: DeviceUIController,
        theme_configurer: Optional[Callable[[tk.Menu], None]] = None,
    ):
        """
        Initialize the connections menu.

        Args:
            parent_menu: The parent menubar to add this menu to
            controller: The UI controller providing data
            theme_configurer: Optional function to configure menu theme
        """
        self._parent = parent_menu
        self._controller = controller
        self._theme_configurer = theme_configurer

        # Menu widget and variables
        self._menu: tk.Menu | None = None
        self._submenus: dict[str, tk.Menu] = {}
        self._vars: dict[str, tk.BooleanVar] = {}

        # Register for updates
        controller.add_ui_observer(self._on_data_changed)

        # Initial build
        self._build()

    def _build(self) -> None:
        """Build the menu from controller data."""
        # Create main menu
        self._menu = tk.Menu(self._parent, tearoff=0)
        if self._theme_configurer:
            self._theme_configurer(self._menu)

        self._parent.add_cascade(label="Connections", menu=self._menu)

        # Get data from controller
        sections = self._controller.get_menu_data()

        # Build sections
        for section in sections:
            self._build_section(section)

    def _build_section(self, section: MenuSectionData) -> None:
        """Build a single menu section (family submenu)."""
        if not self._menu:
            return

        # Create submenu
        submenu = tk.Menu(self._menu, tearoff=0)
        if self._theme_configurer:
            self._theme_configurer(submenu)

        self._menu.add_cascade(label=section.label, menu=submenu)
        self._submenus[section.label] = submenu

        # Add items
        for item in section.items:
            self._add_item(submenu, section.label, item)

    def _add_item(self, submenu: tk.Menu, section_label: str, item: MenuItemData) -> None:
        """Add a single checkbox item to a submenu."""
        # Create variable for checkbox
        key = f"{section_label}:{item.label}"
        var = tk.BooleanVar(value=item.checked)
        self._vars[key] = var

        # Add checkbox with callback
        submenu.add_checkbutton(
            label=item.label,
            variable=var,
            command=lambda cb=item.on_toggle, v=var: cb(v.get()),
        )

    def _on_data_changed(self) -> None:
        """Called when controller data changes - update checkbox states."""
        sections = self._controller.get_menu_data()

        for section in sections:
            for item in section.items:
                key = f"{section.label}:{item.label}"
                if key in self._vars:
                    # Update variable without triggering callback
                    self._vars[key].set(item.checked)

    def rebuild(self) -> None:
        """
        Completely rebuild the menu.

        Call this if the available connections change (rare).
        """
        # Remove old menu
        if self._menu:
            # Find index of Connections menu and delete
            try:
                index = self._parent.index("Connections")
                self._parent.delete(index)
            except tk.TclError:
                pass

        # Clear state
        self._menu = None
        self._submenus.clear()
        self._vars.clear()

        # Rebuild
        self._build()

    def destroy(self) -> None:
        """Clean up the menu."""
        self._controller.remove_ui_observer(self._on_data_changed)
        if self._menu:
            self._menu.destroy()
        self._submenus.clear()
        self._vars.clear()
