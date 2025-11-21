"""
State and data model specification for runtime layer.

- Data structures (frozen dataclasses/typed dicts):
  - CameraId: `backend` ("usb"|"picam"|"mock"), `stable_id` (serial or connector+sensor), optional `friendly_name`, optional `dev_path` for USB.
  - CameraDescriptor: CameraId + `hw_model`, `location_hint` (e.g., usb-port path), `seen_at` monotonic ts.
  - CapabilityMode: `size` (width, height), `fps`, `pixel_format`, optional `controls` (dict of normalized control ranges) mirroring Picamera2/libcamera naming where applicable.
  - CameraCapabilities: `modes` list[CapabilityMode], `default_preview_mode`, `default_record_mode`, `timestamp_ms` when probed, `source` ("probe"|"cache"), `limits` (max_fps per size), `color_formats` allowed.
  - SelectedConfigs: `preview` + `record` ModeSelection (mode ref + requested overlay flags, color_convert toggle, target_fps cap), optional `storage_profile`.
  - RuntimeStatus enum: `discovered`, `selected`, `previewing`, `recording`, `error`.
  - CameraRuntimeState: `descriptor`, `capabilities`, `selected_configs`, `status`, `tasks` (task ids/handles), metrics snapshot refs (fps, timing), `last_error`.

- Responsibilities:
  - Normalize capabilities from discovery/backends into CapabilityMode objects (clamp to numeric types, drop duplicates, map backend pixel formats to canonical names such as "RGB", "YUV420").
  - Merge cached capabilities/configs with fresh probe results using preference order: fresh probe wins size/fps, cache can prefill defaults if compatible.
  - Provide serialization helpers for known_cameras cache (JSON-safe) including schema version and checksum to detect stale entries.
  - Offer selectors for preferred preview/record modes (e.g., prefer 640x480@30 for preview unless overridden) while respecting backend-specific constraints.

- API sketches (pure functions):
  - `merge_capabilities(probed, cached) -> CameraCapabilities`
  - `select_modes(capabilities, requested_preview, requested_record) -> SelectedConfigs` with clamping + warnings.
  - `serialize_camera_state(state) -> dict`; `deserialize_camera_state(data) -> CameraRuntimeState` with validation and logging hooks.
  - `ensure_mode_supported(capabilities, requested) -> (mode, warning)` used by controller/capture_settings.

- Constraints: lightweight, pure-Python; no blocking IO; safe to use across tasks; avoid carrying live backend handles here (state is descriptive only).
- Logging: creation/updates of descriptors/capabilities and any normalization/clamping decisions; log schema version mismatches on deserialize.
"""
