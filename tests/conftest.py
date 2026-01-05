"""Shared pytest configuration and fixtures for Logger test suite."""

import sys
from pathlib import Path

import pytest

# Ensure the project root is in the path for imports
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# =============================================================================
# Pytest Configuration
# =============================================================================

def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line(
        "markers", "hardware: mark test as requiring physical hardware"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )


def pytest_addoption(parser):
    """Add custom command-line options."""
    parser.addoption(
        "--run-hardware",
        action="store_true",
        default=False,
        help="Run tests that require physical hardware",
    )


def pytest_collection_modifyitems(config, items):
    """Skip hardware tests unless --run-hardware is specified."""
    if config.getoption("--run-hardware"):
        # Run all tests including hardware
        return

    skip_hardware = pytest.mark.skip(reason="Need --run-hardware option to run")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip_hardware)


# =============================================================================
# Shared Fixtures
# =============================================================================

@pytest.fixture
def project_root() -> Path:
    """Return the project root directory."""
    return PROJECT_ROOT


@pytest.fixture
def test_data_dir() -> Path:
    """Return the test fixtures directory."""
    return PROJECT_ROOT / "tests" / "infrastructure" / "fixtures"


@pytest.fixture
def sample_gps_csv(test_data_dir) -> Path:
    """Return path to sample GPS CSV fixture."""
    return test_data_dir / "sample_gps.csv"


@pytest.fixture
def sample_drt_sdrt_csv(test_data_dir) -> Path:
    """Return path to sample sDRT CSV fixture."""
    return test_data_dir / "sample_drt_sdrt.csv"


@pytest.fixture
def sample_drt_wdrt_csv(test_data_dir) -> Path:
    """Return path to sample wDRT CSV fixture."""
    return test_data_dir / "sample_drt_wdrt.csv"


@pytest.fixture
def sample_vog_svog_csv(test_data_dir) -> Path:
    """Return path to sample sVOG CSV fixture."""
    return test_data_dir / "sample_vog_svog.csv"


@pytest.fixture
def sample_vog_wvog_csv(test_data_dir) -> Path:
    """Return path to sample wVOG CSV fixture."""
    return test_data_dir / "sample_vog_wvog.csv"


@pytest.fixture
def sample_notes_csv(test_data_dir) -> Path:
    """Return path to sample Notes CSV fixture."""
    return test_data_dir / "sample_notes.csv"


# =============================================================================
# Mock Fixtures
# =============================================================================

@pytest.fixture
def mock_serial_device():
    """Create a mock serial device for testing."""
    from tests.infrastructure.mocks.serial_mocks import MockSerialDevice
    return MockSerialDevice()


@pytest.fixture
def mock_gps_device():
    """Create a mock GPS device for testing."""
    from tests.infrastructure.mocks.serial_mocks import MockGPSDevice
    return MockGPSDevice()


@pytest.fixture
def mock_drt_device():
    """Create a mock DRT device for testing."""
    from tests.infrastructure.mocks.serial_mocks import MockDRTDevice
    return MockDRTDevice()


@pytest.fixture
def mock_vog_device():
    """Create a mock VOG device for testing."""
    from tests.infrastructure.mocks.serial_mocks import MockVOGDevice
    return MockVOGDevice()
