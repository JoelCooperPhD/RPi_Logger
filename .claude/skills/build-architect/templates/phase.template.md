# Phase [N]: [PHASE_NAME]

> [Brief one-line description]

## Quick Reference

| | |
|-|-|
| **Status** | See [TASKS.md](../TASKS.md) |
| **Sub-tasks** | P[N].1, P[N].2, ... |
| **Dependencies** | [List or "None"] |
| **Effort** | [Small/Medium/Large] |
| **Key Specs** | [Link to specs] |

## Goal

[One sentence describing the outcome of this phase]

---

## Sub-Tasks

### P[N].1: [Task Name]

**File**: `path/to/file.py` (~[N] lines)

[Brief description of what this creates]

```python
# Key interface or class signature
class ClassName:
    def method(self, param: Type) -> ReturnType: ...
```

**Validation**:
- [ ] [Specific check 1]
- [ ] [Specific check 2]

---

### P[N].2: [Task Name]

**File**: `path/to/file.py` (~[N] lines)

[Brief description]

```python
# Key interface
```

**Validation**:
- [ ] [Specific check]

---

## Implementation Notes

### [Topic 1]

[Important implementation detail or gotcha]

### [Topic 2]

[Another important detail]

---

## Validation Checklist

- [ ] All files created: `file1.py`, `file2.py`
- [ ] `__init__.py` exports: `Class1`, `Class2`
- [ ] Unit test passes: `pytest tests/unit/test_[name].py`
- [ ] Integration test: [Specific test description]
- [ ] Benchmark: [Metric] < [Threshold]

---

## Completion Criteria

When all validation items pass, update [TASKS.md](../TASKS.md):
1. Set P[N].1-P[N].[M] status to `completed`
2. Add completion date and agent ID
3. Note any issues discovered
