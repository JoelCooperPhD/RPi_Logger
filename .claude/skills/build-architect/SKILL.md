---
name: build-architect
description: Knowledge base for designing AI-agent-friendly build documentation
globs:
  - "**/ARCHITECTURE.md"
  - "**/docs/TASKS.md"
  - "**/docs/README.md"
---

# Build Architect Skill

This skill provides templates and patterns for creating AI-agent-friendly documentation structures.

## When to Use

Use `/architect` command when:
- Starting a new module from scratch
- Refactoring a large module into structured tasks
- Planning a multi-phase feature implementation
- Setting up documentation for parallel AI development

## Documentation Patterns

### TASKS.md (Master Tracker)

The single source of truth for task status. AI agents check here first.

**Required sections**:
1. Folder rename warning (if applicable)
2. Coding standards (MANDATORY)
3. How to use instructions
4. Phase tables with task status
5. Status legend
6. Quick stats

### Task Files

Each phase gets a dedicated task file with:
1. Quick reference table (status, dependencies, effort, specs)
2. Goal statement (one sentence)
3. Sub-tasks with file deliverables
4. Validation checklist with checkboxes
5. Completion criteria

### Reference Files

Background context that doesn't change during implementation:
- mission.md - Goals and non-goals
- design.md - Principles and coding standards
- hardware.md - Platform constraints (if applicable)
- [api].md - External API documentation

### Spec Files

Technical specifications for implementation:
- components.md - Interface definitions with code examples
- output_formats.md - File format specifications
- commands.md - Protocol definitions
- gui.md - UI requirements (if applicable)

### Testing Task Files (REQUIRED)

Every module MUST include testing tasks:
- testing_unit.md - Unit test coverage requirements
- testing_integration.md - Integration test scenarios
- testing_stress.md - Performance and stress test criteria

These are separate from implementation phases and should be documented as their own tasks with validation checklists.

## Complete Folder Structure

```
module_name/
├── ARCHITECTURE.md           # High-level overview (optional)
└── docs/
    ├── TASKS.md              # Master task tracker (START HERE)
    ├── README.md             # Navigation and quick start
    │
    ├── reference/            # Background context (read-only)
    │   ├── mission.md        # Goals, non-goals, success metrics
    │   ├── design.md         # Principles, coding standards
    │   └── [topic].md        # Hardware, API docs, etc.
    │
    ├── specs/                # Technical specifications
    │   ├── components.md     # Interface definitions with pseudocode
    │   ├── output_formats.md # File format specs (CSV, video, etc.)
    │   └── [area].md         # Area-specific specs (gui, commands)
    │
    └── tasks/                # Individual task files
        ├── phase1_[name].md
        ├── phase2_[name].md
        ├── ...
        ├── testing_unit.md         # REQUIRED
        ├── testing_integration.md  # REQUIRED
        └── testing_stress.md       # REQUIRED
```

## Coding Standards Template

Include this in TASKS.md and design.md:

```markdown
## Coding Standards (MANDATORY)

| Requirement | Rationale |
|-------------|-----------|
| Modern asyncio patterns | Use async/await, not threads |
| Non-blocking I/O | All I/O via asyncio.to_thread() |
| No docstrings | Skip docstrings and obvious comments |
| Concise code | Optimize for AI readability |
| Type hints | Use type hints for self-documentation |
```

## Task Table Template

```markdown
| ID | Task | Status | Depends On | Agent | File to Create |
|----|------|--------|------------|-------|----------------|
| P1.1 | [task name] | available | - | - | `path/file.py` |
| P1.2 | [task name] | available | P1.1 | - | `path/file.py` |
```

## Validation Checklist Template

```markdown
## Validation Checklist

- [ ] All files created: `file1.py`, `file2.py`
- [ ] `__init__.py` exports all public classes
- [ ] Unit test passes: `pytest tests/unit/test_X.py`
- [ ] Integration test: [specific test description]
- [ ] Benchmark: [metric] < [threshold]
```

## Dependency Graph Template

Use text-based format for clarity:

```markdown
NO DEPENDENCIES (can start immediately):
  P1.1, P1.4, P2.3, P3.2

AFTER P1.1:
  P1.2, P2.1, P3.1

AFTER P1.2:
  P1.3

AFTER P1.4 + P2.1:
  P2.2
```

## Agent Workflow Template

```markdown
## Agent Workflow

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

## Best Practices

1. **Keep files small**: 50-200 lines per file
2. **Link, don't duplicate**: Reference other docs instead of copying
3. **Use tables**: Structured data is easier to parse
4. **Include examples**: Code snippets over prose descriptions
5. **Explicit dependencies**: Never assume, always state
6. **Measurable validation**: Every checkbox should be verifiable

## Required Specifications (DO NOT SKIP)

When defining data structures and interfaces, you MUST specify:

### Data Format Requirements
- For `bytes` fields: specify format (JPEG, PNG, raw BGR, YUV420, etc.)
- For buffer/queue bounds: specify overflow behavior (drop oldest, block, raise exception)
- For timestamps: specify precision and source (wall clock, monotonic, hardware sensor)

### Algorithm Documentation
- Non-trivial algorithms MUST include pseudocode, not just method signatures
- Include edge case handling in pseudocode
- Document time/space complexity for performance-critical code

### Thread/Async Model Consistency
- If architecture mentions "thread", design MUST specify if it's:
  - A dedicated thread (threading.Thread)
  - A task via asyncio.to_thread()
  - A ProcessPoolExecutor worker
- These MUST be consistent across all documentation files

### Phase Sequencing Rationale
- TASKS.md MUST include a brief explanation of WHY phases are ordered as they are
- Document what would break if phases were reordered

### Error Recovery
- Every component that can fail MUST document:
  - Expected failure modes
  - Recovery behavior (retry, propagate, fallback)
  - State after failure (clean, dirty, unknown)
