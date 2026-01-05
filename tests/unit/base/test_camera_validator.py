"""Unit tests for CapabilityValidator."""

import pytest

from rpi_logger.modules.base.camera_types import (
    CameraCapabilities,
    CapabilityMode,
    CapabilitySource,
    ControlInfo,
    ControlType,
)
from rpi_logger.modules.base.camera_validator import CapabilityValidator, ValidationResult


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_modes() -> list[CapabilityMode]:
    """Create sample camera modes for testing."""
    return [
        CapabilityMode(size=(1920, 1080), fps=30.0, pixel_format="MJPEG"),
        CapabilityMode(size=(1920, 1080), fps=60.0, pixel_format="MJPEG"),
        CapabilityMode(size=(1280, 720), fps=30.0, pixel_format="MJPEG"),
        CapabilityMode(size=(1280, 720), fps=60.0, pixel_format="MJPEG"),
        CapabilityMode(size=(640, 480), fps=30.0, pixel_format="MJPEG"),
    ]


@pytest.fixture
def sample_controls() -> dict[str, ControlInfo]:
    """Create sample camera controls for testing."""
    return {
        "Brightness": ControlInfo(
            name="Brightness",
            control_type=ControlType.INTEGER,
            min_value=0,
            max_value=255,
            default_value=128,
            current_value=128,
        ),
        "Contrast": ControlInfo(
            name="Contrast",
            control_type=ControlType.FLOAT,
            min_value=0.0,
            max_value=2.0,
            default_value=1.0,
            current_value=1.0,
        ),
        "AutoExposure": ControlInfo(
            name="AutoExposure",
            control_type=ControlType.BOOLEAN,
            default_value=True,
            current_value=True,
        ),
        "AwbMode": ControlInfo(
            name="AwbMode",
            control_type=ControlType.ENUM,
            default_value="Auto",
            current_value="Auto",
            options=["Auto", "Daylight", "Cloudy", "Incandescent"],
        ),
    }


@pytest.fixture
def sample_capabilities(sample_modes, sample_controls) -> CameraCapabilities:
    """Create sample capabilities for testing."""
    return CameraCapabilities(
        modes=sample_modes,
        default_preview_mode=sample_modes[2],  # 1280x720@30
        default_record_mode=sample_modes[0],  # 1920x1080@30
        source=CapabilitySource.PROBE,
        controls=sample_controls,
    )


@pytest.fixture
def validator(sample_capabilities) -> CapabilityValidator:
    """Create a validator with sample capabilities."""
    return CapabilityValidator(sample_capabilities)


# ---------------------------------------------------------------------------
# Mode Validation Tests
# ---------------------------------------------------------------------------


class TestValidateMode:
    """Tests for mode validation."""

    def test_validate_valid_mode_exact_match(self, validator):
        """Valid mode should return valid=True."""
        result = validator.validate_mode((1920, 1080), 30.0)
        assert result.valid is True
        assert result.corrected_value == ((1920, 1080), 30.0)
        assert result.reason is None

    def test_validate_valid_mode_string_resolution(self, validator):
        """String resolution should work."""
        result = validator.validate_mode("1920x1080", 30.0)
        assert result.valid is True
        assert result.corrected_value == ((1920, 1080), 30.0)

    def test_validate_invalid_resolution_corrects(self, validator):
        """Invalid resolution should return closest valid mode."""
        result = validator.validate_mode((1000, 800), 30.0)
        assert result.valid is False
        assert result.corrected_value is not None
        assert result.reason is not None

    def test_validate_invalid_fps_corrects(self, validator):
        """Invalid FPS for valid resolution should return closest mode."""
        result = validator.validate_mode((1920, 1080), 45.0)
        assert result.valid is False
        # Should correct to closest FPS (either 30 or 60)
        res, fps = result.corrected_value
        assert res == (1920, 1080)
        assert fps in (30.0, 60.0)

    def test_validate_with_pixel_format(self, validator):
        """Pixel format should be considered."""
        result = validator.validate_mode((1920, 1080), 30.0, pixel_format="MJPEG")
        assert result.valid is True


class TestIsValidResolution:
    """Tests for resolution validation."""

    def test_valid_resolution_tuple(self, validator):
        """Valid resolution tuple should return True."""
        assert validator.is_valid_resolution((1920, 1080)) is True
        assert validator.is_valid_resolution((1280, 720)) is True
        assert validator.is_valid_resolution((640, 480)) is True

    def test_valid_resolution_string(self, validator):
        """Valid resolution string should return True."""
        assert validator.is_valid_resolution("1920x1080") is True
        assert validator.is_valid_resolution("1280x720") is True

    def test_invalid_resolution(self, validator):
        """Invalid resolution should return False."""
        assert validator.is_valid_resolution((1000, 800)) is False
        assert validator.is_valid_resolution("1000x800") is False


class TestIsValidFpsForResolution:
    """Tests for FPS validation per resolution."""

    def test_valid_fps_for_resolution(self, validator):
        """Valid FPS for resolution should return True."""
        assert validator.is_valid_fps_for_resolution((1920, 1080), 30.0) is True
        assert validator.is_valid_fps_for_resolution((1920, 1080), 60.0) is True

    def test_invalid_fps_for_resolution(self, validator):
        """Invalid FPS for resolution should return False."""
        assert validator.is_valid_fps_for_resolution((1920, 1080), 120.0) is False
        assert validator.is_valid_fps_for_resolution((1920, 1080), 15.0) is False

    def test_string_resolution(self, validator):
        """String resolution should work."""
        assert validator.is_valid_fps_for_resolution("1920x1080", 30.0) is True


class TestFindClosestMode:
    """Tests for finding closest valid mode."""

    def test_exact_match(self, validator):
        """Exact match should return that mode."""
        mode = validator.find_closest_mode((1920, 1080), 30.0)
        assert mode is not None
        assert mode.size == (1920, 1080)
        assert mode.fps == 30.0

    def test_closest_by_resolution(self, validator):
        """Should find closest resolution."""
        mode = validator.find_closest_mode((1800, 1000), 30.0)
        assert mode is not None
        # Should pick 1920x1080 or 1280x720 (closest by pixel count)

    def test_closest_by_fps(self, validator):
        """Should find closest FPS for given resolution."""
        mode = validator.find_closest_mode((1920, 1080), 45.0)
        assert mode is not None
        assert mode.size == (1920, 1080)
        # Should pick 30 or 60 (whichever is closer)


# ---------------------------------------------------------------------------
# Control Validation Tests
# ---------------------------------------------------------------------------


class TestValidateControl:
    """Tests for control validation."""

    def test_validate_integer_in_range(self, validator):
        """Integer in range should be valid."""
        result = validator.validate_control("Brightness", 100)
        assert result.valid is True
        assert result.corrected_value == 100

    def test_validate_integer_above_max(self, validator):
        """Integer above max should be clamped."""
        result = validator.validate_control("Brightness", 300)
        assert result.valid is False
        assert result.corrected_value == 255  # max value

    def test_validate_integer_below_min(self, validator):
        """Integer below min should be clamped."""
        result = validator.validate_control("Brightness", -10)
        assert result.valid is False
        assert result.corrected_value == 0  # min value

    def test_validate_float_in_range(self, validator):
        """Float in range should be valid."""
        result = validator.validate_control("Contrast", 1.5)
        assert result.valid is True
        assert result.corrected_value == 1.5

    def test_validate_float_above_max(self, validator):
        """Float above max should be clamped."""
        result = validator.validate_control("Contrast", 3.0)
        assert result.valid is False
        assert result.corrected_value == 2.0  # max value

    def test_validate_boolean(self, validator):
        """Boolean should pass through."""
        result = validator.validate_control("AutoExposure", False)
        assert result.valid is True
        assert result.corrected_value is False

    def test_validate_enum_valid(self, validator):
        """Valid enum option should be accepted."""
        result = validator.validate_control("AwbMode", "Daylight")
        assert result.valid is True
        assert result.corrected_value == "Daylight"

    def test_validate_enum_invalid(self, validator):
        """Invalid enum option should fall back to default."""
        result = validator.validate_control("AwbMode", "InvalidMode")
        assert result.valid is False
        assert result.corrected_value == "Auto"  # default value

    def test_validate_unknown_control(self, validator):
        """Unknown control should pass through unchanged."""
        result = validator.validate_control("UnknownControl", 42)
        assert result.valid is True
        assert result.corrected_value == 42


class TestClampControlValue:
    """Tests for control value clamping."""

    def test_clamp_integer(self, validator):
        """Integer should be clamped to range."""
        assert validator.clamp_control_value("Brightness", 300) == 255
        assert validator.clamp_control_value("Brightness", -10) == 0
        assert validator.clamp_control_value("Brightness", 100) == 100

    def test_clamp_float(self, validator):
        """Float should be clamped to range."""
        assert validator.clamp_control_value("Contrast", 5.0) == 2.0
        assert validator.clamp_control_value("Contrast", -1.0) == 0.0

    def test_clamp_unknown(self, validator):
        """Unknown control should return value unchanged."""
        assert validator.clamp_control_value("Unknown", 999) == 999


# ---------------------------------------------------------------------------
# Settings Validation Tests
# ---------------------------------------------------------------------------


class TestValidateSettings:
    """Tests for full settings validation."""

    def test_validate_valid_settings(self, validator):
        """Valid settings should pass through."""
        settings = {
            "preview_resolution": "1920x1080",
            "preview_fps": "30",
            "record_resolution": "1280x720",
            "record_fps": "60",
        }
        result = validator.validate_settings(settings)
        assert result["preview_resolution"] == "1920x1080"
        assert result["preview_fps"] == "30"

    def test_validate_invalid_resolution_corrects(self, validator):
        """Invalid resolution should be corrected."""
        settings = {
            "preview_resolution": "1000x800",
            "preview_fps": "30",
            "record_resolution": "1280x720",
            "record_fps": "60",
        }
        result = validator.validate_settings(settings)
        assert result["preview_resolution"] != "1000x800"
        # Should be corrected to a valid resolution

    def test_validate_invalid_fps_corrects(self, validator):
        """Invalid FPS should be corrected."""
        settings = {
            "preview_resolution": "1920x1080",
            "preview_fps": "120",  # Invalid for this resolution
            "record_resolution": "1280x720",
            "record_fps": "60",
        }
        result = validator.validate_settings(settings)
        # FPS should be corrected to valid value (may have .0 suffix)
        fps_val = float(result["preview_fps"])
        assert fps_val in (30.0, 60.0)

    def test_validate_empty_settings(self, validator):
        """Empty settings should use defaults from capabilities."""
        settings = {}
        result = validator.validate_settings(settings)
        # Should have been filled with capability defaults
        assert "preview_resolution" in result or "record_resolution" in result

    def test_preserves_unrelated_settings(self, validator):
        """Non-capability settings should be preserved."""
        settings = {
            "preview_resolution": "1920x1080",
            "preview_fps": "30",
            "overlay": "true",
            "custom_setting": "value",
        }
        result = validator.validate_settings(settings)
        assert result.get("overlay") == "true"
        assert result.get("custom_setting") == "value"


# ---------------------------------------------------------------------------
# Query Method Tests
# ---------------------------------------------------------------------------


class TestAvailableResolutions:
    """Tests for available resolutions query."""

    def test_returns_all_resolutions(self, validator):
        """Should return all unique resolutions."""
        resolutions = validator.available_resolutions()
        assert "1920x1080" in resolutions
        assert "1280x720" in resolutions
        assert "640x480" in resolutions
        assert len(resolutions) == 3  # Unique resolutions

    def test_sorted_by_size(self, validator):
        """Should be sorted by resolution size (largest first)."""
        resolutions = validator.available_resolutions()
        assert resolutions[0] == "1920x1080"
        assert resolutions[-1] == "640x480"


class TestAvailableFpsForResolution:
    """Tests for FPS query per resolution."""

    def test_returns_fps_for_resolution(self, validator):
        """Should return valid FPS values for resolution."""
        fps_list = validator.available_fps_for_resolution("1920x1080")
        assert "30" in fps_list
        assert "60" in fps_list

    def test_returns_empty_for_invalid_resolution(self, validator):
        """Should return empty list for invalid resolution."""
        fps_list = validator.available_fps_for_resolution("1000x800")
        assert fps_list == []


class TestAllFpsValues:
    """Tests for all FPS values query."""

    def test_returns_all_fps(self, validator):
        """Should return all unique FPS values."""
        fps_list = validator.all_fps_values()
        assert "30" in fps_list
        assert "60" in fps_list


# ---------------------------------------------------------------------------
# Fingerprint Tests
# ---------------------------------------------------------------------------


class TestFingerprint:
    """Tests for capability fingerprinting."""

    def test_fingerprint_consistent(self, sample_capabilities):
        """Same capabilities should produce same fingerprint."""
        v1 = CapabilityValidator(sample_capabilities)
        v2 = CapabilityValidator(sample_capabilities)
        assert v1.fingerprint() == v2.fingerprint()

    def test_fingerprint_differs_with_different_modes(self, sample_capabilities):
        """Different modes should produce different fingerprint."""
        v1 = CapabilityValidator(sample_capabilities)

        # Create different capabilities
        different_caps = CameraCapabilities(
            modes=[CapabilityMode(size=(800, 600), fps=25.0, pixel_format="YUYV")],
            source=CapabilitySource.PROBE,
        )
        v2 = CapabilityValidator(different_caps)

        assert v1.fingerprint() != v2.fingerprint()

    def test_fingerprint_differs_with_different_controls(self, sample_modes):
        """Different controls should produce different fingerprint."""
        caps1 = CameraCapabilities(
            modes=sample_modes,
            controls={"Brightness": ControlInfo(name="Brightness", control_type=ControlType.INTEGER)},
        )
        caps2 = CameraCapabilities(
            modes=sample_modes,
            controls={"Contrast": ControlInfo(name="Contrast", control_type=ControlType.INTEGER)},
        )

        v1 = CapabilityValidator(caps1)
        v2 = CapabilityValidator(caps2)

        assert v1.fingerprint() != v2.fingerprint()


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_capabilities(self):
        """Empty capabilities should not crash."""
        caps = CameraCapabilities(modes=[], controls={})
        validator = CapabilityValidator(caps)

        # Should handle gracefully
        assert validator.available_resolutions() == []
        assert validator.all_fps_values() == []
        assert validator.find_closest_mode((1920, 1080), 30.0) is None

    def test_single_mode(self):
        """Single mode should work correctly."""
        caps = CameraCapabilities(
            modes=[CapabilityMode(size=(640, 480), fps=30.0, pixel_format="MJPEG")],
        )
        validator = CapabilityValidator(caps)

        assert validator.available_resolutions() == ["640x480"]
        assert validator.all_fps_values() == ["30"]
        assert validator.is_valid_resolution("640x480") is True
        assert validator.is_valid_resolution("1920x1080") is False

    def test_none_values_in_settings(self, validator):
        """None values in settings should be handled."""
        settings = {
            "preview_resolution": None,
            "preview_fps": None,
        }
        result = validator.validate_settings(settings)
        # Should not crash and should return valid settings
        assert isinstance(result, dict)
