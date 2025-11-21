"""
Frame conversion specification.

- Purpose: convert backend frame formats (OpenCV BGR, libcamera formats) into preview-friendly images (Tk-compatible) and record-ready arrays.
- Constraints: no blocking IO; prefer numpy ops; optional offloaded conversions via executor if heavy.
- Logging: conversions that fail or exceed timing budgets; include camera id and format info.
"""
