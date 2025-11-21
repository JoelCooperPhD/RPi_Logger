"""
Discovery cache specification.

- Purpose: consult known_cameras storage to reuse prior capabilities/configs, reducing probe latency; update cache when new devices seen.
- Responsibilities: load cache at startup, match by stable ids, provide cached capabilities/configs to registry, and persist updates asynchronously.
- Logging: cache hits/misses, stale entries pruned, write failures, and timing.
- Constraints: async file IO via storage/known_cameras helpers; never block main loop.
"""
