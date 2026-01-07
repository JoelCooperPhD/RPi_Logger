# Migration

> Cutover from CSICameras to Cameras-CSI2

## Quick Reference

| | |
|-|-|
| **Status** | See [TASKS.md](../TASKS.md) |
| **Task** | M1 |
| **Dependencies** | P7, T1, T2, T3 |
| **Effort** | Small |

## Goal

Safely migrate from the old `CSICameras` module to the new `Cameras-CSI2` module.

---

## Migration Phases

### Phase 1: Development (Current)

Both modules coexist:
```
rpi_logger/modules/
├── CSICameras/      # Current production module
└── Cameras-CSI2/    # New module under development
```

**Actions**:
- Develop and test new module
- Compare outputs with current module
- No impact on production

### Phase 2: Validation

Run both modules side-by-side:

```bash
# Terminal 1: Current module
PYTHONPATH=. python3 -m rpi_logger.modules.CSICameras --camera-index 0

# Terminal 2: New module (different camera or test mode)
PYTHONPATH=. python3 -m rpi_logger.modules.Cameras-CSI2 --camera-index 1
```

**Validation checklist**:
- [ ] Timing CSV headers byte-identical
- [ ] Timing CSV column formats match
- [ ] Video format matches (MJPEG/AVI)
- [ ] GUI looks identical (screenshot diff)
- [ ] All commands work correctly
- [ ] Performance benchmarks meet targets

### Phase 3: Cutover

1. **Rename modules**:
   ```bash
   mv CSICameras CSICameras-legacy
   mv Cameras-CSI2 CSICameras
   ```

2. **Update imports** (if any):
   - Grep for `CSICameras` imports
   - Grep for `Cameras-CSI2` references

3. **Update configuration**:
   - Check `module_settings.json`
   - Check any startup scripts

4. **Test the renamed module**:
   ```bash
   PYTHONPATH=. python3 -m rpi_logger.modules.CSICameras --camera-index 0
   ```

### Phase 4: Cleanup

After validation period (recommended: 1 week):

1. **Archive legacy module**:
   ```bash
   # Or just delete if git history is sufficient
   mv CSICameras-legacy archived/CSICameras-legacy-$(date +%Y%m%d)
   ```

2. **Update documentation**:
   - Remove legacy references
   - Update README

3. **Clean up any migration notes**

---

## Rollback Plan

If issues are found after cutover:

```bash
# Restore legacy module
mv CSICameras Cameras-CSI2-broken
mv CSICameras-legacy CSICameras

# Restart services
systemctl restart rpi-logger
```

---

## Comparison Script

Use this script to compare outputs:

```python
#!/usr/bin/env python3
"""Compare timing CSVs from old and new modules."""

import csv
import sys
from pathlib import Path

def compare_csvs(old_path: Path, new_path: Path) -> bool:
    with open(old_path) as old_f, open(new_path) as new_f:
        old_reader = csv.DictReader(old_f)
        new_reader = csv.DictReader(new_f)

        # Compare headers
        if old_reader.fieldnames != new_reader.fieldnames:
            print(f"Header mismatch!")
            print(f"Old: {old_reader.fieldnames}")
            print(f"New: {new_reader.fieldnames}")
            return False

        # Compare row count
        old_rows = list(old_reader)
        new_rows = list(new_reader)

        if len(old_rows) != len(new_rows):
            print(f"Row count mismatch: {len(old_rows)} vs {len(new_rows)}")

        print(f"Headers match: {old_reader.fieldnames}")
        print(f"Old rows: {len(old_rows)}, New rows: {len(new_rows)}")
        return True

if __name__ == "__main__":
    compare_csvs(Path(sys.argv[1]), Path(sys.argv[2]))
```

---

## Validation Checklist

- [ ] Side-by-side comparison complete
- [ ] Output format compatibility verified
- [ ] GUI visual diff < 1% (allow for timing variations)
- [ ] All integration tests pass
- [ ] Stress tests pass
- [ ] Rollback plan tested

---

## Completion Criteria

When all validation items pass and cutover is complete, update [TASKS.md](../TASKS.md).
