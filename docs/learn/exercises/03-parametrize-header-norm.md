# Exercise 03 — Parametrize the header-normalisation spec

**Goal.** `header_norm.py::normalise_header` implements a 5-step spec (lowercase,
collapse whitespace, strip parentheticals, keep the first `/`-token, naive
singularise with a guard). Write a new `@pytest.mark.parametrize` test in
`tests/test_header_norm.py` with five cases of your own — but **predict each
expected output from the spec before you run anything**. The point is the
xUnit `[Theory]/[InlineData]` muscle transplanted to pytest, plus the
predict-first discipline that catches misread specs.

**Difficulty:** easy

**You will learn**
- `@pytest.mark.parametrize` with `ids=` — the pytest analogue of
  `[Theory]`/`[InlineData]` ([bridge 07](../bridge/07-pytest-for-xunit-developers.md)).
- How the singularise guard really works: `header_norm.py::_singularise_token`
  uses a length guard (`len(tok) > 3`) **and** the `_KEEP_S` ending tuple
  `("ss", "us", "is", "as", "os")` — there is no whitelist of words.

## Before you start

```powershell
git checkout learn-exercises
```

Read `src/sdd_pipeline/header_norm.py` (it's 50 lines) — the module docstring
*is* the spec. Then read the existing parametrized test
`tests/test_header_norm.py::test_normalise_examples` for the house style.

## Files

- `tests/test_header_norm.py` (only — no production code changes)

## Steps

1. Choose 5 inputs that each exercise a *different* spec step. Write down your
   predicted output for each **before** running anything.
2. At least one case must exercise the singularise **guard** — an input ending
   in `s` that must *not* be stripped. Read `_singularise_token` to see the two
   guard conditions and pick an input that hits one of them.
3. Check your predictions (only after committing to them):

   ```powershell
   .\.venv\Scripts\python.exe -c "from sdd_pipeline.header_norm import normalise_header as n; print(n('Status'), '|', n('APIs'))"
   ```

4. Add one new parametrized test function (don't edit `test_normalise_examples`)
   and give your cases readable `ids=` so they show up by name in `-v` output.

If you want verified cases to compare against, these five were run against the
current code:

| input | output | spec step exercised |
|---|---|---|
| `"Producer/Publisher"` | `"producer"` | split on `/`, keep first token |
| `"Quality Attributes (non-functional)"` | `"quality attribute"` | strip parenthetical + singularise |
| `"  Related   Components  "` | `"related component"` | strip/collapse whitespace |
| `"Status"` | `"status"` | guard: `us` ending in `_KEEP_S` |
| `"APIs"` | `"apis"` | guard surprise: lowercased `apis` ends in `is` |

(The last one is the spec-misread trap: you probably predicted `api`. The
lowercase happens *before* singularisation, and `"apis"` ends with `"is"`,
which is in `_KEEP_S` — so the trailing `s` survives.)

<details>
<summary>Hint</summary>

Skeleton (C#: `[Theory]` + `[InlineData]`, here: one decorator with a list of
tuples):

```python
@pytest.mark.parametrize(
    "raw,expected",
    [(..., ...), ...],
    ids=["slash-token", "paren-singular", "whitespace", "keep-us", "keep-is"],
)
def test_my_normalise_cases(raw, expected):
    assert normalise_header(raw) == expected
```

`pytest tests/test_header_norm.py --collect-only -q` shows the generated item
ids without running anything.
</details>

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_header_norm.py -v
```

Success: your 5 cases appear as **separate test items** (e.g.
`test_my_normalise_cases[keep-is]`), all green, and the pre-existing 15 items
(11 of them from `test_normalise_examples`) still pass.

## Cleanup

```powershell
git add -A && git commit -m "learn: parametrized header-norm cases (exercise 03)"
# or: git checkout -- tests/test_header_norm.py
```
