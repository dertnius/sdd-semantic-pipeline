# Exercise 02 — Add a section-classification keyword

**Goal.** Headings like "Observability" currently fall through every rule in
`enrichment.py::_SECTION_RULES` and get the null type `content`. Make them
classify as an existing, sensible `SectionType` — and prove it with a test. This
is the smallest possible change to the rule table, but it forces you to respect
the two constraints documented right inside the module: rule **order** and
substring **collisions**. Background: [tour 03](../tours/03-enrichment.md).

**Difficulty:** easy

**You will learn**
- How the ordered, first-match-wins rule table drives `classify_section_type`.
- Why keyword choice matters (leading-word-boundary matching, collision comments).
- How to extend a parametrized pytest table
  ([bridge 07](../bridge/07-pytest-for-xunit-developers.md)).

## Before you start

```powershell
git checkout learn-exercises    # created in exercise 01; or: git checkout -b learn-exercises
```

Confirm the current behavior yourself (verified output shown):

```powershell
.\.venv\Scripts\python.exe -c "from sdd_pipeline.enrichment import classify_section_type; print(classify_section_type('Observability').value)"
# prints: content
```

`"observability"` appears in no rule list today — that print is the default
fall-through from `enrichment.py::classify_section_type`.

## Files

- `src/sdd_pipeline/enrichment.py` — `_SECTION_RULES`
- `tests/test_enrichment.py` — `TestClassifySectionType`

## Steps

1. Read `_SECTION_RULES` top to bottom and decide which existing `SectionType`
   an "Observability" / "Monitoring and Observability" heading belongs to.
   `DEPLOYMENT` is the natural home (it already owns the ops vocabulary:
   `infrastructure`, `kubernetes`, `rollout`…) — but make the call yourself and
   be able to defend it.
2. Re-read the comment block above `_SECTION_RULES` (lines about "ORDER
   MATTERS" and `contra` ⊂ `contract`) and the one above `_SECTION_PATTERNS`
   (leading `\b` only — keywords match at a word start, plurals/inflections
   still match). Ask: can your keyword be matched *inside* an unrelated title?
   Can an **earlier** rule steal your title first?
3. Add the keyword to the chosen rule list. Note `_SECTION_PATTERNS` is built
   from `_SECTION_RULES` at import time — editing the dict is the whole change.
4. Add a test. Don't write a new function: extend the parametrize table of
   `tests/test_enrichment.py::TestClassifySectionType::test_known_titles` with
   one or two `(title, expected)` rows, exactly in the style of the existing
   `("Kubernetes Config", SectionType.DEPLOYMENT)` row. Include a multi-word
   title (e.g. "Observability and Monitoring") to prove word-start matching.

<details>
<summary>Hint</summary>

- "observability" is not a substring-at-word-start of any common unrelated word,
  and no earlier rule list contains a keyword that matches "Observability" (you
  proved that with the `python -c` above — it returned the default).
- If you also want bare "Monitoring" to classify, that's a second keyword —
  check it against earlier rules the same way before adding it.
</details>

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_enrichment.py -q
```

Success: all tests pass (the file currently passes; your new parametrize rows
appear in the count, no regressions). Then re-run the one-liner from *Before you
start* — it should now print your chosen type (e.g. `deployment`) instead of
`content`.

## Cleanup

```powershell
git add -A && git commit -m "learn: classify Observability headings (exercise 02)"
```

or revert if you don't want to keep it:

```powershell
git checkout -- src/sdd_pipeline/enrichment.py tests/test_enrichment.py
```
