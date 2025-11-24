"""Test spec for retention policy.

- Verify: prunes oldest sessions beyond limit, never deletes active session, handles IO errors gracefully, and logs actions.
- Ensure: async operations and deterministic ordering for reproducibility.
- Cases: collision handling when session names overlap or have non-date suffixes; dry-run mode (if provided) to verify planned deletions; large directory counts handled via batching to avoid blocking.
"""
