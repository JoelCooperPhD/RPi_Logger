"""Test spec for disk guard.

- Verify: blocks recording when below threshold, resumes when space recovers, and reports status to UI.
- Ensure: async checks; handles filesystem errors gracefully; logging covers threshold decisions.
- Cases: simulated low disk during active recording pauses pipeline/recorder; guard recovers after free space returns; handles unreadable filesystem stats with warning not crash.
"""
