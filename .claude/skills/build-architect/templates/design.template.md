# Design Principles

> Philosophy and constraints guiding implementation

## Coding Standards

**All code must follow these constraints**:

| Requirement | Rationale |
|-------------|-----------|
| **Modern asyncio patterns** | Use `async/await`, not threads (except [exceptions]) |
| **Non-blocking I/O** | All file/network I/O via `asyncio.to_thread()` or async libs |
| **No docstrings** | Skip docstrings and obvious comments |
| **Concise code** | Optimize for AI readability (context/token efficiency) |
| **Type hints** | Use type hints for self-documenting code |
| **Minimal abstractions** | Only abstract when reuse is proven, not speculative |

**Exception**: [Describe any exceptions to the above rules]

---

## Principle 1: [Name]

[Description of the principle]

**Allowed**:
- [What is allowed]

**Forbidden**:
- [What is forbidden]

---

## Principle 2: [Name]

[Description]

---

## Priority Hierarchy

When resources are constrained:

1. **[Highest]** - never skip
2. **[High]** - next priority
3. **[Medium]** - can delay
4. **[Low]** - can drop

---

## Error Handling

When something goes wrong:
- Log the error with context
- Continue if possible
- Report via [status mechanism]
- Never crash silently

---

## Testability

Every component must be:
- Unit testable in isolation
- Mockable at integration boundaries
- Benchmarkable for performance

Test coverage requirements:
- Core data types: 100%
- [Area 1]: [N]%
- [Area 2]: [N]%

---

## Standalone Testing

During development, test components without the full system:

```bash
# Run from project root
cd [PROJECT_ROOT]
PYTHONPATH=. python3 -c "
# Quick test code here
"

# Run unit tests
PYTHONPATH=. pytest [test_path] -v
```
