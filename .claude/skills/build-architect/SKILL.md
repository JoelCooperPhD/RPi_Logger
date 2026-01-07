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
