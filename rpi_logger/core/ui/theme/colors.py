"""
Color palette for Logger UI.

Dark theme inspired by rei-simulator's design philosophy:
- Dark backgrounds for reduced eye strain
- Semantic color coding (green=good, red=error, orange=warning, blue=primary)
- High contrast text for readability
"""


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

    # Recording mode colors
    RECORDING_BG = "#8b1a1a"
    RECORDING_DOT = "#ff4444"

    # Card backgrounds
    CARD_BG = "#323232"
    CARD_BORDER = "#454545"

    # Metric thresholds
    METRIC_NORMAL = "#2ecc71"
    METRIC_WARNING = "#f39c12"
    METRIC_CRITICAL = "#e74c3c"
    METRIC_BG = "#1e1e1e"
