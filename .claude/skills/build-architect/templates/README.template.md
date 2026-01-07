# [MODULE_NAME] Documentation

> [One-line module description]

## Quick Start for AI Agents

1. **Check available tasks**: [TASKS.md](TASKS.md)
2. **Read task instructions**: `tasks/phase{N}_{name}.md`
3. **Reference specs as needed**: `specs/*.md`
4. **Mark complete when done**: Update TASKS.md

---

## Documentation Structure

```
docs/
├── TASKS.md              ← START HERE (master task tracker)
├── README.md             ← You are here
│
├── reference/            ← Background context (read-only)
│   ├── mission.md        Goals, non-goals, scope
│   ├── design.md         Principles and coding standards
│   └── [topic].md        Domain-specific context
│
├── specs/                ← Technical specifications
│   ├── components.md     Component interfaces
│   └── [area].md         Area-specific specs
│
└── tasks/                ← Actionable task files
    ├── phase1_[name].md
    ├── phase2_[name].md
    └── ...
```

---

## Task Dependency Graph

```
NO DEPENDENCIES (can start immediately):
  [List tasks]

AFTER [task]:
  [List dependent tasks]

...
```

---

## What Can Be Parallelized

**Immediate (no dependencies)**:
- [List tasks]

**After [task(s)]**:
- [List tasks]

---

## Project Setup (Before Starting)

Create directories and `__init__.py` files:

```bash
# Create directory structure
mkdir -p [directories]

# Create __init__.py files
touch [paths]
```

---

## Key References

| Topic | File | When to Read |
|-------|------|--------------|
| [Topic] | [Link] | [When] |

---

## Agent Workflow

```
1. Read TASKS.md
   └─► Find task with status=available, deps=completed

2. Update TASKS.md
   └─► Set status=in_progress, add agent ID

3. Read task file
   └─► tasks/phase{N}_{name}.md

4. Read relevant specs
   └─► specs/*.md (linked in task file)

5. Implement deliverables
   └─► Create files listed in task

6. Run validation checklist
   └─► Tests, benchmarks from task file

7. Update TASKS.md
   └─► Set status=completed, add date and notes
```

---

## Project Goals

1. [Goal 1]
2. [Goal 2]
3. [Goal 3]

See [reference/mission.md](reference/mission.md) for full context.
