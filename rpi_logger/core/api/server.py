"""
API Server - aiohttp-based REST server for Logger System.

This server runs alongside the GUI, providing HTTP endpoints for
programmatic control of the application.
"""

import asyncio
from typing import Optional

from aiohttp import web

from rpi_logger.core.logging_utils import get_module_logger

from .controller import APIController
from .middleware import (
    localhost_only_middleware,
    error_handling_middleware,
    request_logging_middleware,
    set_debug_mode,
)
from .routes import setup_all_routes


logger = get_module_logger("APIServer")


class APIServer:
    """
    REST API server for the Logger system.

    Provides HTTP endpoints for complete programmatic control of the
    application, including module management, session control, device
    management, and log access.

    The server uses aiohttp and integrates with the existing asyncio
    event loop, allowing it to run alongside the Tkinter GUI.
    """

    def __init__(
        self,
        controller: APIController,
        host: str = "127.0.0.1",
        port: int = 8080,
        localhost_only: bool = True,
        debug: bool = False,
    ):
        """
        Initialize the API server.

        Args:
            controller: APIController instance wrapping LoggerSystem
            host: Host to bind to (default: localhost only)
            port: Port to bind to (default: 8080)
            localhost_only: If True, reject requests from non-localhost
            debug: If True, enable verbose error responses and request logging
        """
        self.controller = controller
        self.host = host
        self.port = port
        self.localhost_only = localhost_only
        self.debug = debug

        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._running = False

        # Set debug mode in middleware
        set_debug_mode(debug)

    def _create_app(self) -> web.Application:
        """Create and configure the aiohttp application."""
        # Build middleware chain: localhost check -> request logging -> error handling
        middlewares = [error_handling_middleware]

        # Add request logging (always, but verbosity depends on debug mode)
        middlewares.insert(0, request_logging_middleware)

        if self.localhost_only:
            middlewares.insert(0, localhost_only_middleware)

        app = web.Application(middlewares=middlewares)

        # Store controller reference for routes
        app["controller"] = self.controller

        # Register all routes
        setup_all_routes(app, self.controller)

        return app

    async def start(self) -> None:
        """Start the API server (non-blocking)."""
        if self._running:
            logger.warning("API server already running")
            return

        self._app = self._create_app()
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()

        self._running = True
        mode_info = " (debug mode)" if self.debug else ""
        logger.info("API server started on http://%s:%d%s", self.host, self.port, mode_info)

    async def stop(self) -> None:
        """Stop the API server gracefully."""
        if not self._running:
            return

        logger.info("Stopping API server...")

        if self._site:
            await self._site.stop()
            self._site = None

        if self._runner:
            await self._runner.cleanup()
            self._runner = None

        self._app = None
        self._running = False

        logger.info("API server stopped")

    @property
    def is_running(self) -> bool:
        """Check if the server is running."""
        return self._running

    @property
    def url(self) -> str:
        """Get the server URL."""
        return f"http://{self.host}:{self.port}"
