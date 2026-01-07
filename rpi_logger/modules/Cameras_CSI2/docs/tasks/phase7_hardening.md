# Phase 7: Hardening

> Production readiness

## Quick Reference

| | |
|-|-|
| **Status** | See [TASKS.md](../TASKS.md) |
| **Task** | P7 (single task) |
| **Dependencies** | P6 |
| **Effort** | Medium |
| **Key Specs** | [debugging.md](../specs/debugging.md) |

## Goal

Make the module production-ready with comprehensive error handling and graceful degradation.

---

## Deliverables

### 1. Comprehensive Error Handling

**Camera disconnection during recording**:
- Detect via frame timeout (no frame in 2 seconds)
- Stop recording gracefully
- Send `device_error` status
- Attempt reconnection with backoff

**I/O errors**:
- Wrap all file operations in try/except
- Log errors with context
- Continue operation where possible

### 2. Graceful Degradation

**Under CPU load**:
- Preview drops before recording
- Metrics update frequency reduced
- Log dropped frames to frame_drops.jsonl

**Buffer overflow**:
- Drop oldest frames (not newest)
- Log drop events with reason
- Continue recording

### 3. Log Rotation

| Log File | Max Size | Backups | Total Max |
|----------|----------|---------|-----------|
| `csicameras.log` | 10 MB | 5 | 50 MB |
| `commands.jsonl` | 5 MB | 3 | 15 MB |
| `frame_drops.jsonl` | 5 MB | 3 | 15 MB |

### 4. Shutdown Sequence

```python
async def stop(self):
    # 1. Stop accepting new commands
    self._accepting_commands = False

    # 2. Stop recording (if active)
    if self._recording_session:
        await self._recording_session.stop()

    # 3. Stop capture
    await self._source.stop()

    # 4. Flush logs
    await self._flush_logs()

    # 5. Send final status
    await self._send_status("shutdown_complete")
```

---

## Edge Cases to Handle

| Case | Handling |
|------|----------|
| Zero-length recording | Don't create empty files |
| Rapid start/stop | Queue commands, process sequentially |
| Camera already in use | Report error, don't crash |
| Invalid session directory | Create if possible, error if not |
| Disk full | Stop recording, report error |

---

## Validation Checklist

- [ ] Fault injection: Camera disconnect during recording
- [ ] Memory test: No leaks over 24 hours (valgrind or tracemalloc)
- [ ] Edge case: Zero-length recordings handled correctly
- [ ] Edge case: Rapid start/stop (100 cycles) without errors
- [ ] Log rotation: Verify files don't grow unbounded
- [ ] Graceful shutdown: Clean exit on SIGTERM

---

## Completion Criteria

When all validation items pass, update [TASKS.md](../TASKS.md).
