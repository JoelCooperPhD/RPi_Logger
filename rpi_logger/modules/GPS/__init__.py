"""GPS module for tracking NMEA GPS receivers.

This module provides:
- NMEA sentence parsing (GPRMC, GPGGA, GPVTG, GPGLL, GPGSA, GPGSV)
- Multi-instance GPS device support
- Offline map rendering with trajectory visualization
- CSV data logging

Main components:
- gps_core: Core functionality (parsers, transports, handlers)
- gps: Runtime package for VMC integration
- view: GPS GUI view

Device assignment is handled by Logger via assign_device commands.
"""
