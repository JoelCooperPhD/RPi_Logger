"""
Known cameras persistence specification.

- Purpose: store stable camera identifiers with cached capabilities and last-used configurations (preview/record) to speed startup and prefill UI.
- Responsibilities: read/write cache file asynchronously, handle schema/versioning, merge new observations, and expose lookups for discovery/cache.
- Logging: loads/saves, cache hits/misses, schema migrations, and errors.
- Constraints: async file IO; safe concurrent access; robust against corruption (fallback to reprobe).
- Shared use: GUI and headless/CLI launches read/write the same cache so capabilities selected in GUI are immediately usable for CLI-only recording runs without reprobe.
"""
