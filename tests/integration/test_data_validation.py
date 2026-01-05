"""Data Validation Test Runner and Report Generator.

This module provides the CLI entry point for running data validation tests
and generating test reports. The actual tests have been split into separate
modules under the schema/ directory.

Usage:
    # Run all tests
    pytest tests/integration/ -v

    # Run schema tests only
    pytest tests/integration/schema/ -v

    # Generate report
    python -m tests.integration.test_data_validation --report
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List

# Try to import pytest (optional for standalone validation)
try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False
    # Stub for pytest.skip when running without pytest
    class _PytestStub:
        @staticmethod
        def skip(reason=""):
            print(f"SKIP: {reason}")
            return
        class mark:
            @staticmethod
            def parametrize(*args, **kwargs):
                def decorator(func):
                    return func
                return decorator
        @staticmethod
        def main(*args, **kwargs):
            print("pytest not installed. Use --report for standalone validation.")
            return 1
    pytest = _PytestStub()

# Import test infrastructure
from tests.infrastructure.schemas.csv_schema import (
    GPS_SCHEMA,
    DRT_SDRT_SCHEMA,
    DRT_WDRT_SCHEMA,
    VOG_SVOG_SCHEMA,
    VOG_WVOG_SCHEMA,
    EYETRACKER_GAZE_SCHEMA,
    EYETRACKER_IMU_SCHEMA,
    EYETRACKER_EVENTS_SCHEMA,
    NOTES_SCHEMA,
    ValidationResult,
    validate_csv_file,
)

from tests.infrastructure.schemas.hardware_detection import HardwareAvailability

from tests.infrastructure.fixtures import (
    get_sample_gps_csv,
    get_sample_drt_sdrt_csv,
    get_sample_drt_wdrt_csv,
    get_sample_vog_svog_csv,
    get_sample_vog_wvog_csv,
    get_sample_eyetracker_gaze_csv,
    get_sample_eyetracker_imu_csv,
    get_sample_eyetracker_events_csv,
    get_sample_notes_csv,
)


# =============================================================================
# Test Configuration
# =============================================================================

def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line(
        "markers", "hardware: mark test as requiring physical hardware"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )


# =============================================================================
# Test Reporting
# =============================================================================

@dataclass
class ValidationReport:
    """Aggregated test report."""
    timestamp: str
    schema_results: Dict[str, ValidationResult] = field(default_factory=dict)
    hardware_matrix: str = ""
    testable_modules: List[str] = field(default_factory=list)
    untestable_modules: List[str] = field(default_factory=list)
    summary: str = ""

    def generate_summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            "=== DATA VALIDATION TEST REPORT ===",
            f"Date: {self.timestamp}",
            "",
            "SCHEMA VALIDATION:",
        ]

        for name, result in self.schema_results.items():
            status = "PASS" if result.is_valid else "FAIL"
            lines.append(f"  {name}: {status} ({result.row_count} rows, {result.error_count} errors)")

        lines.extend([
            "",
            "HARDWARE MATRIX:",
            self.hardware_matrix,
            "",
            f"TESTABLE MODULES: {', '.join(self.testable_modules) or 'None'}",
            f"UNTESTABLE MODULES: {', '.join(self.untestable_modules) or 'None'}",
        ])

        # Overall status
        all_pass = all(r.is_valid for r in self.schema_results.values())
        overall = "PASS" if all_pass else "FAIL"
        lines.extend([
            "",
            f"OVERALL: {overall}",
        ])

        return "\n".join(lines)


def run_full_validation_report() -> ValidationReport:
    """Run full validation and generate report."""
    report = ValidationReport(timestamp=datetime.now().isoformat())

    # Schema validation for all fixtures
    fixtures = [
        ("GPS", GPS_SCHEMA, get_sample_gps_csv()),
        ("DRT_sDRT", DRT_SDRT_SCHEMA, get_sample_drt_sdrt_csv()),
        ("DRT_wDRT", DRT_WDRT_SCHEMA, get_sample_drt_wdrt_csv()),
        ("VOG_sVOG", VOG_SVOG_SCHEMA, get_sample_vog_svog_csv()),
        ("VOG_wVOG", VOG_WVOG_SCHEMA, get_sample_vog_wvog_csv()),
        ("EyeTracker_GAZE", EYETRACKER_GAZE_SCHEMA, get_sample_eyetracker_gaze_csv()),
        ("EyeTracker_IMU", EYETRACKER_IMU_SCHEMA, get_sample_eyetracker_imu_csv()),
        ("EyeTracker_EVENTS", EYETRACKER_EVENTS_SCHEMA, get_sample_eyetracker_events_csv()),
        ("Notes", NOTES_SCHEMA, get_sample_notes_csv()),
    ]

    for name, schema, path in fixtures:
        if path.exists():
            result = validate_csv_file(path, schema)
        else:
            result = ValidationResult(
                schema_name=name,
                file_path=str(path),
                is_valid=False,
                row_count=0,
                errors=[],
            )
        report.schema_results[name] = result

    # Hardware detection
    hw = HardwareAvailability()
    hw.detect_all()
    report.hardware_matrix = hw.availability_matrix()
    report.testable_modules = hw.get_testable_modules()
    report.untestable_modules = hw.get_untestable_modules()

    report.summary = report.generate_summary()
    return report


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    """CLI entry point for running validation and generating report."""
    import argparse

    parser = argparse.ArgumentParser(description="Data Validation Test Runner")
    parser.add_argument("--report", action="store_true", help="Generate validation report")
    parser.add_argument("--output", type=str, help="Output file for report")
    args = parser.parse_args()

    if args.report:
        report = run_full_validation_report()
        output = report.summary

        if args.output:
            with open(args.output, 'w') as f:
                f.write(output)
            print(f"Report written to: {args.output}")
        else:
            print(output)
    else:
        # Run pytest on the integration tests directory
        sys.exit(pytest.main(["tests/integration/", "-v"]))


if __name__ == "__main__":
    main()
