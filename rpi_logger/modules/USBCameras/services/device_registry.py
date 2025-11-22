"""Device discovery, probing, and selection management for USB cameras."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Iterable, Optional

try:
    import cv2
except Exception:  # pragma: no cover - OpenCV is optional during dev
    cv2 = None

from rpi_logger.core.logging_utils import ensure_structured_logger
from rpi_logger.modules.USBCameras.controller.device_manager import USBCameraDiscovery
from rpi_logger.modules.USBCameras.io.capture.usb_camera import USBCameraInfo
from rpi_logger.modules.USBCameras.ui import USBCameraViewAdapter


class DeviceRegistry:
    """Coordinates discovery/probing and keeps the view menu in sync with device selection."""

    def __init__(
        self,
        *,
        discovery: USBCameraDiscovery,
        view_adapter: Optional[USBCameraViewAdapter],
        logger,
    ) -> None:
        self.discovery = discovery
        self.view_adapter = view_adapter
        self.logger = ensure_structured_logger(
            logger,
            component="DeviceRegistry",
            fallback_name=f"{__name__}.DeviceRegistry",
        )
        self._discovered_infos: list[USBCameraInfo] = []
        self._menu_index_map: dict[int, USBCameraInfo] = {}
        self._selected_devices: set[str] = set()
        self._on_selection_changed: Optional[Callable[[], Awaitable[None]]] = None

    # ------------------------------------------------------------------
    # Hooks and helpers

    def attach_view(self, adapter: Optional[USBCameraViewAdapter]) -> None:
        self.view_adapter = adapter

    def on_selection_changed(self, handler: Callable[[], Awaitable[None]]) -> None:
        self._on_selection_changed = handler

    @property
    def discovered_infos(self) -> list[USBCameraInfo]:
        return list(self._discovered_infos)

    @property
    def selected_devices(self) -> set[str]:
        return set(self._selected_devices)

    def clear(self) -> None:
        self._discovered_infos.clear()
        self._selected_devices.clear()
        self._menu_index_map.clear()

    # ------------------------------------------------------------------
    # Discovery + probing

    @staticmethod
    def parse_indices(raw: Optional[str]) -> list[int]:
        return USBCameraDiscovery.parse_indices(raw)

    def discover_candidates(self, *, requested: Optional[Iterable[int]], max_devices: int) -> list[USBCameraInfo]:
        return self.discovery.discover(requested=requested, max_devices=max_devices)

    async def probe_devices(self, infos: list[USBCameraInfo], limit: int) -> list[USBCameraInfo]:
        """Lightweight open/read probes to filter real cameras."""

        if cv2 is None:
            self.logger.warning("OpenCV unavailable; skipping device probes")
            return infos

        async def probe(info: USBCameraInfo) -> tuple[USBCameraInfo, bool, str]:
            def _do_probe() -> tuple[bool, str]:
                backends = [getattr(cv2, "CAP_V4L2", None), None]
                for backend in backends:
                    try:
                        cap = cv2.VideoCapture(info.index, backend) if backend is not None else cv2.VideoCapture(info.index)
                    except Exception as exc:  # pragma: no cover - defensive
                        return False, f"open failed ({exc})"
                    if not cap or not cap.isOpened():
                        try:
                            if cap:
                                cap.release()
                        except Exception:
                            pass
                        continue
                    try:
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
                        ok, frame = cap.read()
                    except Exception as exc:  # pragma: no cover - defensive
                        ok = False
                        frame = None
                        reason = f"read failed ({exc})"
                    else:
                        reason = "ok" if ok and frame is not None else "empty frame"
                    try:
                        cap.release()
                    except Exception:
                        pass
                    return bool(ok and frame is not None), reason
                return False, "not opened"

            try:
                ok, reason = await asyncio.wait_for(asyncio.to_thread(_do_probe), timeout=1.25)
            except asyncio.TimeoutError:
                ok, reason = False, "probe timeout"
            return info, ok, reason

        results = await asyncio.gather(*(probe(info) for info in infos[:limit]), return_exceptions=False)
        good: list[USBCameraInfo] = []
        for info, ok, reason in results:
            if ok:
                good.append(info)
                self.logger.info("Probe success -> %s (%s)", info.path, info.name)
            else:
                self.logger.debug("Probe failed -> %s (%s): %s", info.path, info.name, reason)
        if good:
            self.logger.info("Probed %d/%d usable cameras", len(good), len(results))
        else:
            self.logger.warning("No probed cameras returned a frame; skipping initialization to keep UI alive")
        return good

    # ------------------------------------------------------------------
    # Selection + menu helpers

    def set_discovered_infos(
        self,
        infos: list[USBCameraInfo],
        *,
        max_cameras: int,
    ) -> None:
        self._discovered_infos = infos
        self._sync_camera_menu(max_cameras)

    def select_default(self, *, max_cameras: int) -> list[USBCameraInfo]:
        if not self._discovered_infos:
            return []
        selected = [info for info in self._discovered_infos if info.path in self._selected_devices]
        if not selected:
            selected = self._discovered_infos[:max_cameras]
            self._selected_devices = {info.path for info in selected}
        return selected

    def _sync_camera_menu(self, max_cameras: int) -> None:
        adapter = self.view_adapter
        if adapter is None:
            return
        adapter.reset_camera_toggles()
        self._menu_index_map.clear()
        for menu_idx, info in enumerate(self._discovered_infos):
            label = f"{info.name} ({info.path})"
            enabled = (
                info.path in self._selected_devices
                if self._selected_devices
                else menu_idx < max_cameras
            )
            adapter.register_camera_toggle(
                menu_idx,
                label,
                enabled,
                lambda idx=menu_idx, enabled=None: self._handle_camera_menu_toggle(idx, enabled),
            )
            self._menu_index_map[menu_idx] = info

    async def _handle_camera_menu_toggle(self, menu_index: int, enabled: Optional[bool] = None) -> None:
        info = self._menu_index_map.get(menu_index)
        if info is None:
            return

        adapter = self.view_adapter
        var = adapter._camera_toggle_vars.get(menu_index) if adapter else None  # type: ignore[attr-defined]
        if enabled is None:
            enabled = bool(var.get()) if var is not None else False
        if enabled:
            self._selected_devices.add(info.path)
        else:
            self._selected_devices.discard(info.path)
        self.logger.info(
            "Camera selection updated | %s -> %s | total_selected=%s",
            info.path,
            enabled,
            len(self._selected_devices),
        )
        if self._on_selection_changed:
            await self._on_selection_changed()


__all__ = ["DeviceRegistry"]
