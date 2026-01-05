"""
API route modules.

Each module handles a category of endpoints:
- system: Health, status, platform, shutdown
- modules: Module management (enable, disable, start, stop)
- session: Session and trial control
- devices: Device discovery and connection
- config: Configuration management
- logs: Log access and verification
- cameras: Camera-specific operations (Phase 2)
- gps: GPS module-specific endpoints (Phase 2)
- notes: Notes module-specific endpoints (Phase 2)
- audio: Audio module-specific endpoints (Phase 2)
- vog: VOG module-specific endpoints (Phase 2)
- eyetracker: EyeTracker (Pupil Labs Neon) endpoints (Phase 2)
- drt: DRT (Detection Response Task) endpoints (Phase 2)
- settings: Comprehensive settings management (Phase 3)
- windows: Window and UI control endpoints (Phase 4)
- testing: Testing and verification endpoints (Phase 5)
"""

from .system import setup_system_routes
from .modules import setup_module_routes
from .session import setup_session_routes
from .devices import setup_device_routes
from .config import setup_config_routes
from .logs import setup_log_routes
from .cameras import setup_camera_routes
from .gps import setup_gps_routes
from .notes import setup_notes_routes
from .audio import setup_audio_routes
from .vog import setup_vog_routes
from .eyetracker import setup_eyetracker_routes
from .drt import setup_drt_routes
from .settings import setup_settings_routes
from .windows import setup_windows_routes
from .testing import setup_testing_routes


def setup_all_routes(app, controller):
    """Register all API routes with the application."""
    setup_system_routes(app, controller)
    setup_module_routes(app, controller)
    setup_session_routes(app, controller)
    setup_device_routes(app, controller)
    setup_config_routes(app, controller)
    setup_log_routes(app, controller)
    setup_camera_routes(app, controller)
    setup_gps_routes(app, controller)
    setup_notes_routes(app, controller)
    setup_audio_routes(app, controller)
    setup_vog_routes(app, controller)
    setup_eyetracker_routes(app, controller)
    setup_drt_routes(app, controller)
    setup_settings_routes(app, controller)
    setup_windows_routes(app, controller)
    setup_testing_routes(app, controller)


__all__ = ["setup_all_routes"]
