# 02 — Dataclasses vs C# records

All the pipeline's data contracts live in [models.py](../../src/sdd_pipeline/models.py) — pure
dataclasses, no service logic (a deliberate guardrail, see [CLAUDE.md](../../CLAUDE.md)). Open it.

## `@dataclass` ≈ `record` (positional class)

```python
@dataclass
class ContentBlock:
    """A single typed block of content within a section."""

    block_id: str
    content_type: ContentType
    text: str
    language: str | None = None  # populated for CodeBlock
    raw: dict[str, Any] | None = field(default=None, repr=False)
```

The decorator generates `__init__`, `__eq__` (value equality) and `__repr__` from the annotated
fields — exactly what `record class ContentBlock(string BlockId, ...)` generates (ctor, value
equality, `ToString`). `repr=False` on `raw` is like excluding a member from the printed form.
Unlike a C# record, a plain `@dataclass` is **mutable** — fields are settable like ordinary
properties. `@dataclass(frozen=True)` is the init-only/immutable record equivalent: assignment
after construction raises. `models.py::EntityRecord` is the repo's one frozen dataclass.

Now read `models.py::Section` and `models.py::SemanticChunk` — note `SemanticChunk` is a dataclass
*with methods* (`to_embed_text`, `to_metadata`, `to_dict`). That's fine: dataclasses are normal
classes; the decorator only generates the boilerplate.

## `field(default_factory=list)` — the foot-gun C# doesn't have

In `Section` you'll see:

```python
blocks: list[ContentBlock] = field(default_factory=list)
subsections: list[Section] = field(default_factory=list)
```

Why not `blocks: list[ContentBlock] = []`? Because Python evaluates default values **once, at
class definition time**, not per call/instance. With `= []`, every `Section` created without an
explicit `blocks` argument would share *one single list object*: appending a block to section A
would make it appear in section B. C# has no equivalent trap — `new List<T>()` in a property
initializer runs per instance. `default_factory=list` restores per-instance semantics: it stores a
factory (`list` is the constructor) called for each new object. Dataclasses actually *refuse* to
compile `= []` (`ValueError: mutable default`), which is why every list/dict field in models.py
uses `default_factory`.

## `__post_init__` + the frozen-write incantation

```python
@dataclass(frozen=True)
class EntityRecord:
    ...
    canonical: str = ""

    def __post_init__(self) -> None:
        if not self.canonical:
            object.__setattr__(self, "canonical", self.text)
```

`__post_init__` runs right after the generated `__init__` — the body of a C# record constructor
after the positional parameters are assigned (or an `init` accessor computing a derived default).
The twist: `frozen=True` is implemented by overriding `__setattr__` to raise, so the *class can't
even mutate itself*. `object.__setattr__(self, ...)` bypasses the override by calling the base
implementation directly — the sanctioned escape hatch for "set a derived field during
construction of an immutable object". Read `models.py::EntityRecord` and its docstring for what
`field`/`canonical` mean in the enrichment flow.

## `StrEnum` ≈ enum whose `ToString()` is the wire value

```python
class SectionType(StrEnum):
    OVERVIEW = "overview"
    ...
    DONE_CRITERIA = "done_criteria"
    ...
    CONTENT = "content"
```

A `StrEnum` member **is** a `str` (`SectionType.OVERVIEW == "overview"` is true), so it
serializes as its string value with zero converters — the effect you'd get in C# only with
`JsonStringEnumConverter` plus a naming policy. That's why these survive JSON roundtrips: look at
`models.py::SemanticChunk.to_dict`, which still writes `self.section_type.value` explicitly for
lossless export, and `models.py::SemanticChunk.to_metadata` doing the same for Chroma. Compare
`models.py::ContentType` (paragraph/code/table/list/blockquote). An int-backed enum would have
exported `3` and broken every consumer that reindexes the JSON.

## `asdict()` ≈ reflection-based serialization

[dump.py](../../src/sdd_pipeline/dump.py) serializes a whole enriched document tree with one call:

```python
_write(out / "enriched.json", asdict(enriched))
```

`dataclasses.asdict` recursively converts a dataclass graph (here `DocumentModel` →
`Section` → `ContentBlock`) into nested dicts/lists — like `JsonSerializer.Serialize` walking
public properties via reflection, except it produces a dict you then hand to `json.dumps`.
Contrast with `SemanticChunk.to_dict`, which is *hand-written* because it adds a computed field
(`embed_text`) and normalizes shapes — read its docstring for the rationale.

## Self-check

1. A teammate "simplifies" `Section` by changing `tags: list[str] = field(default_factory=list)`
   to `tags: list[str] = []`. What happens, and if Python *didn't* reject it, what bug would ship?

<details><summary>Answer</summary>

Dataclasses raise `ValueError: mutable default ... for field tags` at class-definition time. If
allowed, all `Section` instances constructed without `tags` would share one list — enrichment
appending a tag to one section would silently tag every section in every document.
</details>

2. Why can't `EntityRecord.__post_init__` just write `self.canonical = self.text`?

<details><summary>Answer</summary>

`frozen=True` makes the dataclass override `__setattr__` to raise `FrozenInstanceError` — even
inside the class's own methods. `object.__setattr__(self, "canonical", self.text)` calls the
non-raising base implementation, the standard idiom for derived defaults on frozen dataclasses.
</details>
