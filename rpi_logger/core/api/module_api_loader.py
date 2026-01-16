"""
Module API loader - loads api/ packages from modules at startup.

Similar to the discovery_loader, this module scans module directories for
api/ packages and loads controller mixins and route setup functions.

Each module can provide an api/ package that exports:
- A controller mixin class with methods to add to APIController
- A route setup function to register module-specific HTTP routes
- An API_SPEC with metadata about the module's API
"""

import importlib
import inspect
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type, TYPE_CHECKING

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.core.paths import MODULES_DIR

if TYPE_CHECKING:
    from aiohttp import web

logger = get_module_logger("ModuleAPILoader")


@dataclass
class ModuleApiSpec:
    """Specification for a module's API contribution."""
    module_id: str
    version: str = "v1"
    description: str = ""


@dataclass
class LoadedModuleApi:
    """Container for a loaded module API package."""
    module_id: str
    spec: ModuleApiSpec
    mixin_class: Optional[Type] = None
    route_setup_fn: Optional[Callable[["web.Application", Any], None]] = None


class ApiRegistry:
    """
    Runtime registry for module-provided API extensions.

    Collects controller mixins and route setup functions from modules
    and provides them to the core API infrastructure.
    """

    def __init__(self) -> None:
        self._loaded_apis: Dict[str, LoadedModuleApi] = {}

    def register(self, loaded_api: LoadedModuleApi) -> None:
        """Register a loaded module API."""
        self._loaded_apis[loaded_api.module_id] = loaded_api
        logger.debug("Registered API for module: %s", loaded_api.module_id)

    @property
    def mixins(self) -> Dict[str, Type]:
        """Get all registered mixin classes, keyed by module_id."""
        return {
            module_id: api.mixin_class
            for module_id, api in self._loaded_apis.items()
            if api.mixin_class is not None
        }

    @property
    def route_setups(self) -> Dict[str, Callable[["web.Application", Any], None]]:
        """Get all registered route setup functions, keyed by module_id."""
        return {
            module_id: api.route_setup_fn
            for module_id, api in self._loaded_apis.items()
            if api.route_setup_fn is not None
        }

    def get_loaded_api(self, module_id: str) -> Optional[LoadedModuleApi]:
        """Get loaded API info for a specific module."""
        return self._loaded_apis.get(module_id)

    def get_all_specs(self) -> List[ModuleApiSpec]:
        """Get all registered API specs."""
        return [api.spec for api in self._loaded_apis.values()]


def load_module_api(module_dir: Path) -> Optional[LoadedModuleApi]:
    """
    Load api/ package from a module directory.

    Looks for:
    - API_SPEC: ModuleApiSpec with metadata
    - Mixin class: Class ending with 'ApiMixin' or 'APIMixin'
    - Route setup function: Function named 'setup_*_routes'

    Args:
        module_dir: Path to module directory (e.g., modules/GPS/)

    Returns:
        LoadedModuleApi if api/ package found, None otherwise
    """
    api_dir = module_dir / "api"
    if not api_dir.is_dir():
        return None

    init_file = api_dir / "__init__.py"
    if not init_file.exists():
        logger.warning("api/ in %s missing __init__.py", module_dir.name)
        return None

    # Build module import path
    # e.g., rpi_logger.modules.GPS.api
    module_name = module_dir.name
    import_path = f"rpi_logger.modules.{module_name}.api"

    try:
        # Import the api package
        api_module = importlib.import_module(import_path)

        # Look for API_SPEC
        spec = getattr(api_module, "API_SPEC", None)
        if spec is None:
            # Create a default spec
            spec = ModuleApiSpec(
                module_id=module_name.lower(),
                description=f"{module_name} module API"
            )

        # Look for mixin class (convention: *ApiMixin or *APIMixin)
        mixin_class = None
        for name, obj in inspect.getmembers(api_module, inspect.isclass):
            if name.endswith("ApiMixin") or name.endswith("APIMixin"):
                mixin_class = obj
                logger.debug("Found mixin class %s in %s", name, module_name)
                break

        # Look for route setup function (convention: setup_*_routes)
        route_setup_fn = None
        for name, obj in inspect.getmembers(api_module, inspect.isfunction):
            if name.startswith("setup_") and name.endswith("_routes"):
                route_setup_fn = obj
                logger.debug("Found route setup function %s in %s", name, module_name)
                break

        if mixin_class is None and route_setup_fn is None:
            logger.debug("No mixin or routes found in %s api/", module_name)
            return None

        return LoadedModuleApi(
            module_id=spec.module_id,
            spec=spec,
            mixin_class=mixin_class,
            route_setup_fn=route_setup_fn,
        )

    except ImportError as e:
        logger.error("Failed to import %s: %s", import_path, e)
        return None
    except Exception as e:
        logger.error("Error loading API from %s: %s", module_name, e)
        return None


def load_all_module_apis(modules_dir: Path = None) -> ApiRegistry:
    """
    Load api/ packages from all modules.

    Args:
        modules_dir: Path to modules directory (defaults to MODULES_DIR)

    Returns:
        ApiRegistry populated with all module APIs
    """
    if modules_dir is None:
        modules_dir = MODULES_DIR

    registry = ApiRegistry()

    if not modules_dir.exists():
        logger.error("Modules directory not found: %s", modules_dir)
        return registry

    logger.debug("Loading module APIs from: %s", modules_dir)

    for module_dir in sorted(modules_dir.iterdir()):
        if not module_dir.is_dir():
            continue

        if module_dir.name.startswith(".") or module_dir.name in (
            "__pycache__",
            "base",
        ):
            continue

        loaded_api = load_module_api(module_dir)
        if loaded_api is not None:
            registry.register(loaded_api)

    logger.debug("Loaded %d module API packages", len(registry._loaded_apis))
    return registry


# Global registry instance (lazy-loaded)
_global_api_registry: Optional[ApiRegistry] = None


def get_api_registry() -> ApiRegistry:
    """Get the global API registry, loading if needed."""
    global _global_api_registry
    if _global_api_registry is None:
        _global_api_registry = load_all_module_apis()
    return _global_api_registry


def reload_api_registry() -> ApiRegistry:
    """Reload the global API registry."""
    global _global_api_registry
    _global_api_registry = load_all_module_apis()
    return _global_api_registry


def apply_mixins_to_controller(controller: Any) -> None:
    """
    Apply all registered mixin methods to a controller instance.

    This dynamically adds methods from module mixin classes to the
    controller, allowing modules to extend the API controller.

    Args:
        controller: The APIController instance to extend
    """
    registry = get_api_registry()

    for module_id, mixin_cls in registry.mixins.items():
        logger.debug("Applying mixin from %s to controller", module_id)

        for name, method in inspect.getmembers(mixin_cls, predicate=inspect.isfunction):
            # Skip private methods
            if name.startswith("_"):
                continue

            # Bind the method to the controller instance
            bound_method = types.MethodType(method, controller)
            setattr(controller, name, bound_method)
            logger.debug("  Added method: %s", name)
