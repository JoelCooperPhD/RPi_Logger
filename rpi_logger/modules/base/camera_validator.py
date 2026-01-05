"""Capability validation for camera settings.

This module provides centralized validation of camera settings against actual
hardware capabilities. It serves as the single source of truth for what
configuration options are valid for a given camera.

Used by both USB and CSI camera modules to ensure:
- Resolution/FPS combinations are supported
- Camera control values are within valid ranges
- Settings loaded from cache are valid for the current camera
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from rpi_logger.modules.base.camera_types import (
    CameraCapabilities,
    CapabilityMode,
    ControlInfo,
    ControlType,
)


@dataclass(slots=True, frozen=True)
class ValidationResult:
    """Result of validating a value against capabilities.

    Attributes:
        valid: True if the original value was valid.
        corrected_value: The valid value to use (same as input if valid).
        reason: Human-readable explanation if correction was needed.
    """

    valid: bool
    corrected_value: Any
    reason: Optional[str] = None


class CapabilityValidator:
    """Validates settings against camera capabilities.

    This class is the single source of truth for what configuration options
    are valid for a camera. It should be created once per camera assignment
    and used to validate all settings before they are applied.

    Example:
        >>> caps = camera.get_capabilities()
        >>> validator = CapabilityValidator(caps)
        >>> result = validator.validate_mode((1920, 1080), 30.0)
        >>> if not result.valid:
        ...     print(f"Using {result.corrected_value} instead: {result.reason}")
    """

    def __init__(self, capabilities: CameraCapabilities) -> None:
        """Initialize validator with camera capabilities.

        Args:
            capabilities: The camera's probed or cached capabilities.
        """
        self._caps = capabilities
        self._mode_signatures: Set[Tuple[int, int, float, str]] = set()
        self._resolution_set: Set[Tuple[int, int]] = set()
        self._fps_by_resolution: Dict[Tuple[int, int], Set[float]] = {}
        self._all_fps: Set[float] = set()
        self._build_indexes()

    def _build_indexes(self) -> None:
        """Build lookup indexes from capabilities for fast validation."""
        for mode in self._caps.modes:
            sig = mode.signature()
            self._mode_signatures.add(sig)

            resolution = mode.size
            self._resolution_set.add(resolution)

            if resolution not in self._fps_by_resolution:
                self._fps_by_resolution[resolution] = set()
            self._fps_by_resolution[resolution].add(mode.fps)
            self._all_fps.add(mode.fps)

    # -------------------------------------------------------------------------
    # Mode Validation
    # -------------------------------------------------------------------------

    def validate_mode(
        self,
        resolution: Union[Tuple[int, int], str],
        fps: float,
        pixel_format: Optional[str] = None,
    ) -> ValidationResult:
        """Validate a resolution/fps combination.

        Args:
            resolution: (width, height) tuple or "WxH" string.
            fps: Frame rate.
            pixel_format: Optional pixel format to check exact match.

        Returns:
            ValidationResult with corrected_value as (resolution, fps) tuple.
        """
        # Parse resolution if string
        res_tuple = self._parse_resolution(resolution)
        if res_tuple is None:
            # Invalid resolution format - use default
            default_mode = self._caps.default_record_mode or (
                self._caps.modes[0] if self._caps.modes else None
            )
            if default_mode:
                return ValidationResult(
                    valid=False,
                    corrected_value=(default_mode.size, default_mode.fps),
                    reason=f"Invalid resolution format '{resolution}'",
                )
            return ValidationResult(
                valid=False,
                corrected_value=(resolution if isinstance(resolution, tuple) else (0, 0), fps),
                reason=f"Invalid resolution format '{resolution}'",
            )
        resolution = res_tuple

        # Check if we have any modes at all
        if not self._caps.modes:
            return ValidationResult(
                valid=False,
                corrected_value=(resolution, fps),
                reason="No capability modes available",
            )

        # Check exact match if pixel_format provided
        if pixel_format:
            sig = (resolution[0], resolution[1], float(fps), pixel_format.lower())
            if sig in self._mode_signatures:
                return ValidationResult(valid=True, corrected_value=(resolution, fps))

        # Check resolution + fps match (any format)
        if self.is_valid_resolution(resolution) and self.is_valid_fps_for_resolution(
            resolution, fps
        ):
            return ValidationResult(valid=True, corrected_value=(resolution, fps))

        # Find closest valid mode
        closest = self.find_closest_mode(resolution, fps)
        if closest:
            return ValidationResult(
                valid=False,
                corrected_value=(closest.size, closest.fps),
                reason=f"Mode {resolution[0]}x{resolution[1]}@{fps} not supported, "
                f"using {closest.size[0]}x{closest.size[1]}@{closest.fps}",
            )

        # Last resort: use default or first mode
        fallback = self._caps.default_record_mode or (
            self._caps.modes[0] if self._caps.modes else None
        )
        if fallback:
            return ValidationResult(
                valid=False,
                corrected_value=(fallback.size, fallback.fps),
                reason=f"Mode {resolution[0]}x{resolution[1]}@{fps} not supported, "
                f"using default {fallback.size[0]}x{fallback.size[1]}@{fallback.fps}",
            )

        return ValidationResult(
            valid=False,
            corrected_value=(resolution, fps),
            reason="No valid modes available",
        )

    def find_closest_mode(
        self, resolution: Union[Tuple[int, int], str], fps: float
    ) -> Optional[CapabilityMode]:
        """Find the mode closest to the requested resolution and fps.

        Prioritizes:
        1. Exact resolution match with closest FPS
        2. Closest resolution (by area) with closest FPS

        Args:
            resolution: Requested (width, height) tuple or "WxH" string.
            fps: Requested frame rate.

        Returns:
            Closest matching CapabilityMode, or None if no modes available.
        """
        if not self._caps.modes:
            return None

        # Parse resolution if string
        res_tuple = self._parse_resolution(resolution)
        if res_tuple is None:
            return None
        resolution = res_tuple

        target_area = resolution[0] * resolution[1]
        target_fps = fps

        # First try: exact resolution, closest FPS
        if resolution in self._fps_by_resolution:
            best_fps_diff = float("inf")
            best_mode = None
            for mode in self._caps.modes:
                if mode.size == resolution:
                    fps_diff = abs(mode.fps - target_fps)
                    if fps_diff < best_fps_diff:
                        best_fps_diff = fps_diff
                        best_mode = mode
            if best_mode:
                return best_mode

        # Second try: closest resolution by area, then closest FPS
        best_score = float("inf")
        best_mode = None
        for mode in self._caps.modes:
            mode_area = mode.size[0] * mode.size[1]
            # Normalize differences to make them comparable
            area_diff = abs(mode_area - target_area) / max(target_area, 1)
            fps_diff = abs(mode.fps - target_fps) / max(target_fps, 1)
            # Weight area more heavily than FPS
            score = area_diff * 2 + fps_diff
            if score < best_score:
                best_score = score
                best_mode = mode

        return best_mode

    def is_valid_resolution(
        self, resolution: Union[Tuple[int, int], str]
    ) -> bool:
        """Check if a resolution is supported.

        Args:
            resolution: (width, height) tuple or "WxH" string.

        Returns:
            True if the resolution is in the capabilities.
        """
        res_tuple = self._parse_resolution(resolution)
        if res_tuple is None:
            return False
        return res_tuple in self._resolution_set

    def is_valid_fps_for_resolution(
        self, resolution: Union[Tuple[int, int], str], fps: float
    ) -> bool:
        """Check if an FPS is valid for a given resolution.

        Args:
            resolution: (width, height) tuple or "WxH" string.
            fps: Frame rate to check.

        Returns:
            True if the fps is supported at this resolution.
        """
        res_tuple = self._parse_resolution(resolution)
        if res_tuple is None:
            return False
        available_fps = self._fps_by_resolution.get(res_tuple, set())
        # Allow small tolerance for floating point comparison
        return any(abs(f - fps) < 0.01 for f in available_fps)

    @staticmethod
    def _parse_resolution(
        resolution: Union[Tuple[int, int], str]
    ) -> Optional[Tuple[int, int]]:
        """Parse resolution from tuple or string format.

        Args:
            resolution: (width, height) tuple or "WxH" string.

        Returns:
            (width, height) tuple or None if parsing fails.
        """
        if isinstance(resolution, tuple) and len(resolution) == 2:
            return (int(resolution[0]), int(resolution[1]))
        if isinstance(resolution, str) and "x" in resolution.lower():
            try:
                parts = resolution.lower().split("x")
                return (int(parts[0]), int(parts[1]))
            except (ValueError, IndexError):
                return None
        return None

    # -------------------------------------------------------------------------
    # Control Validation
    # -------------------------------------------------------------------------

    def validate_control(self, name: str, value: Any) -> ValidationResult:
        """Validate a camera control value.

        Args:
            name: Control name (e.g., "Brightness", "Exposure").
            value: Value to validate.

        Returns:
            ValidationResult with clamped/corrected value if invalid.
        """
        info = self._caps.controls.get(name)
        if not info:
            # Unknown control - pass through unchanged
            return ValidationResult(valid=True, corrected_value=value)

        if info.read_only:
            return ValidationResult(
                valid=False,
                corrected_value=info.current_value,
                reason=f"Control '{name}' is read-only",
            )

        if info.control_type == ControlType.INTEGER:
            return self._validate_integer_control(info, value)
        elif info.control_type == ControlType.FLOAT:
            return self._validate_float_control(info, value)
        elif info.control_type == ControlType.BOOLEAN:
            return self._validate_boolean_control(info, value)
        elif info.control_type == ControlType.ENUM:
            return self._validate_enum_control(info, value)
        else:
            # TUPLE or UNKNOWN - pass through
            return ValidationResult(valid=True, corrected_value=value)

    def _validate_integer_control(
        self, info: ControlInfo, value: Any
    ) -> ValidationResult:
        """Validate an integer control value."""
        try:
            int_val = int(value)
        except (ValueError, TypeError):
            default = info.default_value if info.default_value is not None else 0
            return ValidationResult(
                valid=False,
                corrected_value=int(default),
                reason=f"Invalid integer value '{value}' for {info.name}",
            )

        clamped = int_val
        reason = None

        if info.min_value is not None and int_val < info.min_value:
            clamped = int(info.min_value)
            reason = f"{info.name} value {int_val} below minimum {info.min_value}"
        elif info.max_value is not None and int_val > info.max_value:
            clamped = int(info.max_value)
            reason = f"{info.name} value {int_val} above maximum {info.max_value}"

        # Apply step if defined
        if info.step is not None and info.step > 0 and info.min_value is not None:
            steps = round((clamped - info.min_value) / info.step)
            clamped = int(info.min_value + steps * info.step)
            if info.max_value is not None:
                clamped = min(clamped, int(info.max_value))

        return ValidationResult(
            valid=(clamped == int_val and reason is None),
            corrected_value=clamped,
            reason=reason,
        )

    def _validate_float_control(
        self, info: ControlInfo, value: Any
    ) -> ValidationResult:
        """Validate a float control value."""
        try:
            float_val = float(value)
        except (ValueError, TypeError):
            default = info.default_value if info.default_value is not None else 0.0
            return ValidationResult(
                valid=False,
                corrected_value=float(default),
                reason=f"Invalid float value '{value}' for {info.name}",
            )

        clamped = float_val
        reason = None

        if info.min_value is not None and float_val < info.min_value:
            clamped = float(info.min_value)
            reason = f"{info.name} value {float_val} below minimum {info.min_value}"
        elif info.max_value is not None and float_val > info.max_value:
            clamped = float(info.max_value)
            reason = f"{info.name} value {float_val} above maximum {info.max_value}"

        return ValidationResult(
            valid=(abs(clamped - float_val) < 1e-9 and reason is None),
            corrected_value=clamped,
            reason=reason,
        )

    def _validate_boolean_control(
        self, info: ControlInfo, value: Any
    ) -> ValidationResult:
        """Validate a boolean control value."""
        if isinstance(value, bool):
            return ValidationResult(valid=True, corrected_value=value)

        # Try to interpret string/int as boolean
        if isinstance(value, str):
            if value.lower() in ("true", "1", "yes", "on"):
                return ValidationResult(valid=True, corrected_value=True)
            elif value.lower() in ("false", "0", "no", "off"):
                return ValidationResult(valid=True, corrected_value=False)
        elif isinstance(value, (int, float)):
            return ValidationResult(valid=True, corrected_value=bool(value))

        default = (
            bool(info.default_value) if info.default_value is not None else False
        )
        return ValidationResult(
            valid=False,
            corrected_value=default,
            reason=f"Invalid boolean value '{value}' for {info.name}",
        )

    def _validate_enum_control(self, info: ControlInfo, value: Any) -> ValidationResult:
        """Validate an enum control value."""
        options = info.options or []

        # Check exact match
        if value in options:
            return ValidationResult(valid=True, corrected_value=value)

        # Try string comparison for non-string types
        str_value = str(value)
        for opt in options:
            if str(opt) == str_value:
                return ValidationResult(valid=True, corrected_value=opt)

        # Invalid - fall back to default or first option
        if info.default_value is not None and info.default_value in options:
            fallback = info.default_value
        elif options:
            fallback = options[0]
        else:
            fallback = value  # No options defined, pass through

        return ValidationResult(
            valid=False,
            corrected_value=fallback,
            reason=f"Invalid enum value '{value}' for {info.name}, "
            f"valid options: {options}",
        )

    def clamp_control_value(self, name: str, value: Any) -> Any:
        """Convenience method to clamp a control value.

        Args:
            name: Control name.
            value: Value to clamp.

        Returns:
            The clamped/corrected value.
        """
        result = self.validate_control(name, value)
        return result.corrected_value

    def get_control_info(self, name: str) -> Optional[ControlInfo]:
        """Get control metadata.

        Args:
            name: Control name.

        Returns:
            ControlInfo if the control exists, None otherwise.
        """
        return self._caps.controls.get(name)

    # -------------------------------------------------------------------------
    # Settings Validation
    # -------------------------------------------------------------------------

    def validate_settings(self, settings: Dict[str, str]) -> Dict[str, str]:
        """Validate and correct a settings dictionary.

        This is the primary method for validating user settings loaded from
        cache or applied from the UI. It ensures all settings are valid for
        the current camera.

        Args:
            settings: Dict with keys like "record_resolution", "record_fps",
                     "preview_resolution", "preview_fps", etc.

        Returns:
            Corrected settings dict with invalid values replaced.
        """
        corrected = dict(settings)

        # Validate record settings
        corrected = self._validate_mode_settings(
            corrected, "record_resolution", "record_fps"
        )

        # Validate preview settings
        corrected = self._validate_mode_settings(
            corrected, "preview_resolution", "preview_fps"
        )

        return corrected

    def _validate_mode_settings(
        self, settings: Dict[str, str], res_key: str, fps_key: str
    ) -> Dict[str, str]:
        """Validate resolution/fps pair in settings dict."""
        corrected = dict(settings)
        res_str = settings.get(res_key, "")
        fps_str = settings.get(fps_key, "")

        # Parse resolution
        resolution: Optional[Tuple[int, int]] = None
        if res_str and "x" in res_str.lower():
            try:
                parts = res_str.lower().split("x")
                resolution = (int(parts[0]), int(parts[1]))
            except (ValueError, IndexError):
                pass

        # Parse FPS
        fps: Optional[float] = None
        if fps_str:
            try:
                fps = float(fps_str)
            except ValueError:
                pass

        # If both are missing or invalid, use defaults
        if resolution is None or fps is None:
            default_mode = (
                self._caps.default_record_mode
                if "record" in res_key
                else self._caps.default_preview_mode
            )
            if default_mode is None and self._caps.modes:
                default_mode = self._caps.modes[0]

            if default_mode:
                if resolution is None:
                    corrected[res_key] = f"{default_mode.size[0]}x{default_mode.size[1]}"
                    resolution = default_mode.size
                if fps is None:
                    corrected[fps_key] = str(default_mode.fps)
                    fps = default_mode.fps
            return corrected

        # Validate the mode
        result = self.validate_mode(resolution, fps)
        if not result.valid:
            new_res, new_fps = result.corrected_value
            corrected[res_key] = f"{new_res[0]}x{new_res[1]}"
            corrected[fps_key] = str(new_fps)

        return corrected

    # -------------------------------------------------------------------------
    # Query Methods (for UI)
    # -------------------------------------------------------------------------

    def available_resolutions(self) -> List[str]:
        """Get list of available resolutions as strings.

        Returns:
            List of "WxH" strings sorted by area descending (largest first).
        """
        resolutions = sorted(
            self._resolution_set,
            key=lambda r: r[0] * r[1],
            reverse=True,
        )
        return [f"{w}x{h}" for w, h in resolutions]

    def available_fps_for_resolution(self, resolution: str) -> List[str]:
        """Get available FPS values for a specific resolution.

        Args:
            resolution: Resolution string like "1920x1080".

        Returns:
            List of FPS values as strings, sorted descending.
        """
        try:
            parts = resolution.lower().split("x")
            res_tuple = (int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            return []

        fps_set = self._fps_by_resolution.get(res_tuple, set())
        return [self._format_fps(f) for f in sorted(fps_set, reverse=True)]

    def all_fps_values(self) -> List[str]:
        """Get all unique FPS values across all resolutions.

        Returns:
            List of FPS values as strings, sorted descending.
        """
        return [self._format_fps(f) for f in sorted(self._all_fps, reverse=True)]

    @staticmethod
    def _format_fps(fps: float) -> str:
        """Format FPS value for display, showing as integer if whole number."""
        if fps == int(fps):
            return str(int(fps))
        return str(fps)

    # -------------------------------------------------------------------------
    # Capability Fingerprinting
    # -------------------------------------------------------------------------

    def fingerprint(self) -> str:
        """Generate a fingerprint for capability comparison.

        Used to detect when a different camera has been connected with the
        same stable_id. The fingerprint is a hash of the mode signatures
        and control names.

        Returns:
            String fingerprint that uniquely identifies this capability set.
        """
        modes_sig = tuple(sorted(self._mode_signatures))
        controls_sig = tuple(sorted(self._caps.controls.keys()))
        return str(hash((modes_sig, controls_sig)))

    @property
    def capabilities(self) -> CameraCapabilities:
        """Access the underlying capabilities."""
        return self._caps


__all__ = [
    "CapabilityValidator",
    "ValidationResult",
]
