"""Sample data fixtures for Logger module testing.

Provides sample CSV data files for schema validation testing.
These fixtures can be used without physical hardware.

Usage:
    from fixtures import FIXTURES_DIR, get_sample_gps_csv

    gps_path = get_sample_gps_csv()
    # Run validation against gps_path
"""

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent

# Sample file getters
def get_sample_gps_csv() -> Path:
    return FIXTURES_DIR / "sample_gps.csv"

def get_sample_drt_sdrt_csv() -> Path:
    return FIXTURES_DIR / "sample_drt_sdrt.csv"

def get_sample_drt_wdrt_csv() -> Path:
    return FIXTURES_DIR / "sample_drt_wdrt.csv"

def get_sample_vog_svog_csv() -> Path:
    return FIXTURES_DIR / "sample_vog_svog.csv"

def get_sample_vog_wvog_csv() -> Path:
    return FIXTURES_DIR / "sample_vog_wvog.csv"

def get_sample_eyetracker_gaze_csv() -> Path:
    return FIXTURES_DIR / "sample_eyetracker_gaze.csv"

def get_sample_eyetracker_imu_csv() -> Path:
    return FIXTURES_DIR / "sample_eyetracker_imu.csv"

def get_sample_eyetracker_events_csv() -> Path:
    return FIXTURES_DIR / "sample_eyetracker_events.csv"

def get_sample_notes_csv() -> Path:
    return FIXTURES_DIR / "sample_notes.csv"
