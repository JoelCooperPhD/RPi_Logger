"""Test spec for registry state machine.

- Verify: discovered -> selected -> previewing -> recording transitions; hotplug removals stop pipelines and remove tabs; cache merge works.
- Ensure: no leaked tasks, clean cancellation, correct notifications to view adapter.
- Cases: invalid transition attempts are logged but do not raise; rapid plug/unplug debounced yet releases resources immediately; shared vs split router strategy updated when configs change.
"""
