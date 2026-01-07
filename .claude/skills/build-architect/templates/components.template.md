# Component Specifications

> Core data types and interfaces

## [ComponentName]

[Brief description of the component]

```python
@dataclass(frozen=True, slots=True)
class ComponentName:
    field1: Type              # Description
    field2: Type              # Description
    field3: Type              # Description
```

**Notes**:
- [Important note 1]
- [Important note 2]

---

## [ProtocolName]

[Brief description of the protocol/interface]

```python
class ProtocolName(Protocol):
    async def method1(self) -> ReturnType: ...
    async def method2(self, param: Type) -> ReturnType: ...

    @property
    def property1(self) -> Type: ...
```

---

## [ClassName]

[Brief description]

```python
class ClassName:
    _private1: Type           # Description
    _private2: Type           # Description

    async def method1(self) -> None: ...
    async def method2(self, param: Type) -> ReturnType: ...
```

**Implementation notes**:
- [Note 1]
- [Note 2]

---

## Data Flow

```
[Source]
    │
    ▼
[Step 1]
    │
    ├──► [Branch 1] ──► [Output 1]
    │
    └──► [Branch 2] ──► [Output 2]
```

---

## Algorithm: [Name]

```python
def algorithm_name(param: Type) -> ReturnType:
    # Step 1: [Description]
    ...

    # Step 2: [Description]
    if condition:
        return result1

    # Step 3: [Description]
    return result2
```

**Key points**:
- [Point 1]
- [Point 2]
