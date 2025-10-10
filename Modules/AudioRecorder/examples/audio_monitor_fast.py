#!/usr/bin/env python3
"""Compatibility shim that delegates to main_audio."""

import sys
from pathlib import Path

# Add parent directory to path to import main_audio
sys.path.insert(0, str(Path(__file__).parent.parent))

from main_audio import main


if __name__ == "__main__":
    main()
