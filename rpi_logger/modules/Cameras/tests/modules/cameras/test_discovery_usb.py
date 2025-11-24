"""Test spec for USB discovery.

- Verify: detects real devices, handles hotplug remove/add, respects policy/cache, logs appropriately, and surfaces capabilities.
- Ensure: async probe doesn't block, errors handled gracefully, deduplication works.
- Cases: permissions error on /dev/video* is logged and skipped; rapid plug/unplug coalesced; cache hit skips probe when policy allows; capability normalization matches expected canonical formats.
"""
