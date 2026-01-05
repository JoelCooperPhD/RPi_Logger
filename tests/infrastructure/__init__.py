"""Test infrastructure - mocks, fixtures, schemas, and helpers.

This package contains test support code, NOT actual tests.
"""

from pathlib import Path

INFRASTRUCTURE_DIR = Path(__file__).parent
MOCKS_DIR = INFRASTRUCTURE_DIR / "mocks"
FIXTURES_DIR = INFRASTRUCTURE_DIR / "fixtures"
SCHEMAS_DIR = INFRASTRUCTURE_DIR / "schemas"
HELPERS_DIR = INFRASTRUCTURE_DIR / "helpers"
