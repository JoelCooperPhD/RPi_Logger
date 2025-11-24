"""Test spec for known cameras cache.

- Verify: cache load/save, schema handling, cache hit path avoids probe, and fallback on corruption.
- Ensure: async IO usage, logging of misses/hits, merges new capabilities/configs correctly.
- Coverage ideas:
  - Schema version bump triggers reprobe and rewrite.
  - Concurrent read/write (two loads) resolves to single cached instance with locking.
  - Capabilities merge honors preference (fresh probe overrides cache when differing).
"""
