"""
Metadata specification.

- Purpose: define metadata persisted with recordings (camera id, backend, mode, timing stats), serialize/deserialize helpers.
- Integration: used by recorder and CSV logger; ties into known_cameras persistence.
- Fields: session id, camera id, backend, selected preview/record modes, overlays enabled, timestamp source, fps targets, capture latency stats, disk guard status flags, and software versions.
- API sketch: `build_metadata(camera_state, configs, paths) -> dict`, `to_json(metadata) -> str`, `from_json(str) -> metadata` with validation and defaults for missing fields.
- Constraints: pure logic; no blocking IO; stable schema with versioning for forwards/backwards compatibility.
- Logging: serialization errors and mismatches; emit warnings when optional fields omitted.
"""
