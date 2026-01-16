"""
API route modules.

Core route modules (always present):
- system: Health, status, platform, shutdown
- modules: Module management (enable, disable, start, stop)
- session: Session and trial control
- devices: Device discovery and connection
- config: Configuration management
- logs: Log access and verification
- settings: Comprehensive settings management
- windows: Window and UI control endpoints
- testing: Testing and verification endpoints
- debug: Debug and introspection endpoints

Module-specific routes are loaded dynamically from each module's api/ package.
"""

from .system import setup_system_routes
from .modules import setup_module_routes
from .session import setup_session_routes
from .devices import setup_device_routes
from .config import setup_config_routes
from .logs import setup_log_routes
# Module-specific routes migrated to modules/*/api/:
# - GPS migrated to modules/GPS/api/
# - Notes migrated to modules/Notes/api/
# - Audio migrated to modules/Audio/api/
# - VOG migrated to modules/VOG/api/
# - EyeTracker migrated to modules/EyeTracker/api/
# - DRT migrated to modules/DRT/api/
# - Cameras migrated to modules/Cameras/api/
from .settings import setup_settings_routes
from .windows import setup_windows_routes
from .testing import setup_testing_routes
from .debug import setup_debug_routes


def setup_all_routes(app, controller):
    """Register all API routes with the application.

    First registers core routes, then loads module-provided routes from
    each module's api/ package via the module API registry.
    """
    # Core routes (always present)
    setup_system_routes(app, controller)
    setup_module_routes(app, controller)
    setup_session_routes(app, controller)
    setup_device_routes(app, controller)
    setup_config_routes(app, controller)
    setup_log_routes(app, controller)
    setup_settings_routes(app, controller)
    setup_windows_routes(app, controller)
    setup_testing_routes(app, controller)
    setup_debug_routes(app, controller)

    # Module-provided routes (loaded from module api/ packages)
    from ..module_api_loader import get_api_registry
    from rpi_logger.core.logging_utils import get_module_logger
    logger = get_module_logger("APIRoutes")

    api_registry = get_api_registry()
    for module_id, setup_fn in api_registry.route_setups.items():
        try:
            setup_fn(app, controller)
            logger.debug("Loaded routes from module: %s", module_id)
        except Exception as e:
            logger.error("Failed to load routes from %s: %s", module_id, e)


__all__ = ["setup_all_routes"]
