# Confluence → Markdown conversion rules for the embedding corpus

Definitive rule set for converting Confluence Server/DC 8.0–10.x pages — arriving as either
**(A) storage-format XHTML** (`body.storage` from REST, `ac:`/`ri:`/`at:` namespaces, CDATA) or
**(B) rendered HTML export** (space export / `export_view`) — into GitLab-flavoured Markdown
optimized for vector embedding.

*Last updated: 2026-06-12*

> **Corpus hazard:** this document contains literal Confluence syntax (`ac:` examples in code spans and
> fences). Exclude it from any embedding corpus and from `sdd-pipeline lint` targets — point those at the
> real corpus, never at a docs tree that *documents* Confluence syntax.

**Code references** are against branch `template-enrichment` @ commit `5e60065`. Note: `quality.py`, the
`sdd-pipeline lint` command and the extended `models.py` exist only on that (unmerged) branch until
`template-enrichment` merges to `main`.

**Supersedes** `docs/inbox/CONFLUENCE_FORMAT_INSTRUCTIONS.md` and
`docs/guides/confluence-storage-format-gitlab-markdown.md` wherever they conflict. Known divergences from those
specs: jira macro handling (SF-MACRO-JIRA/HX-JIRA instead of untranslated residue), expand rendering (bold
paragraph, **no** `<details>`), anchor policy (targets dropped, same-page links → plain text), placeholders
(deleted, not `*[text]*`), the `#content-view` content root (legacy code-derived; the catalog documents
`div#content.view` — see HX-ROOT), and `[[_TOC_]]` injection (default OFF for the embedding corpus, not
unconditional).

**Status legend** (every rule carries one):

- `[EXISTS: file]` — already implemented; the rule documents it as canonical.
- `[CHANGE]` — implemented but conflicting with the embedding goal or buggy; the rule states the required behavior.
- `[NEW]` — not implemented.

Key files referenced:
- `src/sdd_pipeline/convert/html_to_gitlab_md.py` (converter, all three stages today)
- `src/sdd_pipeline/quality.py` (post-conversion lint)
- `src/sdd_pipeline/structural.py`, `src/sdd_pipeline/models.py`, `src/sdd_pipeline/chunking.py` (downstream consumers)
- `src/sdd_pipeline/ast_parser.py` (repo-native pandoc-JSON pattern reused by Stage B/C)

---

## 1. Architecture overview

**Strategy: two thin input-specific pre-cleans → one common intermediate HTML → one shared pandoc + panflute + regex path.**

```
(A) storage XHTML ──► Stage A1 (BeautifulSoup 'html.parser')──┐
                                                              ├──► PFI-HTML ──► Stage B (pandoc html→json)
(B) HTML export  ──► Stage A2 (BeautifulSoup 'lxml')──────────┘        │
                                                                       ▼
                                              Stage C (panflute filter, in-process on the JSON AST)
                                                                       │
                                                                       ▼
                                              Stage B' (pandoc json→gfm) ──► Stage D (regex post-process,
                                                                              frontmatter) ──► .md
```

Rationale: pandoc has **no Confluence storage-format reader** (jgm/pandoc#2155, never implemented) and its
default HTML reader silently **unwraps unknown namespaced tags, dropping all their attributes** — an
`ac:structured-macro` loses its `ac:name` identity, and self-closing `ri:page`/`ac:emoticon` elements vanish
entirely (verified, pandoc 3.9). `+raw_html` does not help (namespace prefix stripped from tag names, fragments
split across blocks). Therefore **all Confluence semantics must be resolved before pandoc** by rewriting into
the *pandoc-friendly intermediate* (PFI-HTML): plain `div`/`span`/standard HTML carrying classes +
`data-*` attributes, which pandoc's default `+native_divs`/`+native_spans` turns into AST `Div`/`Span` with
readable attributes for the panflute filter.

**PFI-HTML vocabulary** (contract between Stage A and Stage C):

| PFI construct | Meaning | Consumed by |
|---|---|---|
| `div.adm[data-macro=info\|note\|warning\|tip\|panel][data-title]` | admonition/panel, body = real block children | PF-ADMONITION |
| `pre > code.language-{lang}` | code block (CDATA already inlined) | pandoc natively |
| `div.expand[data-title]` | expand macro body | PF-EXPAND |
| `span.lozenge[data-colour]` | status macro | PF-LOZENGE |
| `div.layout` / `div.layout-col` | layout sections/cells, section/column macros | PF-LAYOUT-FLATTEN |
| `ul > li > input[type=checkbox][checked]` | task list | pandoc natively (`- [x]`) |
| `p > em` one-liner summaries | summarize-to-text macro output | passthrough |

*(Unknown bodiless macros never reach the PFI: they are deleted in Stage A with a `ConversionNotes` count —
the single reporting channel; see SF-MACRO-UNKNOWN.)*

**PFI contract requirement — the Stage-A unwrap/scrub must be PFI-aware** `[CHANGE]`: the existing blanket
div/span unwrap (lines 268–271) and attribute scrub (lines 273–287) would destroy every PFI element before
pandoc sees it — the scrub's allowlist (`href/src/alt/title/id/colspan/rowspan` + `language-*` on `code`)
strips `class` and all `data-*`, and the unwrap deletes the carrier elements outright, leaving the entire
Stage-C filter dead code (PF-ADMONITION, PF-LOZENGE, PF-EXPAND, PF-LAYOUT-FLATTEN, PF-DROP and the report
channel would never fire). Both passes MUST skip elements whose class is in the PFI vocabulary above, and the
attribute allowlist MUST be extended with `class` + `data-macro`/`data-title`/`data-colour` on those elements.
(Alternative: move the blanket unwrap/scrub entirely into Stage C as part of PF-HYGIENE-UNWRAP and delete the
BS4 version.) Wherever this document cites lines 268–287 as `[EXISTS]`, read it as `[CHANGE]` to this contract.

**Pandoc invocations** (Stage B; details in §4):

- Both input kinds, after pre-clean: `pandoc --from=html --to=json` → `pf.load` → `run_filter(...)` in-process →
  `pandoc --from=json --to=gfm --wrap=none --markdown-headings=atx --strip-comments` (reuses the repo's
  `ast_parser.py`/`structural.py` pf.load pattern; 2 pandoc subprocesses per document).
- Reader stays at HTML defaults (`+native_divs +native_spans -raw_html -empty_paragraphs`) — do **not** add `+raw_html`.
- Writer keeps gfm's default `+raw_html` only because `-raw_html` degrades any unsimplified table to the
  literal string `[TABLE]` — total content loss. Raw-HTML table output is NOT a fallback but a **conversion
  failure**: it is a `quality.py html_leakage` block AND is silently destroyed downstream
  (`structural._elem_to_content_block` handles only Para/CodeBlock/Lists/Table/BlockQuote — a RawBlock
  returns None, so the chunker never sees the content). PF-TABLE-SIMPLIFY's job is to make this path
  unreachable; the lint proves it per file.

`[CHANGE]` vs today: `html_to_gitlab_md.convert()` runs a single `pandoc --from html --to gfm+pipe_tables
--wrap=none --strip-comments --no-highlight` call with **no filter stage**. The panflute Stage C is `[NEW]`; the
writer gains `--markdown-headings=atx` (explicit pin) — `+smart` is deliberately NOT added (see PD-WRITE);
`--no-highlight` is a no-op for gfm and may be kept.

**Critical parser requirement** `[CHANGE]`: storage-format input MUST be parsed with BeautifulSoup
`html.parser` (or lxml's recovering HTMLParser), **not** `lxml`. `preprocess()` line 192 uses
`BeautifulSoup(html, "lxml")`, and the code's own comment (line 679) concedes "the lxml HTML parser DROPS
CDATA" — which means every `code` macro body, `noformat` body and `ac:plain-text-link-body` is **destroyed
today** on storage-format input. `html.parser` preserves CDATA as a `bs4.CData` node and treats
`ac:structured-macro` as a literal tag name, so `soup.find_all("ac:structured-macro")` works. Stage A2 (rendered
HTML, no CDATA) may keep lxml for speed.

### 1.1 Profiles

The **embedding profile** is the normative default for every rule in this document; remarks about a
**human-docs profile** are non-normative alternatives for a corpus meant to be read, not embedded. The
genuinely profile-divergent rules:

| Rule | Embedding profile (normative) | Human-docs profile (non-normative) |
|---|---|---|
| MD-TOC-INJECT (§6) | default OFF — a `[[_TOC_]]` paragraph survives chunking as a junk chunk | may inject `[[_TOC_]]` |
| SF-INLINE-EMOTICON chain (§2.7; also HX-EMOTICON, VER-EMOJI) | shortname → mapped word → literal char LAST | emoji-first chain acceptable |
| Anchor policy (SF-LINK-ANCHORLINK, SF-MACRO-ANCHOR, HX-ANCHOR, SF-LINK-EXT carve-out) | same-page anchors → plain text; anchor targets dropped | may map anchors to the nearest heading's GitLab auto-anchor when resolvable |
| Expand rendering (SF-MACRO-EXPAND / HX-EXPAND / PF-EXPAND) | bold paragraph + body as first-class prose | `<details>`/`<summary>` HTML acceptable |

### 1.2 Input acquisition

Preferred REST call — one request covers every FM-* source field (§7):

```
GET /rest/api/content/{id}?expand=body.storage,version,space,history,metadata.labels
```

| Body | Properties | Preference |
|---|---|---|
| `body.storage` | lossless authored XHTML — CDATA intact, macro identities (`ac:name`) preserved, element-valued params readable | **preferred**; processed by Stage A1 (SF-* rules) |
| `body.export_view` | pre-rendered HTML — macros expanded as anonymous user, render-time content baked in, CDATA escaped away | lossy fallback; processed by Stage A2 (HX-* rules + HX-EXPORTVIEW deltas) |

`version`, `space`, `history`, `metadata.labels` feed FM-VERSION, FM-SPACE, FM-AUTHOR/FM-DATE and FM-LABELS
respectively; the page object's `title` feeds FM-TITLE.

### 1.3 Input routing

REST callers pass the body kind explicitly; the byte-sniff is the fallback for files of unknown origin:
content containing `<ac:` / `<ri:` / `<at:` routes to **Stage A1** (storage format, `html.parser`); anything
else routes to **Stage A2** (rendered export, lxml acceptable). `<at:` is required in the sniff — template
bodies may contain only `at:*` tags. The sniff cannot misroute rendered input: `export_view` escapes code
samples to `&lt;ac:`, so a literal `<ac:` byte sequence occurs only in real storage-format input (verified).

> **IMPLEMENTED (rendered-only scope).** `html_to_gitlab_md._reject_if_storage_format`
> applies this sniff at the top of `convert_file`: a literal `<ac:`/`<ri:`/`<at:` opener
> ⇒ **refuse with `ConversionError`** ("rendered HTML only"). Stage A1 / the SF-* rules
> below are **not** wired into `convert_file` (the door rejects storage input first); the
> `_normalise_ac_*` handlers remain only for direct unit tests. Full storage support
> stays deferred — supporting it means routing storage input to `html.parser` + Stage A1
> instead of rejecting it. Rendered input (Stage A2) is the supported path.

---

## 2. Stage A1 — pre-clean rules for STORAGE-FORMAT input (SF-*)

All rules run on the BeautifulSoup tree (`html.parser`). Order matters: the shared early inline rules
(SF-TEXT-STRIKE, SF-INLINE-TIME, SF-TEXT-SMALLBIG) run BEFORE any unwrap/scrub; then specific macro handlers,
layout/RI handlers next, SF-ADF before the catch-all, the unknown-macro catch-all **last**.

### 2.1 Text constructs

| ID | Detect | Action | Example (in → out) | Embedding rationale | Status |
|---|---|---|---|---|---|
| SF-TEXT-HEADING | `h1`–`h6` | passthrough | `<h2>Design</h2>` → `## Design` | headings drive section tree, breadcrumbs, chunk boundaries | [EXISTS: html_to_gitlab_md.py — implicit passthrough] |
| SF-TEXT-PARA | `p`, `p[style*=text-align]` | keep `p`, strip the alignment style | `<p style="text-align: center;">x</p>` → `x` | alignment is presentation, zero semantic signal | [EXISTS: attr scrub, lines 273–287] |
| SF-TEXT-BOLD | `strong` (also `b` in link bodies) | passthrough | `<strong>must</strong>` → `**must**` | emphasis survives as markdown, no HTML leak | [EXISTS] |
| SF-TEXT-ITALIC | `em` (also `i` in link bodies) | passthrough | `<em>note</em>` → `*note*` | same | [EXISTS] |
| SF-TEXT-UNDERLINE | `u` | no Stage-A action — pandoc reads `u` natively (Underline); PF-INLINE-TEXT (§5) unwraps it | `<u>key</u>` → `key` | avoids raw `<u>` in corpus; text intact | [NEW — via PF-INLINE-TEXT] |
| SF-TEXT-SUPSUB | `sup`, `sub` | no Stage-A action — pandoc reads them natively; PF-INLINE-TEXT (§5) normalizes | `m<sup>2</sup>` → `m^2` | gfm would emit raw `<sup>` tags — HTML leakage; gluing to `m2` would corrupt units | [NEW — via PF-INLINE-TEXT] |
| SF-TEXT-MONO | inline `code` (also `tt` in link bodies; map `tt`→`code`) | passthrough | `<code>kubectl</code>` → `` `kubectl` `` | inline code is a strong entity signal for `extract_entities` | [EXISTS] |
| SF-TEXT-BLOCKQUOTE | `blockquote` | passthrough | → `> quoted` | quote semantics kept as searchable text | [EXISTS] |
| SF-TEXT-COLOR | `span[style*=color]` (rgb() and hex) | unwrap, keep text | `<span style="color: rgb(255,0,0);">red</span>` → `red` | colour carries no retrievable meaning; spans leak HTML | [CHANGE — lines 268–287 must first become PFI-aware (§1 PFI contract)] |
| SF-TEXT-SMALLBIG | `small`, `big` | unwrap, keep text — runs in BOTH A1 and A2, BEFORE the blanket unwrap/scrub | `<small>fine print</small>` → `fine print` | deprecated presentation tags; text is the content | [NEW] |
| SF-TEXT-HR | `<hr />` | passthrough | → `---` | harmless separator; pandoc-native | [EXISTS] |
| SF-TEXT-ENTITY | `&nbsp; &mdash; &ndash;` | decode; nbsp → plain space (Stage D backstop); keep Unicode em/en-dashes and ellipsis as-is (`+smart` is deliberately not used — see PD-WRITE) | `A&nbsp;&mdash;&nbsp;B` → `A — B` | nbsp breaks tokenizers; Unicode punctuation embeds fine (BGE/MiniLM tokenizers handle — and …) | [EXISTS: nbsp at line 1089] |

#### SF-TEXT-STRIKE / HX-TEXT-STRIKE — strikethrough (both serializations, both input kinds)
- **Detect:** `span[style*="text-decoration: line-through"]` (the *official* storage form). Literal `<s>`/`<del>`/`<strike>` need no Stage-A action — pandoc reads them natively as Strikeout (PF-INLINE-TEXT, §5).
- **Action:** rewrite the styled span to `<del>` so pandoc emits GFM strikethrough. Runs in BOTH A1 and A2, ordered BEFORE the blanket unwrap/scrub (the scrub strips the `style` attr and the unwrap deletes the span — the `line-through` rewrite must precede both).
- **Example:** `<span style="text-decoration: line-through;">old plan</span>` → `~~old plan~~`
- **Embedding rationale:** strikethrough often marks *rejected* decisions — `~~ ~~` keeps that signal as text instead of dropping it with the styled span.
- **Status:** [NEW] (the generic span-unwrap currently erases the strike semantics).

#### SF-TEXT-BR — line breaks and junk-`\` prevention
- **Detect:** `<br />`; specifically paragraphs whose only content is one or more `<br/>`.
- **Action:** keep `<br/>` inside table cells (the converter emits them there on purpose — `quality.py` deliberately excludes `br` from `_HTML_LEAKAGE`); **delete** paragraphs that contain only `<br/>`/whitespace.
- **Example:** `<p><br /></p>` → *(nothing)*; in a cell: `line1<br/>line2` → `line1<br/>line2` (rendered fine by GitLab).
- **Embedding rationale:** a lone `<br/>` becomes a `\`-only markdown line — the exact junk-chunk source CLAUDE.md documents.
- **Status:** [CHANGE] — today junk chunks are only dropped later at export; remove them at conversion (junk paragraphs die in PF-JUNK-PARA, §5).

#### SF-TEXT-PRE — bare preformatted blocks
- **Detect:** bare `pre` not produced by a macro handler (paste or legacy content; distinct from the code/noformat macros).
- **Action:** → fenced code block with **no** language class. Do **not** run `_detect_language` — pasted legacy text is usually not code in any specific language.
- **Example:** `<pre>raw pasted text</pre>` → ```` ``` raw pasted text ``` ````
- **Embedding rationale:** verbatim dumps stay verbatim; an invented language class would mint an untrusted `lang:` tag.
- **Status:** [NEW] — no covering rule today on either input path (HX side formalized as HX-PRE, §3).

### 2.2 Lists

| ID | Detect | Action | Example | Rationale | Status |
|---|---|---|---|---|---|
| SF-LIST-UL | `ul > li` (nested `ul` inside `li`; `style="list-style-type: square"`) | passthrough; strip style | → `- item` | native markdown lists | [EXISTS: scrub] |
| SF-LIST-OL | `ol > li` | passthrough | → `1. item` | same | [EXISTS] |

#### SF-LIST-TASK — task lists
- **Detect:** `ac:task-list > ac:task` with children `ac:task-id` (present in real DC storage even though docs omit it — accept and discard), `ac:task-status` (`complete`/`incomplete`), `ac:task-body` (rich text, may hold mentions/placeholders).
- **Action:** rewrite to `<ul><li><input type="checkbox" [checked]/> …body children…</li></ul>`. Pandoc converts checkbox-`li` natively to `- [x]` / `- [ ]` (gfm `+task_lists`). Process `ac:task-body` children through the other SF rules first (mentions, placeholders).
- **Example:** `<ac:task><ac:task-id>1</ac:task-id><ac:task-status>complete</ac:task-status><ac:task-body>ship it</ac:task-body></ac:task>` → `- [x] ship it`
- **Embedding rationale:** `[x]`/`[ ]` are searchable completion markers; rich bodies survive instead of being flattened.
- **Status:** [CHANGE] — `_normalise_task_lists` (lines 588–614) handles the storage form but flattens the body via `get_text` and emits literal `[x]` text markers requiring a Stage-D unescape; the checkbox-input form is structurally cleaner and keeps rich bodies.

### 2.3 Links and resource identifiers

#### SF-LINK-EXT — external / plain anchors
- **Detect:** `a[href]` — EXCLUDING same-page `a[href^="#"]`.
- **Action:** passthrough. Same-page `a[href^="#"]` are carved out of the passthrough: for the embedding profile they degrade to plain text (their targets are deleted by SF-MACRO-ANCHOR/HX-ANCHOR — see the anchor policy under SF-LINK-ANCHORLINK).
- **Example:** `<a href="http://www.atlassian.com">Atlassian</a>` → `[Atlassian](http://www.atlassian.com)`
- **Embedding rationale:** real URLs are provenance-grade content.
- **Status:** [EXISTS].

#### SF-LINK-PAGE — page links
- **Detect:** `ac:link > ri:page[ri:content-title][ri:space-key?][ri:version-at-save?]`, body from `ac:plain-text-link-body` (CDATA) or `ac:link-body`; missing body ⇒ link text = page title.
- **Action:** link text = body text or `ri:content-title`. If a site base URL is configured: `[text]({base}/display/{space-or-current}/{url-encoded title})`. If not: emit **plain text only** (no `href="#"` stub). Record unresolved targets in `ConversionNotes`, never in prose.
- **Example:** `<ac:link><ri:page ri:content-title="Deployment Guide"/></ac:link>` → `[Deployment Guide](https://conf.example/display/OPS/Deployment+Guide)` or, unresolved, `Deployment Guide`
- **Embedding rationale:** the page *title* is the semantic payload; dead `#` hrefs inflate `link_density` for nothing.
- **Status:** [CHANGE] — `_normalise_ac_links` (line 683) emits `href="#"` plus an HTML `Comment` marker that the pipeline's own `--strip-comments` then deletes (self-defeating); replace with resolvable-URL-or-plain-text.

#### SF-LINK-ATTACH — attachment links
- **Detect:** `ac:link > ri:attachment[ri:filename]`; cross-page form nests `ri:page`/`ri:blog-post` **inside** `ri:attachment`.
- **Action:** `[text-or-filename](attachments/{filename})`; warn to co-locate the file.
- **Example:** `<ac:link><ri:attachment ri:filename="logo.gif"/></ac:link>` → `[logo.gif](./attachments/logo.gif)`
- **Embedding rationale:** the filename is a searchable artifact name.
- **Status:** [EXISTS: `_normalise_ac_links`, lines 700–705] (extend to read the nested `ri:page` for cross-page attachments — minor [NEW]).

#### SF-LINK-ANCHORLINK — anchor links (the anchor policy, both input kinds)
- **Detect:** `ac:link[ac:anchor]`; same-page form has no `ri:page` child; cross-space form carries `ri:space`.
- **Action:** keep body text; same-page: **plain text** for the embedding profile (matching SF-LINK-PAGE's unresolved-target policy) — SF-MACRO-ANCHOR/HX-ANCHOR delete every anchor target, so a kept `[text](#anchor)` would be a guaranteed-dead link; cross-page/space: treat as SF-LINK-PAGE with `#anchor` suffix when a base URL exists (Confluence resolves it server-side), else plain text. Note: the rendered-export anchor-id scheme is `#PageTitleNoSpaces-HeadingTextNoSpaces`, which never matches GitLab's heading slugs — do not try to map anchors onto GitLab auto-anchors.
- **Example:** `<ac:link ac:anchor="setup"><ac:plain-text-link-body><![CDATA[Setup]]></ac:plain-text-link-body></ac:link>` → `Setup`
- **Embedding rationale:** anchor text is content; dead `#` fragments inflate `link_density` for nothing (the same reasoning SF-LINK-PAGE applies to `href="#"` stubs).
- **Status:** [CHANGE] — lines 706–709 emit fragment links whose targets this rule set deletes.

#### SF-LINK-USER — user mentions
- **Detect:** `ac:link > ri:user[ri:userkey]` (DC, 32-hex); tolerate `ri:account-id` (Cloud import) and `ri:username` (old exports).
- **Action:** resolve key → display name via an optional user-map (config/REST cache); emit `@DisplayName` as plain text (no link). Unresolved: never delete silently when any human-readable identifier exists — fall back through link body text → `ri:username` (old exports) → a neutral `@user` token; emit nothing ONLY for a bare 32-hex `ri:userkey` standing alone as its own block/cell (+ report entry). Silent deletion leaves grammatical holes in embeddable prose ("Reviewed by .", "Owner: ", empty cells).
- **Example:** `<ac:link><ri:user ri:userkey="2c9680f7…"/></ac:link>` → `@Jane Doe` (mapped), `@jdoe` (via ri:username), or `@user` (no identifier); a bare key alone in a cell → *(nothing)*
- **Embedding rationale:** a 32-hex userkey is pure entropy in a vector; a name is a usable entity.
- **Status:** [NEW] — confirmed gap; `ri:user` currently falls into the catch-all and is decomposed silently.

#### SF-LINK-BODY — plain vs rich link bodies
- **Detect:** `ac:plain-text-link-body` (CDATA) vs `ac:link-body` (markup limited to `b strong em i code tt sub sup br span`, occasionally `ac:image`).
- **Action:** plain body: CDATA text becomes the link text (requires the html.parser fix). Rich body: serialize the inner inline markup *into* the `<a>` (structure-preserving), don't flatten; an `ac:image` body makes the converted `<img>` the link content.
- **Example:** `<ac:link-body>Some <strong>Rich</strong> Text</ac:link-body>` → `[Some **Rich** Text](…)`
- **Embedding rationale:** inline code/bold inside link text carries entity signal.
- **Status:** [CHANGE] — current handler `get_text`-flattens (line 687).

#### SF-LINK-SHORTCUT — shortcut links
- **Detect:** `ac:link > ri:shortcut[ri:key][ri:parameter]`. **Body-nesting gotcha:** the link body (`ac:plain-text-link-body`) nests INSIDE `ri:shortcut` — unlike every other `ac:link` form, where the body is a SIBLING of the `ri:*` child. Search the body as a DESCENDANT of `ri:shortcut` (and tolerate the sibling position too).
- **Action:** unresolvable offline → plain text `{body-text or "{key}:{parameter}"}`. Body extraction for shortcuts explicitly differs from the page/attachment link shape — a generic direct-children search misses it.
- **Example:** `<ri:shortcut ri:key="jira" ri:parameter="ABC-123">…` → `jira:ABC-123`
- **Embedding rationale:** `ABC-123` is a searchable ticket id even without the site-configured URL.
- **Status:** [NEW].

#### SF-RI-MISC — remaining resource identifiers
- **Detect / Action:**
  - `ri:blog-post[ri:content-title][ri:posting-day]` → like SF-LINK-PAGE; text `"{title} ({posting-day})"`. [NEW]
  - `ri:space[ri:space-key]` → plain text space key (e.g. `TST`). [NEW] — confirmed gap.
  - `ri:content-entity[ri:content-id]` → plain text of link body if present, else nothing + report. [NEW]
  - `ri:url[ri:value]` → handled inside SF-IMG-EXT / SF-LINK contexts. [EXISTS]
  - `ri:version-at-save` on any RI → accept and discard (see VER-RIVAS).
- **Example:** `<ri:blog-post ri:content-title="First Post" ri:posting-day="2012/01/30"/>` → `First Post (2012/01/30)`
- **Embedding rationale:** titles/keys are text; numeric content-ids are noise.

### 2.4 Images

#### SF-IMG-ATTACH / SF-IMG-EXT
- **Detect:** `ac:image > ri:attachment[ri:filename]` | `ac:image > ri:url[ri:value]`.
- **Action:** → `<img src="./attachments/{filename}" alt="{ac:alt or filename}" title="{ac:title?}">` | `<img src="{ri:value}" alt="{ac:alt}">`.
- **Example:** `<ac:image ac:alt="topology"><ri:attachment ri:filename="net.png"/></ac:image>` → `![topology](./attachments/net.png)`
- **Embedding rationale:** alt/filename text is the only retrievable content of an image.
- **Status:** [EXISTS: `_normalise_ac_images`, lines 714–736].

#### SF-IMG-ATTRS — attribute policy
- **Detect:** official DC set `ac:align ac:border ac:class ac:title ac:style ac:thumbnail ac:alt ac:height ac:width ac:vspace ac:hspace`; Cloud extras `ac:queryparams ac:original-height ac:original-width ac:custom-width`.
- **Action:** keep `ac:alt`→`alt`, `ac:title`→`title`; **drop everything else including width/height** (pandoc's gfm `![alt](src)` cannot carry them without raw HTML).
- **Example:** `<ac:image ac:align="center" ac:width="300" ac:alt="x">…` → `![x](…)`
- **Embedding rationale:** layout attributes never reach the vector usefully; raw-HTML img tags would.
- **Status:** [CHANGE] — current handler copies width/height (lines 733–735); drop them.

#### SF-IMG-CAPTION — `ac:caption` (Cloud-origin)
- **Detect:** `ac:image > ac:caption` (rich text). Cloud-only; not written by DC 8–10 but tolerate on input (CONFSERVER-99865).
- **Action:** emit caption as an italic paragraph immediately after the image.
- **Example:** `<ac:caption><p>Fig 1: flow</p></ac:caption>` → `![…](…)` then `*Fig 1: flow*`
- **Embedding rationale:** captions are dense, human-written summaries of the figure — prime embedding text.
- **Status:** [NEW] — confirmed gap (figcaption handled only inside the diagram-placeholder path).

### 2.5 Tables

| ID | Detect | Action | Example | Rationale | Status |
|---|---|---|---|---|---|
| SF-TABLE-BASIC | `table > colgroup? + tbody > tr > th/td`; classes `wrapped relative-table fixed-table`; inline width styles; cell shading styles / `data-highlight-colour` | drop `colgroup`, all classes/styles/highlight attrs; keep `th/td` (cell-type position must survive into the AST — PF-TABLE-SIMPLIFY detects row-header tables by it) and `colspan/rowspan` (for PF-TABLE) | → pipe table | header row feeds `_summarize_table_for_embed`; presentation attrs are noise | [EXISTS: attr scrub] |
| SF-TABLE-MERGED | `td/th[rowspan,colspan]` | keep content, warn; final simplification in PF-TABLE-SIMPLIFY | merged cell content survives in its first cell | content loss is worse than lost geometry | [EXISTS: `_flag_tables`, lines 649–666] |
| SF-TABLE-CLOUD | `table[data-layout="default\|wide\|full-width"][ac:local-id]` (Cloud fabric editor, import-only) | strip both attrs | → plain table | unrepresentable + meaningless in MD | [EXISTS: attr scrub covers it; document explicitly] |
| SF-TABLE-NUMCOL | `table.numberingColumn` | strip class (rendered numbering column is generated, not stored) | → plain table | presentational; droppable per community sources | [EXISTS: scrub] |

### 2.6 Page layout

#### SF-LAYOUT — `ac:layout` family
- **Detect:** `ac:layout > ac:layout-section[ac:type=single|two_equal|two_left_sidebar|two_right_sidebar|three_equal|three_with_sidebars] > ac:layout-cell` (cell count matches type).
- **Action:** rewrite `ac:layout-section` → `div.layout`, each `ac:layout-cell` → `div.layout-col`; unwrap `ac:layout`. PF-LAYOUT-FLATTEN linearizes in document order.
- **Example:** two_equal cells `<p>left</p>` / `<p>right</p>` → `left` then `right` as sequential paragraphs.
- **Embedding rationale:** columns are visual; reading order is what chunkers and embedders need.
- **Status:** [CHANGE] — **critical bug today**: storage-form layouts are not handled, so `_drop_leftover_ac` (line 747) **decomposes `ac:layout-cell` and destroys the whole column's content**. This rule must run before the catch-all.

### 2.7 Inline elements

#### SF-INLINE-EMOTICON — both serializations
- **Detect:** `ac:emoticon[ac:name]` (legacy names: smile, sad, cheeky, laugh, wink, thumbs-up, thumbs-down, information, tick, cross, warning) and the DC 8.0+ emoji form with `ac:emoji-shortname`, `ac:emoji-id`, `ac:emoji-fallback` (`ac:name` falls back to `blue-star`).
- **Action:** preference order **`ac:emoji-shortname` (`:name:` searchable ASCII token) → `ac:name` mapped via `_EMOTICON_MAP` to a plain WORD → `ac:emoji-fallback` (literal emoji char) LAST, or report-only** (attributes are not guaranteed present per Atlassian KB; custom-emoji ids may be orphaned). The emoji-first chain may be kept for the human-docs profile (§1 profiles table).
- **Example:** `<ac:emoticon ac:name="blue-star" ac:emoji-shortname=":red_circle:" ac:emoji-fallback="(U+1F534 char)"/>` → `:red_circle:`; `<ac:emoticon ac:name="tick"/>` → the mapped word (e.g. `yes`).
- **Embedding rationale:** a `:shortname:` or mapped word is a searchable ASCII token; literal emoji add no vector signal and trip the documented cp1252 console pitfalls — the same reasoning PF-ADMONITION and HX-STATUS use to strip emoji prefixes.
- **Status:** [CHANGE] — `_normalise_emoticons` (lines 580–585) reads only `ac:name`; add the fallback chain.

#### SF-INLINE-TIME — date lozenge (both input kinds)
- **Detect:** `<time datetime="2019-01-01" />` (self-closing, usually empty).
- **Action:** replace with the ISO date as plain text. Runs in BOTH A1 and A2, BEFORE the blanket unwrap/scrub — pandoc drops a self-closing `time` at read, so a Stage-C rule is physically unreachable; this MUST stay a Stage-A rule.
- **Example:** `<time datetime="2019-01-01"/>` → `2019-01-01`
- **Embedding rationale:** a self-closing `time` is dropped by pandoc — the date (often a deadline) would be lost.
- **Status:** [NEW] — confirmed gap.

#### SF-INLINE-PLACEHOLDER — instructional text
- **Detect:** `ac:placeholder`, `ac:placeholder[ac:type=mention]`.
- **Action:** **delete entirely** (template/blueprint-only; never shown on saved pages).
- **Example:** `<ac:placeholder>Describe the decision…</ac:placeholder>` → *(nothing)*
- **Embedding rationale:** boilerplate instructions poison retrieval (“describe the decision” matches every query about decisions).
- **Status:** [CHANGE] — `_normalise_template_vars` (line 743) currently renders it as `*[text]*`; drop instead.

#### SF-INLINE-COMMENT — inline comment marker (storage form)
- **Detect:** `ac:inline-comment-marker[ac:ref=<uuid>]`.
- **Action:** unwrap, keep inner text. Must run **before** the catch-all.
- **Example:** `<ac:inline-comment-marker ac:ref="216…">annotated text</ac:inline-comment-marker>` → `annotated text`
- **Embedding rationale:** the wrapped span is real page prose; the UUID is noise.
- **Status:** [CHANGE] — the rendered-HTML form is unwrapped (lines 251–252) but the `ac:` form hits `_drop_leftover_ac` and is **decomposed, losing the text**.

### 2.8 Template constructs

| ID | Detect | Action | Example | Rationale | Status |
|---|---|---|---|---|---|
| SF-TMPL-DECL | `at:declarations` (with `at:string`, `at:textarea`, `at:list`/`at:option`) | delete the whole block | → *(nothing)* | form definitions, never content | [NEW — make explicit; today removed only by catch-all decompose] |
| SF-TMPL-VAR | `at:var[at:name]` | → `{name}` placeholder text | `<at:var at:name="MyText"/>` → `{MyText}` | a named slot is at least greppable | [EXISTS: `_normalise_template_vars`, lines 741–742] |

### 2.9 Macro anatomy and policy

#### SF-MACRO-ANATOMY — parsing contract
- **Detect:** `ac:structured-macro[ac:name][ac:schema-version][ac:macro-id]`; parameters as `ac:parameter[ac:name]` with the **unnamed default parameter as `ac:name=""`**; bodies as `ac:plain-text-body` (CDATA), `ac:rich-text-body` (XHTML), or bodiless. **Also accept** the legacy `<ac:macro>`/`<ac:default-parameter>` serialization (CONF 5.0-era; input-only, never emit). Parameter *values* may contain resource identifiers (`ri:attachment`, `ri:user`, `ri:page`, sometimes wrapped in `ac:link`) instead of text — handle element-valued params per macro.
- **Action:** dispatch on `ac:name` to the per-macro rules below; route unmatched names to SF-MACRO-UNKNOWN.
- **Status:** [CHANGE] — partial today (no dispatcher; only catch-all unwrap/decompose).

#### SF-CDATA — CDATA mechanics
- **Detect:** `ac:plain-text-body` containing one or **multiple** CDATA sections (code containing `]]>` is split).
- **Action:** with `html.parser`, concatenate all `CData` children verbatim (preserving newlines) into the code text. Never let CDATA reach pandoc — outside `<pre>` pandoc collapses it into mangled inline text (`pythondef`-style fusions, verified).
- **Status:** [NEW] — blocked today by the lxml parse (§1).

**Macro dispatch table** (keyed on `ac:name` — real `ac:structured-macro` names ONLY, explicit and exhaustive;
an implementer keys the SF-MACRO-ANATOMY dispatcher off this table):

| Macro (`ac:name`) | Policy | Rule |
|---|---|---|
| code, noformat | convert-with-semantics | SF-MACRO-CODE / -NOFORMAT |
| info / tip / note / warning | convert-with-semantics | SF-MACRO-ADMONITION |
| panel | convert-with-semantics | SF-MACRO-PANEL |
| expand | convert-with-semantics | SF-MACRO-EXPAND |
| status | convert-with-semantics | SF-MACRO-STATUS |
| excerpt | convert-with-semantics (unwrap body) | SF-MACRO-EXCERPT |
| jira (single issue) | convert-with-semantics | SF-MACRO-JIRA |
| profile / profile-picture | convert-with-semantics | SF-MACRO-PROFILE |
| section / column | convert-with-semantics (flatten) | SF-MACRO-SECTION |
| html | convert-with-semantics (body through the Stage-A2 pre-clean) or drop+report | SF-MACRO-HTML |
| gallery | summarize-to-text (page-specific payload only; no `title` → drop+report) | SF-MACRO-GALLERY |
| view-file / viewpdf / viewdoc / viewxls / viewppt | summarize-to-text | SF-MACRO-VIEWFILE |
| multimedia | summarize-to-text | SF-MACRO-MULTIMEDIA |
| widget | summarize-to-text | SF-MACRO-WIDGET |
| chart | summarize-to-text (keep body table) | SF-MACRO-CHART |
| contentbylabel | summarize-to-text (labels/cql payload) | SF-MACRO-CBL |
| include, excerpt-include | summarize-to-text (SPACE:Title payload) | SF-MACRO-INCLUDE |
| jira (query mode) | summarize-to-text (jqlQuery payload) | SF-MACRO-JIRA |
| attachments | drop-with-no-trace (+ ConversionNotes count) | SF-MACRO-ATTACHMENTS |
| children, pagetree (+pagetreesearch) | drop-with-no-trace (+ ConversionNotes count) | SF-MACRO-CHILDREN |
| recently-updated | drop-with-no-trace (+ ConversionNotes count) | SF-MACRO-RECENT |
| toc, toc-zone (the TOC itself) | drop-with-no-trace | SF-MACRO-TOC / -TOCZONE |
| anchor | drop-with-no-trace | SF-MACRO-ANCHOR |
| loremipsum; misc report/nav macros (change-history, cheese, favpages, global-reports, listlabels, popular-labels, recently-used-labels, related-labels, livesearch, spaces-list, space-details, index, navmap, blog-posts, contributors, contributors-summary, content-report-table, html-include, im, junitreport, userlister) | drop-with-no-trace (+report count) | SF-MACRO-MISC |
| **anything else** | FALLBACK | SF-MACRO-UNKNOWN |

**Element rules table** (NOT macros — these are storage *elements* with no `ac:structured-macro`/`ac:name`
identity; they run as independent Stage-A element rules and are unreachable via the macro dispatcher —
keying the dispatcher on them would add dead entries):

| Element | Rule |
|---|---|
| `ac:task-list` / `ac:task` | SF-LIST-TASK |
| `ac:emoticon` | SF-INLINE-EMOTICON |
| `<time datetime>` | SF-INLINE-TIME (stays Stage A — pandoc drops self-closing `time` at read) |
| `ac:image > ac:caption` | SF-IMG-CAPTION |
| `ac:placeholder` | SF-INLINE-PLACEHOLDER |
| `ac:inline-comment-marker` | SF-INLINE-COMMENT |
| `ac:link > ri:user` (mentions) | SF-LINK-USER |
| `ac:adf-extension` (decision lists, Cloud panels) | SF-ADF (runs BEFORE the catch-all) |

### 2.10 Per-macro rules

#### SF-MACRO-CODE
- **Detect:** `ac:structured-macro[ac:name=code]`; params `language`, `title`, `linenumbers`, `firstline`, `collapse`, `theme`; body `ac:plain-text-body` CDATA (possibly split, SF-CDATA).
- **Action:** → `<pre><code class="language-{mapped}">{verbatim text}</code></pre>`. Map language aliases before writing (`html/xml`→`xml`, `js`→`javascript`, `py`→`python`, `shell`→`bash`, `none`→ no class); only languages in `models._EMBED_LANGS` later earn a trusted `lang:` tag. `title` param → preceding `<p><strong>{title}</strong></p>`. Ignore `theme/linenumbers/firstline/collapse`.
- **Example:** `…ac:name="code"…<ac:parameter ac:name="language">js</ac:parameter><ac:plain-text-body><![CDATA[const x = 1;]]></ac:plain-text-body>` →
  ```` ```javascript
  const x = 1;
  ``` ````
- **Embedding rationale:** a correctly fenced+tagged block gets the `lang:` embed tag and is splittable as CODE; mangled CDATA text is corpus poison.
- **Status:** [CHANGE] — code-fence machinery exists (`_rebuild_pre`, `_normalise_code_blocks`) but the storage path is broken by the lxml CDATA drop; add the macro dispatcher + alias map.

#### SF-MACRO-NOFORMAT
- **Detect:** `ac:name=noformat`; param `nopanel`; CDATA body.
- **Action:** fenced code block with **no** language class.
- **Example:** → ```` ``` raw text ``` ````
- **Embedding rationale:** monospace dumps stay verbatim, never re-flowed into prose.
- **Status:** [NEW].

#### SF-MACRO-ADMONITION
- **Detect:** `ac:name=info|tip|note|warning`; params `title` (optional), `icon`; body `ac:rich-text-body`.
- **Action:** → `div.adm[data-macro={name}][data-title={title}]` with the rich-text-body **children preserved as blocks** (not flattened). PF-ADMONITION renders `> **Note — {title}:**` + quoted body blocks.
- **Example:** `<ac:structured-macro ac:name="warning"><ac:parameter ac:name="title">Hot path</ac:parameter><ac:rich-text-body><p>Do <em>not</em> retry.</p></ac:rich-text-body></ac:structured-macro>` →
  ```
  > **Warning — Hot path:**
  > Do *not* retry.
  ```
- **Embedding rationale:** “Warning” as a plain English word is searchable; emoji prefixes add no vector signal and trip the cp1252 console; flattening loses lists/code inside the body.
- **Status:** [CHANGE] — `_MACRO_LABELS`/`_normalise_macros` (lines 371–411) exists for the rendered form but uses emoji labels and `get_text` flattening; the storage form has no handler at all.

#### SF-MACRO-PANEL
- **Detect:** `ac:name=panel`; params `title`, `borderStyle/borderColor/borderWidth/bgColor/titleBGColor/titleColor` (all dropped); rich body.
- **Action:** same as admonition with `data-macro=panel`; label `**{title}**` (or `**Panel**`).
- **Example:** → `> **My Panel Title:**` + body.
- **Embedding rationale:** panels usually hold callout-grade content; the colour params are pure chrome.
- **Status:** [CHANGE] — rendered-form handler exists (lines 414–429, text-flattening); storage form [NEW].

#### SF-MACRO-EXPAND
- **Detect:** `ac:name=expand`; param `title` (legacy: default parameter); rich body.
- **Action:** → `div.expand[data-title]` with body blocks. PF-EXPAND renders `**{title}**` paragraph + body inline (no `<details>` HTML).
- **Example:** → `**Click here to expand...**` then the hidden text as normal paragraphs.
- **Embedding rationale:** `<details>/<summary>` is raw HTML in the corpus and hides content from naive renderers; the body must be first-class text since expand bodies often hold the actual procedure.
- **Status:** [CHANGE] — current code emits `<details>` (lines 431–448).

#### SF-MACRO-STATUS
- **Detect:** `ac:name=status` (bodiless); params `colour` (British spelling; Grey default |Red|Yellow|Green|Blue), `title` (defaults to colour name), `subtle`.
- **Action:** → `span.lozenge[data-colour]` with the title text; PF-LOZENGE renders `**{title}**`.
- **Example:** `…colour=Green, title=On track…` → `**On track**`
- **Embedding rationale:** the status word is the signal; colour/subtle are styling. Plain bold beats inline-code-with-emoji (current) — backticked status text gets mistaken for code entities.
- **Status:** [CHANGE] — `_normalise_badges` (lines 493–524) emits inline code with emoji prefixes for the rendered form; storage form [NEW].

#### SF-MACRO-TOC / SF-MACRO-TOCZONE
- **Detect:** `ac:name=toc` (bodiless; params printable/style/maxLevel/indent/minLevel/class/exclude/type/outline/include/separator) | `ac:name=toc-zone` (rich body; extra params location/separator).
- **Action:** toc: delete, no trace. toc-zone: **unwrap the rich body** (it is real page content), delete the macro shell.
- **Example:** toc → *(nothing)*; toc-zone body `<p>Only headings…</p>` → `Only headings…`
- **Embedding rationale:** TOCs are duplicated navigation — `quality.py link_density` exists precisely to catch them.
- **Status:** toc [EXISTS: lines 239–240 for rendered form; storage form NEW]; toc-zone [NEW].

#### SF-MACRO-ANCHOR
- **Detect:** `ac:name=anchor`; unnamed default param = anchor name (legacy `<ac:default-parameter>`).
- **Action:** delete, no trace (embedding corpus carries no intra-page hrefs worth the HTML).
- **Example:** → *(nothing)*
- **Embedding rationale:** an empty named span is zero content and a guaranteed `html_leakage` hit if kept as `<a id>`.
- **Status:** [CHANGE] — `_normalise_anchors` (lines 617–626) currently preserves `<a id="…">`; drop for the embedding profile.

#### SF-MACRO-JIRA
- **Detect:** `ac:name=jira`; single-issue: `server`, `serverId`, `key`, plus optional `cache` (recognized-and-ignored — keep it out of unexpected-parameter reports); query: `jqlQuery`, `columns`, `maximumIssues`, `count`, `cache`; legacy `jiraissues` (url/columns/anonymous).
- **Action:** single issue → `[KEY-123](https://{jira}/browse/KEY-123)` if a Jira base URL is configured, else plain `KEY-123`. Query mode → one italic line `*Jira issues: {jqlQuery}*`. Legacy `jiraissues` → same via its `url`.
- **Example:** `…key=CONF-1234…` → `CONF-1234`
- **Embedding rationale:** issue keys are first-class entities for hybrid/BM25 search; an unrendered macro is residue.
- **Status:** [NEW] — confirmed gap.

#### SF-MACRO-INCLUDE / SF-MACRO-EXCERPT-INCLUDE
- **Detect:** `ac:name=include` (unnamed param = `ac:link > ri:page`, legacy `SPACE:Title` text) | `ac:name=excerpt-include` (default param = page, `nopanel`).
- **Action:** one italic line `*Includes content from {SPACE:Title}.*` (transclusion is unresolvable offline; optionally resolve when a corpus crawl includes the target).
- **Example:** → `*Includes content from DOC:My page.*`
- **Embedding rationale:** names the dependency without fabricating absent content.
- **Status:** [NEW].

#### SF-MACRO-EXCERPT
- **Detect:** `ac:name=excerpt`; params `hidden`, `atlassian-macro-output-type` (INLINE|BLOCK); rich body. DC 8–10 has **no** `name` param (first-excerpt-only; named excerpts are Cloud).
- **Action:** unwrap the rich body in place (it is authored content). `hidden=true` bodies are kept (resolved decision, §10 — they are the author's own summary text).
- **Example:** `<ac:rich-text-body><p>This is the <strong>text</strong> I want to reuse</p></…>` → `This is the **text** I want to reuse`
- **Embedding rationale:** excerpts are the author's own summary — the highest-value sentences on the page.
- **Status:** [NEW] (today survives only via the catch-all's structured-macro unwrap, losing the parameter cleanup).

#### SF-MACRO-ATTACHMENTS / SF-MACRO-GALLERY / SF-MACRO-RECENT / SF-MACRO-CBL / SF-MACRO-CHILDREN
- **Detect:** `ac:name=attachments` (old/patterns/sortBy/page/sortOrder/labels/upload/preview) | `gallery` (title/columns/page/sort/reverse/include/exclude/includeLabel/excludeLabel) | `recently-updated` (spaces/author/labels/width/types/max/theme/showProfilePic/hideHeading) | `contentbylabel` (`cql` modern; legacy labels/spaces/author/type/operator/sort/reverse/max/excerpt/showLabels/showSpace/title) | `children` (reverse/sort/style/page/excerpt/first/depth/all) and `pagetree`/`pagetreesearch` (root as nested `ac:link/ri:page`, sort, excerpt, searchBox…).
- **Action:** emit a summary line ONLY when it carries page-specific payload; constant-payload macros drop with no trace (+ `ConversionNotes` counts) — a constant sentence repeated across hundreds of pages is exactly the boilerplate SF-INLINE-PLACEHOLDER's rationale condemns (it matches every query about its topic, and under `--merge-prose` it folds identical noise tokens into many vectors):
  - attachments → *(drop + count)* — constant payload
  - gallery → `*Image gallery: {title}.*` when `title` is present; a gallery with no `title` param drops (+ count)
  - recently-updated → *(drop + count)* — constant payload
  - contentbylabel → `*Related pages by label: {labels-from-cql}.*` (page-specific payload)
  - children/pagetree → *(drop + count)* — constant payload
- **Example:** gallery with title "My holiday pictures" → `*Image gallery: My holiday pictures.*`; `<ac:structured-macro ac:name="attachments"/>` → *(nothing; report `attachments: 1`)*
- **Embedding rationale:** render-time listings cannot be reproduced offline; a page-specific sentence is searchable, but a constant one-liner is retrieval noise.
- **Status:** [NEW] for storage forms. Note: the rendered-export forms are already **silently decomposed** as chrome (lines 354–360) — that is the correct end-state; add only the ConversionNotes count.

#### SF-MACRO-VIEWFILE / SF-MACRO-MULTIMEDIA / SF-MACRO-WIDGET
- **Detect:** `ac:name=view-file|viewpdf|viewdoc|viewxls|viewppt` — **key gotcha: the `name` param value is a nested `ri:attachment` element**, not text (older content: plain text filename); page/slide/grid params vary. `multimedia` (space/page/name=nested `ri:attachment`/autostart/width/height). `widget` (url/width/height/_template).
- **Action:** → markdown link to the artifact: `[{filename}](./attachments/{filename})` (view-file/multimedia) or `[{url}]({url})` prefixed `*Embedded media:*` (widget).
- **Example:** `<ac:parameter ac:name="name"><ri:attachment ri:filename="sample.pdf"/></ac:parameter>` → `[sample.pdf](./attachments/sample.pdf)`
- **Embedding rationale:** the filename/URL is the only durable content of an embed; players and iframes are not text.
- **Status:** [NEW].

#### SF-MACRO-CHART
- **Detect:** `ac:name=chart`; **rich-text body contains the data table(s)**; huge param set (type/orientation/3D/… all presentational).
- **Action:** keep the body table(s) (they flow through SF-TABLE/PF-TABLE), preceded by one italic line `*Chart: {title} — data table below.*`; drop all chart params.
- **Example:** pie chart "Fish Sold" with a data table → `*Chart: Fish Sold — data table below.*` + pipe table.
- **Embedding rationale:** the data table is real content; the rendered image never existed in storage.
- **Status:** [NEW].

#### SF-MACRO-SECTION — section/column macros (legacy layout)
- **Detect:** `ac:name=section` (param `border`) containing `ac:name=column` macros (param `width`) in its rich body.
- **Action:** map to `div.layout` / `div.layout-col` exactly like SF-LAYOUT; PF-LAYOUT-FLATTEN linearizes.
- **Example:** two columns → sequential blocks in document order.
- **Embedding rationale:** same as SF-LAYOUT.
- **Status:** [NEW].

#### SF-MACRO-HTML — raw-HTML macro
- **Detect:** `ac:name=html`; plain-text CDATA body of raw HTML (standard DC macro, often admin-disabled but present in real corpora).
- **Action:** run the body through the **Stage-A2 pre-clean** (it IS rendered-style HTML — convert it like export input), or drop + report when that is not feasible. Never route it to the generic plain-text-body fallback: a giant raw-HTML dump fenced as a no-language code block is de-fenced by `quality.py` (html_leakage cannot see inside fences), inflates `code_ratio`, and embeds pure markup garbage.
- **Example:** `<ac:plain-text-body><![CDATA[<table>…</table>]]></ac:plain-text-body>` → converted table, or *(dropped + report entry `html: 1`)*.
- **Embedding rationale:** authored HTML content deserves conversion; markup residue in a CODE chunk is corpus poison.
- **Status:** [NEW].

#### SF-MACRO-PROFILE
- **Detect:** `ac:name=profile` / `profile-picture`; `user` param holds a nested `ri:user[ri:userkey]`.
- **Action:** resolve to display name via the SF-LINK-USER user-map → plain text `@DisplayName`; unresolved → drop + report.
- **Example:** → `@Jane Doe`
- **Embedding rationale:** identical to mentions — names embed, hex keys don't.
- **Status:** [NEW].

#### SF-MACRO-MISC — bodiless report/nav macros
- **Detect:** `ac:name` in {change-history, cheese, favpages, global-reports, listlabels, popular-labels, recently-used-labels, related-labels, livesearch, pagetreesearch, spaces-list, space-details, index, navmap, blog-posts, contributors, contributors-summary, content-report-table, html-include, im, junitreport, loremipsum, userlister}.
- **Action:** delete with no trace in prose; increment `ConversionNotes.macro_counts[name]`.
- **Example:** `<ac:structured-macro ac:name="cheese" />` → *(nothing)*
- **Embedding rationale:** all are render-time dynamic widgets; any textual stand-in would be filler.
- **Status:** [NEW] (today they survive only via the catch-all, which already warns+counts — formalize the list so they stop emitting "Dropped leftover…" warnings as *unknowns*).

#### SF-MACRO-UNKNOWN — FALLBACK (mandatory)
- **Detect:** any `ac:structured-macro` (or legacy `ac:macro`) whose `ac:name` matched no rule above.
- **Action:** bodiless → delete entirely in Stage A + `ConversionNotes` count — this is the ONE channel for unknown bodiless macros (PF-DROP handles only rendered-input leftovers, never storage macros). With `ac:rich-text-body` → unwrap the body (human-authored content survives), delete shell+params. With only `ac:plain-text-body` → fenced no-language code block, **capped at ~2 kB** — beyond the cap, drop + report (verbatim is safer than flowed, but a giant dump is corpus poison). **In every case** record the macro name in `ConversionNotes.macro_counts` / the JSON report — never emit the macro name or parameters into embeddable text.
- **Example:** `<ac:structured-macro ac:name="vendor-roadmap"><ac:rich-text-body><p>Q3 plan…</p></…>` → `Q3 plan…` (+ report entry `vendor-roadmap: 1`)
- **Embedding rationale:** untranslated macro residue is a `confluence_artifacts` block; invented placeholders are retrieval noise.
- **Status:** [EXISTS: `_drop_leftover_ac`, lines 747–764] — keep, but it must run after all the new specific handlers above (it currently destroys layout cells, comments markers, ri:user — fixed by ordering).

#### SF-ADF — ADF bridge (decision lists, Cloud panels)
- **Detect:** `ac:adf-extension > ac:adf-node[type=decision-list|decision-item|…]` with `ac:adf-attribute[key=local-id|state|panel-type]`, `ac:adf-content`, and the sibling `ac:adf-fallback` (plain-XHTML rendering — usually present, NOT guaranteed; Atlassian documents nothing about adf-*).
- **Action:** **render the `ac:adf-fallback` content when present; ignore the adf-node tree** (safest, per the catalog). For `decision-list` specifically, prefix each item with `**Decision:**` (state DECIDED) so ADR semantics survive. **Missing-fallback path:** if `ac:adf-fallback` is absent or empty, walk `ac:adf-content` and emit its text blocks (for `decision-item`, the item text with the `**Decision:**` prefix); unknown adf-node types with no usable content → drop + record the node type in `ConversionNotes`. SF-ADF MUST run before the catch-all: an unmatched `ac:adf-extension` is not `ac:structured-macro`/`ac:rich-text-body`, so `_drop_leftover_ac` (line 764) would DECOMPOSE it — silently destroying decision lists.
- **Example:** decision-item "Use Quarto" (state DECIDED) → `- **Decision:** Use Quarto`
- **Embedding rationale:** decisions are the highest-value retrieval targets in an SDD corpus (`SectionType.decision`).
- **Status:** [NEW] — absent from official docs and from the code.

---

## 3. Stage A2 — pre-clean rules for HTML-EXPORT input (HX-*)

Applies to space-export HTML and REST `export_view`. Match on **stable class names**, not `data-macro-name`
attributes (absent from space exports; present only in export_view/Cloud — see HX-EXPORTVIEW).

#### HX-ROOT — content-root selection
- **Detect:** priority chain `div#content-view` (legacy code-derived selector, not catalog-backed — the catalog documents `div#content.view`), `div.wiki-content`, `div#main-content`, `div#content` (catalog: `div#content.view` is the content wrapper, and space `index.html` pages use `#content` as the root; it also contains the attachments/comments pageSections, so HX-CHROME-ATTACH-SECTION/-COMMENTS must drop those first), `div#page-content`, `div.content-body`, Cloud `div.content-area`/`div.view` (these are likewise legacy code-derived, not catalog-backed), then `main`/`article`/`[role=main]`, then `#content #main`, `#main`, `body`.
- **Action:** everything outside the chosen root is discarded — this alone kills `head` CSS links, `#page` shell, etc. **Ordering requirement:** title/space/byline harvesting (HX-CHROME-TITLE/-METADATA) runs on the FULL soup **before `_find_content_root`** — the harvest sources (`#main-header` with `span#title-text`, `#breadcrumb-section`, `div.page-metadata`) live OUTSIDE the typical content root and are otherwise destroyed before harvesting; harvested values are handed to Stage-D frontmatter assembly, then root selection and chrome deletion proceed as today.
- **Example:** full export page → only `div#main-content.wiki-content` children survive.
- **Embedding rationale:** `#main-content.wiki-content` is the only element with author content.
- **Status:** [CHANGE] — `_find_content_root` (lines 297–327) exists, but the chain gains `div#content` and the pre-root harvest pass is [NEW].

#### HX-CHROME-TITLE — header / breadcrumbs / title
- **Detect:** `#main-header`, `#breadcrumb-section > ol#breadcrumbs`, `h1#title-heading.pagetitle > span#title-text` (text = `"SpaceName : Page Title"`).
- **Action:** **first harvest** title (strip the `"Space : "` prefix) and space name for frontmatter — on the full soup, BEFORE `_find_content_root` (see HX-ROOT) — **then** delete `#main-header` wholesale.
- **Example:** `<span id="title-text">OPS : Deploy Guide</span>` → frontmatter `title: "Deploy Guide"`, `space: "OPS"`; no body output.
- **Embedding rationale:** breadcrumbs are duplicated nav (link_density); the title belongs in provenance, not prose.
- **Status:** [CHANGE] — chrome selectors (lines 332–361) delete `header`/`.breadcrumb`, but the title is never harvested (currently inferred from H1/filename, line 1163).

#### HX-CHROME-METADATA — byline
- **Detect:** `div.page-metadata` ("Created by `span.author`, last modified by `span.editor` on date").
- **Action:** harvest author + last-modified date for frontmatter, then delete.
- **Example:** → frontmatter `author: "jsmith"`, `date: "2024-03-02"`; no body output.
- **Embedding rationale:** provenance belongs in metadata where `structural._extract_metadata` reads it; as prose it's boilerplate.
- **Status:** [CHANGE] — currently deleted without harvesting (line 352).

#### HX-CHROME-FOOTER
- **Detect:** `div#footer[role=contentinfo]` ("Document generated by Confluence on <date>").
- **Action:** optionally record export date in the report; delete.
- **Example:** → *(nothing in body)*
- **Embedding rationale:** generator boilerplate matches no useful query.
- **Status:** [EXISTS: `footer` selector, line 348].

#### HX-CHROME-ATTACH-SECTION — attachments footer section
- **Detect:** `div.pageSection.group` containing `h2#attachments.pageSectionTitle`, with `div.greybox` of `attachments/<pageId>/<attId>` links (sits inside `#content` but outside `#main-content`).
- **Action:** delete the whole section (filenames optionally to the report) **before** the generic pageSection unwrap.
- **Example:** attachments greybox → *(nothing)*
- **Embedding rationale:** a raw link dump is the canonical `link_density` failure.
- **Status:** [CHANGE] — **bug today**: line 198 unwraps every `div.pageSection` first, so when the content root is `#content` the attachment link list leaks into the corpus. Drop `#attachments`/`#comments` sections before unwrapping.

#### HX-CHROME-COMMENTS — comments section
- **Detect:** `div.pageSection` with `h2#comments.pageSectionTitle`; per-comment `div.comment-header > h4.author`, `div.comment-body > div.comment-content.wiki-content`.
- **Action:** **delete** (resolved decision, §10 — page comments are out of corpus scope; comment bodies occasionally hold decisions, but unreviewed discussion dilutes the page's vector).
- **Example:** → *(nothing)*
- **Embedding rationale:** unreviewed discussion dilutes the page's vector; if kept it must be its own provenance unit, not appended prose.
- **Status:** [NEW] (today only partially removed depending on root selection).

#### HX-ADMONITION — information macros (all generations)
- **Detect:** modern: `div.confluence-information-macro.confluence-information-macro-{information|note|warning|tip}` with optional first-child `p.title`, icon `span.aui-icon.aui-iconfont-{info|warning|error|approve}` (omitted when `icon=false`; DC 8.x+ adds `role=region`), body `div.confluence-information-macro-body`. **Legacy pre-5.x**: `div.panelMacro > table.{infoMacro|noteMacro|warningMacro|tipMacro}` with an `images/icons/emoticons/*.png` img in the first td.
- **Action:** → `div.adm[data-macro][data-title]`, body **children moved as blocks** (title from `p.title`; icon spans deleted). Same PF-ADMONITION rendering as storage input.
- **Example:** info macro with title → `> **Info — This is my title:**` + body paragraphs.
- **Embedding rationale:** as SF-MACRO-ADMONITION; one shared rendering for both input kinds.
- **Status:** [CHANGE] — `_MACRO_LABELS`/`_normalise_macros` exists but emoji-labels + `get_text`-flattens; legacy `panelMacro` table form is [NEW].

#### HX-CODE — code-block panels
- **Detect:** `div.code.panel.pdl > div.codeHeader.panelHeader.pdl? > b` (title) + `div.codeContent.panelContent.pdl > pre.syntaxhighlighter-pre[data-syntaxhighlighter-params="brush: <lang>; …"]`; older exports without the `pdl` suffix. The pre contains plain escaped text (highlighting is client-side JS, absent in exports).
- **Action:** language from `brush:` (mapped through the alias map; note `java` is Confluence's default even for shell — apply `_detect_language` heuristics when brush=java but content disagrees); title `b` → bold paragraph; rebuild as `pre > code.language-{lang}`.
- **Example:** `brush: python` panel → ```` ```python … ``` ````
- **Embedding rationale:** correct fences give trusted `lang:` tags and CODE-typed chunks.
- **Status:** [EXISTS: `_normalise_code_blocks` §17 priority order + `_lang_from_syntaxhighlighter`, lines 936–1016].

#### HX-NOFORMAT — preformatted panels
- **Detect:** `div.preformatted.panel > div.preformattedHeader.panelHeader? > b + div.preformattedContent.panelContent > pre` (no syntaxhighlighter classes).
- **Action:** treat exactly like HX-CODE with no language; title → bold paragraph.
- **Example:** → fenced block, no info string.
- **Embedding rationale:** prevents the bare-`pre` fallback from mislabeling noformat dumps via language heuristics.
- **Status:** [CHANGE] — currently caught only by the generic bare-`pre` fallback (now formalized as HX-PRE below), which runs `_detect_language` (may invent a language) and leaves the header `b` to leak as stray bold text.

#### HX-PRE — bare preformatted blocks
- **Detect:** bare `pre` with no syntaxhighlighter/codeContent/preformattedContent ancestry (paste or legacy content).
- **Action:** → fenced code block with **no** language class; `_detect_language` does NOT apply (consistent with SF-TEXT-PRE — pasted legacy text is usually not code in any specific language).
- **Example:** `<pre>raw pasted text</pre>` → ```` ``` raw pasted text ``` ````
- **Embedding rationale:** as SF-TEXT-PRE; an invented language class would mint an untrusted `lang:` tag.
- **Status:** [CHANGE] — the existing generic bare-`pre` fallback runs `_detect_language`; stop doing that.

#### HX-PANEL — generic panel
- **Detect:** `div.panel` (excluding `.code.panel`) with `div.panelHeader? > b` + `div.panelContent`; colour params as inline styles.
- **Action:** → `div.adm[data-macro=panel][data-title]`, body blocks preserved.
- **Example:** → `> **My Panel Title:**` + content.
- **Embedding rationale:** as SF-MACRO-PANEL.
- **Status:** [CHANGE] — exists (lines 414–429) but text-flattens.

#### HX-EXPAND
- **Detect:** `div.expand-container[id^=expander-] > div.expand-control` (icon img + `span.expand-control-text`, sometimes inline `onclick`) + `div.expand-content[.expand-hidden]`.
- **Action:** → `div.expand[data-title={expand-control-text}]`; keep `expand-content` children; drop the control row.
- **Example:** → `**Click here to expand...**` + body.
- **Embedding rationale:** as SF-MACRO-EXPAND.
- **Status:** [CHANGE] — exists (lines 433–448) but emits `<details>`.

#### HX-STATUS — AUI lozenges
- **Detect:** `span.status-macro.aui-lozenge` with optional `aui-lozenge-{success|error|current|complete|moved}`, `aui-lozenge-subtle`, `aui-lozenge-visual-refresh` (DC 9/10).
- **Action:** → `span.lozenge[data-colour]`; PF-LOZENGE renders `**{text}**`.
- **Example:** `<span class="status-macro aui-lozenge aui-lozenge-error">BLOCKED</span>` → `**BLOCKED**`
- **Embedding rationale:** as SF-MACRO-STATUS.
- **Status:** [CHANGE] — `_normalise_badges` emits inline code + emoji prefixes.

#### HX-TOC
- **Detect:** `div.toc-macro.rbtoc<epoch>` (match class **prefix** `rbtoc` — the suffix is a render timestamp) `> ul.toc-indentation` recursive; very old `div.toc.rbtoc*`; Cloud `div.toc-macro.client-side-toc-macro`; plus the **inline `<style>` block** that precedes it.
- **Action:** delete the div and any `<style>` elements in the body.
- **Example:** → *(nothing)*
- **Embedding rationale:** pure navigation; the lint's link_density check exists to catch exactly this.
- **Status:** [EXISTS: lines 239–240]; explicit `<style>` deletion [NEW] (cheap insurance even though pandoc usually drops it).

#### HX-TABLE
- **Detect:** `div.table-wrap > table.confluenceTable` (also `.wrapped`, `.relative-table`), `colgroup`, `th.confluenceTh[scope=col]`/`td.confluenceTd`, numbering `td.numberingColumn`, highlight classes `highlight-*`/`data-highlight-colour`; page-properties wrapper `div.plugin-tabmeta-details > div.table-wrap`.
- **Action:** unwrap `table-wrap`/`plugin-tabmeta-details`; strip classes/colgroup/highlights; keep `colspan/rowspan` for PF-TABLE; preserve `th` vs `td` cell types into the AST (PF-TABLE-SIMPLIFY detects row-header tables by `th` position). Page-properties: keep the inner table (it is a key:value provenance table) preceded by its title as a heading.
- **Example:** → pipe table.
- **Embedding rationale:** header rows feed `_summarize_table_for_embed`; the wrapper divs would otherwise leak.
- **Status:** [EXISTS: unwrap+scrub; page-props at `_normalise_page_props` lines 1019–1028 — keep, but stop discarding the table structure ([CHANGE]-minor)].

#### HX-IMG — embedded images/attachments
- **Detect:** `span.confluence-embedded-file-wrapper > img.confluence-embedded-image` with `src="attachments/<pageId>/<attachmentId>.<ext>"` (numeric ids), `data-image-src` (absolute), `data-linked-resource-default-alias` (**original filename**), `data-linked-resource-type=attachment`; export_view uses absolute src URLs; thumbnails nest the img in a link to the full file.
- **Action:** before the attribute scrub, set `alt` (if empty) from `data-linked-resource-default-alias`; keep relative src (or absolute in export_view); unwrap wrapper spans and thumbnail links.
- **Example:** → `![network-topology.png](attachments/123/456.png)`
- **Embedding rationale:** the numeric-id src is opaque — the original filename in `alt` is the only searchable token.
- **Status:** [CHANGE] — scrub keeps `src/alt` but the alias→alt copy does not exist, so most images embed as `![](attachments/123/456.png)`.

#### HX-IMG-DATA — data-URI images and inline SVG (both input kinds)
- **Detect:** `img[src^="data:"]` (base64 blobs — drawio/Gliffy previews; the existing `validate()` (line 1181) already checks "No base64 data URIs", proving the input class is real); inline `svg`, `.drawio-diagram`, `figure` (with `figcaption`).
- **Action:** data-URI img → keep the alt text only, as plain text (never the URI — `src` passes the scrub allowlist and pandoc would emit `![alt](data:image/png;base64,…)`, a multi-KB token blob); count in `ConversionNotes`. Inline `svg`/diagram figures → drop the vector tree and emit the `figcaption`/alt as an italic paragraph (per SF-IMG-CAPTION), so Stage B never receives an inline SVG tree (its text children would leak as garbled prose). Carries forward the intent of the existing `_replace_diagrams` (lines 767–787) / `--keep-diagrams`.
- **Example:** `<img src="data:image/png;base64,AAAA…" alt="auth flow">` → `auth flow` (+ count); `<figure><svg>…</svg><figcaption>Topology</figcaption></figure>` → `*Topology*`
- **Embedding rationale:** a base64 blob is pure entropy in the corpus; the alt/caption is the only retrievable content.
- **Status:** [NEW] — applies in BOTH A1 and A2.

#### HX-TASKLIST
- **Detect:** `ul.inline-task-list[data-inline-tasks-content-id] > li[data-inline-task-id]`, completed = `li.checked` (no `<input>` in static exports — checkbox is CSS).
- **Action:** synthesize checkbox inputs (or text markers) per SF-LIST-TASK.
- **Example:** `li.checked` "ship it" → `- [x] ship it`
- **Embedding rationale:** as SF-LIST-TASK.
- **Status:** [EXISTS: lines 596–601].

#### HX-EMOTICON
- **Detect:** `img.emoticon.emoticon-<name>[data-emoticon-name][alt="(alias)"]` (png or DC 7.20+ svg; class suffix and filename may differ).
- **Action:** map `alt`/`data-emoticon-name` keys to plain WORDS via the same preference chain as SF-INLINE-EMOTICON (shortname-style token → mapped word → literal char last) — A1/A2 symmetry, never emit emoji the storage path would not; fall back to the alt text.
- **Example:** `alt="(tick)"` → the mapped word (e.g. `yes`).
- **Embedding rationale:** alt text is usable plain text; a dead img path is not.
- **Status:** [EXISTS: `_normalise_emoticons`, lines 570–578].

#### HX-MENTION — user links
- **Detect:** `a.confluence-userlink.user-mention[data-username]` (Server/DC; href `/display/~user`), Cloud `data-account-id` + `/wiki/people/…`; byline variant `a.confluence-userlink.url.fn`.
- **Action:** replace with the link **text** (display name) as plain text; drop the href.
- **Example:** `<a class="confluence-userlink user-mention" data-username="jdoe">Jane Doe</a>` → `Jane Doe`
- **Embedding rationale:** profile hrefs are dead outside Confluence and inflate link_density; the name is the entity.
- **Status:** [NEW] — currently passes through as a normal link with kept href.

#### HX-JIRA
- **Detect:** `span.jira-issue[.resolved][data-jira-key]` / newer `span.confluence-jim-macro.jira-issue` containing `a.jira-issue-key[href*="/browse/"]`, `span.summary`, status `span.aui-lozenge.jira-macro-single-issue-export-pdf`; table-mode degrades to an error paragraph or plain table.
- **Action:** single issue → `[KEY-123](browse-url-stripped-of-?src=confmacro) {summary} ({status})` as one inline run; `.resolved` may append `(resolved)`. Table mode: keep a real table if present; delete refresh-module wrappers and error paragraphs.
- **Example:** → `[JENKINS-123](https://issues.example/browse/JENKINS-123) Fix agent leak (Done)`
- **Embedding rationale:** key+summary+status is dense, query-matching text; widget chrome is not.
- **Status:** [NEW] — confirmed gap.

#### HX-LAYOUT
- **Detect:** `div.contentLayout2 > div.columnLayout.{single|two-equal|two-left-sidebar|two-right-sidebar|three-equal|three-with-sidebars|fixed-width}[data-layout] > div.cell[data-type] > div.innerCell`.
- **Action:** unwrap all four levels in document order (→ `div.layout-col` for PF, or direct flatten).
- **Example:** two-equal columns → sequential blocks.
- **Embedding rationale:** as SF-LAYOUT.
- **Status:** [CHANGE] — `_normalise_layouts` (lines 629–646) inserts `<hr>` between cells; remove the separators — plain concatenation in document order (resolved decision, §10).

#### HX-INLINE-COMMENT
- **Detect:** `span.inline-comment-marker[data-ref=<uuid>]` (mainly REST view/export_view; space exports exclude inline comments per DC 10.2 docs).
- **Action:** unwrap, keep text.
- **Example:** → the annotated text, bare.
- **Embedding rationale:** the marked span is page prose.
- **Status:** [EXISTS: lines 251–252].

#### HX-ANCHOR
- **Detect:** empty `span.confluence-anchor-link[id="PageTitle-anchor"]`; heading auto-anchors `h1-h6[id="PageTitle-Heading"]`.
- **Action:** delete the empty spans; strip heading ids (pandoc/GitLab regenerate heading anchors; `structural.py` hashes its own section ids).
- **Example:** → *(nothing)* / clean `## Heading`
- **Embedding rationale:** empty named elements are zero-content HTML leakage.
- **Status:** [CHANGE] — `_normalise_anchors` keeps `<a id>`; drop for embedding output.

#### HX-PROFILE
- **Detect:** `div.profile-macro > div.vcard > a.userLogoLink[data-username|data-account-id] > img.userLogo.logo[alt="User icon: <name>"]`.
- **Action:** → plain text display name (from alt or link text).
- **Example:** → `Jane Doe`
- **Embedding rationale:** as HX-MENTION.
- **Status:** [NEW].

#### HX-GALLERY
- **Detect:** `table.gallery` whose cells reuse `span.confluence-embedded-file-wrapper > img.confluence-embedded-image` (key on the embedded-image classes, not the wrapper — gallery root is medium-confidence).
- **Action:** → one italic line `*Image gallery ({n} images): {alias1}, {alias2}, …*`; drop the thumbnails table.
- **Example:** → `*Image gallery (3 images): a.png, b.png, c.png*`
- **Embedding rationale:** a grid of thumbnail img tags embeds as nothing; filenames are searchable.
- **Status:** [NEW].

#### HX-VIEWFILE
- **Detect:** `span.confluence-embedded-file-wrapper > a.confluence-embedded-file[href*="attachments/"][data-nice-type][data-mime-type][data-linked-resource-default-alias]` (Cloud export_view adds `.conf-macro.output-inline[data-macro-name=view-file]`); sometimes degrades to a plain attachment link.
- **Action:** → `[{default-alias}]({href})`, optionally suffixed `({data-nice-type})`.
- **Example:** → `[sample.pdf](attachments/98/102.pdf) (PDF)`
- **Embedding rationale:** filename + type are the artifact's identity.
- **Status:** [NEW].

#### HX-CHILDREN-PAGETREE
- **Detect:** `ul.childpages-macro` (nested), `div.plugin_pagetree` + `ul.plugin_pagetree_children_list` (empty JS shell in static exports, with hidden fieldset of params).
- **Action:** delete + `ConversionNotes` count — no summary line (constant payload; SF-MACRO-CHILDREN policy, §10).
- **Example:** → *(nothing)*
- **Embedding rationale:** nav listings duplicate every child title into one page's vector.
- **Status:** [EXISTS: chrome selectors `.plugin_pagetree`, `.childpages-macro-container`, `.child-display`, lines 357–360 — add bare `ul.childpages-macro` to the list ([CHANGE]-minor)].

#### HX-EXPORTVIEW — REST export_view deltas
- **Detect:** body is content-only (no `#page` chrome); absolute URLs; macros rendered as anonymous user; macro roots decorated `.conf-macro.output-block|output-inline[data-macro-name][data-hasbody]`.
- **Action:** same rules apply; selectors must rely on stable classes (they already do). Use `data-macro-name`, *when present*, only as a cross-check/report enrichment. Absolute attachment URLs are kept as-is.
- **Embedding rationale:** one selector set, two export channels.
- **Status:** [EXISTS — design property of the current selector approach; document it].

---

## 4. Stage B — pandoc invocation (PD-*)

#### PD-READ `[EXISTS, pinned]`
`--from=html` with stock extensions. Verified defaults (pandoc 3.9): `+native_divs +native_spans -raw_html -empty_paragraphs`.
- `+native_divs/+native_spans` turn PFI-HTML classes/attrs into AST `Div`/`Span` for Stage C — the whole strategy rests on this.
- Do **not** enable `+raw_html`: it strips namespace prefixes from tag names and splits open/body/close into separate blocks — useless for macros, harmful for hygiene.
- HTML comments are dropped by default; keep `--strip-comments` as belt-and-braces.

#### PD-WRITE `[CHANGE]`
`--to=gfm --wrap=none --markdown-headings=atx` (replacing today's `gfm+pipe_tables` — pipe_tables is already a gfm default).
- `+smart` is deliberately **NOT** added: it would rewrite em-dash → `---`, ellipsis → `...`, curly quotes → straight, but the Stage-2 gfm reader (ast_parser.py default) has `-smart`, so nothing ever re-smartens — corpus prose would permanently carry markdown syntax characters (`A --- B`, `...` runs), which `content_density` strips as `_SYNTAX_CHARS` and which make PF-ADMONITION's own `> **Warning — Hot path:**` output impossible. Unicode punctuation stays: BGE/MiniLM tokenizers handle — and … fine; the cp1252 pitfall is a console-printing issue, not file encoding (files are UTF-8).
- `--wrap=none`: one logical line per paragraph — required by the line-oriented chunker.
- `--markdown-headings=atx`: already the default; pin it against future pandoc changes.
- **Keep writer `+raw_html` (gfm default)**: with `-raw_html` a table the filter failed to simplify becomes the literal string `[TABLE]` — total content loss. PF-TABLE makes raw HTML unnecessary; `quality.py html_leakage` proves it per file.
- gfm degrades definition lists to readable Term + linebreak paragraphs — acceptable for embedding; do not switch to the non-gfm `markdown` writer (grid tables are noise for vectors and unrendered by GitLab).

#### PD-PIPELINE `[NEW]`
Programmatic shape (cheapest, repo-native): `pandoc --from=html --to=json` on the PFI-HTML → `pf.load(io.StringIO(json_str))` → `pf.run_filter(action, doc=doc)` in-process → `pandoc --from=json --to=gfm --wrap=none --markdown-headings=atx`. Two subprocesses per document; mirrors `ast_parser.py`→`structural.py` (`pf.load` at structural.py line ~323). Frontmatter remains Stage-D string assembly (no `--standalone` needed); alternatively set `doc.metadata` in the filter and add `--standalone` — pick one, not both.

---

## 5. Stage C — panflute AST filter rules (PF-*)

All `[NEW]` — today there is no filter stage. panflute walks depth-first bottom-up, so nested layout divs
linearize correctly when each returns `list(el.content)`.
**Attribute-lookup gotcha (verified):** pandoc strips the `data-` prefix inconsistently (`data-macro` → key
`macro`, but `data-title` stays `data-title` because bare `title` collides with a known HTML attribute). Every
lookup must check both keys: `el.attributes.get('macro', el.attributes.get('data-macro'))`.

#### PF-ADMONITION
- **Match:** `pf.Div` with class `adm`.
- **Transform:** `BlockQuote(Para(Strong(Str(f"{Macro.capitalize()}{' — '+title if title else ''}:"))), *el.content)`.
- **Example:** `div.adm[data-macro=warning][data-title=Hot path]` → `> **Warning — Hot path:**` + quoted body.
- **Embedding rationale:** admonition type becomes a plain searchable word inside the same chunk as its body.

#### PF-CODELANG
- **Match:** `pf.CodeBlock`.
- **Transform:** normalize the first class through the alias map (`js`→`javascript`, `html/xml`→`xml`, `py`→`python`, `none`→remove); strip a `language-` prefix (the gfm writer handles either, but normalized classes let `models._EMBED_LANGS` trust checks work downstream).
- **Example:** CodeBlock classes `["language-js"]` → fence ` ```javascript `.
- **Embedding rationale:** only trusted languages earn `lang:` embed tags.

#### PF-LAYOUT-FLATTEN
- **Match:** `pf.Div` with class in `{layout, layout-col}` (and any surviving `columnLayout/cell/innerCell`).
- **Transform:** `return list(el.content)` — splices children in place, document order.
- **Example:** two columns → sequential paragraphs.
- **Embedding rationale:** reading order without wrapper divs leaking as raw HTML.

#### PF-EXPAND
- **Match:** `pf.Div` with class `expand`.
- **Transform:** `[Para(Strong(Str(title or "Details"))), *el.content]` (bold paragraph, not a heading — keeps the section tree stable; resolved decision, §10).
- **Example:** → `**Prerequisites**` + body blocks.
- **Embedding rationale:** the hidden body becomes first-class prose in the same section.

#### PF-LOZENGE
- **Match:** `pf.Span` with class `lozenge`.
- **Transform:** `Strong(Str(pf.stringify(el)))`.
- **Example:** → `**On track**`
- **Embedding rationale:** without this, gfm (+raw_html) leaks the literal `<span class=…>` (verified).

#### PF-INLINE-TEXT — native inline-text normalization (u / sup / sub / strike)
- **Match:** `pf.Underline`, `pf.Superscript`, `pf.Subscript`, `pf.Strikeout` — pandoc's HTML reader produces these natively from literal `<u>`/`<sup>`/`<sub>`/`<s>`/`<del>`/`<strike>` (verified, pandoc 3.9), so ONE Stage-C rule covers both input kinds.
- **Transform:** Underline → splice contents (GFM has no underline; gfm would otherwise emit raw `<u>`). Superscript: a footnote-style marker (single digit/symbol) → drop + report; otherwise emit `^` notation — `m^2` — because gluing to `m2` corrupts units and welds footnote markers into words (mutated tokens mis-feed entity extraction). Subscript → plain unwrap (CO2-style chemical subscripts read fine glued). Strikeout → keep (gfm renders `~~ ~~` natively).
- **Example:** `m<sup>2</sup>` → `m^2`; `<u>key</u>` → `key`; `CO<sub>2</sub>` → `CO2`.
- **Embedding rationale:** the gfm writer passes `<u>`/`<sup>`/`<sub>` through as raw HTML (verified) — leakage `quality._HTML_LEAKAGE` cannot currently see (its regex lacks these tags; §9).

#### PF-DROP
- **Match:** decorative spans and tracking imgs that survived Stage A (rendered-input leftovers only — unknown storage macros are deleted in Stage A by SF-MACRO-UNKNOWN, the single channel).
- **Transform:** `return []`.
- **Embedding rationale:** nothing-in-prose policy for unrenderables.

#### PF-TABLE-SIMPLIFY
- **Match:** `pf.Table` whose cells contain block elements or row/colspans (pipe tables cannot represent either — pandoc manual); also tables whose `th` cells sit in the first COLUMN (row-header tables — "header cells can appear in any row/column" per the catalog).
- **Transform:** **simplify, unconditionally total** — stringify EVERY cell's blocks to a single inline run (joining with `; `), drop spans (content stays in the first cell) → the writer always emits a pipe table. Every cell is reducible once nested tables are flattened in Stage A; add a filter-level assertion/report if a Table would still be unrepresentable — that is a conversion failure (§1: raw-HTML output is lint-blocked AND silently dropped downstream), never an output mode. Row-header tables: render the column-1 `th` cells as bold inline text within their row, and do NOT treat row 1 as the header when it contains `td` cells.
- **Example:** table with a list inside a cell → pipe table with `item1; item2` cell; a row-header row → `| **Owner** | Jane Doe |`.
- **Embedding rationale:** guarantees zero raw `<table>` fallback; mirrors `_summarize_table_for_embed` semantics so embed-text and source agree.

#### PF-TABLE-PIPE-IN-CODE
- **Match:** `pf.Code` inline elements inside table cells whose text contains `|`.
- **Transform:** escape the pipe as `\|` in the serialized cell (emit the Code inline as a RawInline carrying `\|`, or post-fix in Stage D with a table-row-scoped regex) — pandoc emits `|` unescaped inside Code in cells (verified) and GitLab splits the row on it; GitLab and GitHub both render `\|` inside code spans in table cells as a literal pipe. Never substitute a different character: content must stay byte-identical for BM25/hybrid exact-match and entity extraction (`kubectl get pods | grep x` must remain a real command).
- **Example:** `` `a | b` `` in a cell → serialized as `` `a \| b` `` (renders as `a | b`).
- **Embedding rationale:** prevents silent table corruption; only the markdown serialization changes, never the content.

#### PF-HYGIENE-UNWRAP (must be the filter's last clause)
- **Match:** any `pf.Div`/`pf.Span` not consumed above.
- **Transform:** `return list(el.content)`.
- **Embedding rationale:** an unconsumed `Div` is emitted by gfm as literal `<div …>` raw HTML (verified, even for empty divs) — direct `html_leakage` violation.
- *(Stage A's blanket unwrap/scrub runs first but is PFI-aware — `[CHANGE]`, §1 PFI contract — so PFI-classed
  elements reach this filter intact; this clause is the final net once Stage C has consumed them.)*

#### PF-JUNK-PARA
- **Match:** `pf.Para`/`pf.Plain` whose `stringify()` contains no alphanumerics.
- **Transform:** `return []`.
- **Example:** the lone `\` from a `<p><br/></p>` → *(nothing)*.
- **Embedding rationale:** kills junk chunks at the source instead of at export (`[CHANGE]` of responsibility, same outcome).

---

## 6. Stage D — markdown post-process rules (MD-*, regex level)

| ID | Detect (regex) | Action | Status |
|---|---|---|---|
| MD-NBSP | U+00A0 | → plain space | [EXISTS: line 1089] |
| MD-FENCE-SPACE | `^``` (\w` | `` ```yaml `` (remove pandoc's space) | [EXISTS: line 1092] |
| MD-UNESCAPE-EMPH | `\\(\*\*)`, `\\(\*)` | unescape bold/italic over-escapes | [CHANGE — must become fence-aware; today it corrupts fenced code containing literal `\*`] |
| MD-TASKBOX | `(^\s*[-*+] )\\\[( \|x)\\\]` | `- [x]` (needed only while text-marker task lists remain; obsolete once checkbox inputs land) | [EXISTS: line 1103] |
| MD-TOC-ESCAPED | over-escaped `[[_TOC_]]` remnants | delete | [EXISTS: lines 1106–1110] |
| MD-BLANKLINES | `\n{3,}` | → `\n\n` | [EXISTS: line 1113] |
| MD-TRAILWS | trailing whitespace per line | strip | [EXISTS: line 1116] |
| MD-FINAL-NL | EOF | exactly one `\n` | [EXISTS: line 1119] |
| MD-TOC-INJECT | n/a | inject `[[_TOC_]]` only in the *human-docs* profile; **default OFF for the embedding corpus** (a `[[_TOC_]]` paragraph survives chunking as a junk chunk and is pure nav) | [CHANGE — currently injected unless `--no-toc`, line 1155] |

**Fence-awareness (stage-wide, mandatory):** every Stage-D content regex applies ONLY to lines outside
fenced code (reuse `quality.py`'s de-fence approach, `_strip_code_preserving_lines`) — unguarded regexes
silently corrupt fenced code (a `\`-only shell-continuation line, literal `\*` in regex examples). Two draft
rules are deleted outright rather than guarded: the lone-backslash line-delete (PF-JUNK-PARA, §5, already
kills the junk paragraph at the AST level) and the angle-bracket unescape (un-escaping pandoc's deliberate
`\<` resurrects raw HTML — `List\<String\>` becomes `List<String>`, which GitLab swallows as an unknown tag
and which can trip `_HTML_LEAKAGE`).

**Embedding rationale (stage-wide):** these are the final defenses for `quality.py` checks — escape residue and
blank-line bloat are exactly what `html_leakage`/`content_density` measure.

---

## 7. Frontmatter / provenance rules (FM-*)

Emit YAML frontmatter with **exactly the key names `structural._extract_metadata` reads back** (structural.py
lines 43–73): `title`, `space`, `url`, `author`, `date`, `labels` — plus extras for citability.

| ID | Key | Source (storage input) | Source (export input) | Status |
|---|---|---|---|---|
| FM-TITLE | `title` | REST page object (`title`) — body.storage has no title; pass as parameter | `span#title-text` minus `"Space : "` prefix; fallback `head > title` (same `"Space : "` strip — survives `Page.htmlexport.vm` customization, can also seed FM-SPACE); then first H1/filename | [CHANGE: harvest from #title-text; today `--title` flag or `_infer_title` only] |
| FM-SPACE | `space` | REST `space.key` / CLI `--space` | title prefix or breadcrumb; CLI `--space` | [EXISTS: CLI flag, line 1141; harvesting NEW] |
| FM-URL | `url` | `{base}/pages/viewpage.action?pageId={id}` or `_links.webui` | CLI `--source-url` | [EXISTS: `--source-url` → `url:`, line 1143] |
| FM-AUTHOR | `author` (singular) | REST `history.createdBy.displayName` | `div.page-metadata` byline | [CHANGE — postprocess writes `authors:` (list, lines 1133–1135) which `_extract_metadata` **does not read**; emit `author:`] |
| FM-DATE | `date` | REST `version.when` | page-metadata "last modified on …" | [NEW] |
| FM-LABELS | `labels` (list) | REST labels / CLI `--labels` | CLI `--labels` | [EXISTS: lines 1144–1146] |
| FM-PAGEID | `page_id` | REST `id` | `attachments/<pageId>/` paths or export filename `Title_<pageId>.html` | [NEW — ignored by structural today; harmless, future-citable] |
| FM-VERSION | `version` | REST `version.number` | n/a (export has no version) | [NEW — same caveat] |
| FM-SOURCEFILE | `source_file` | input filename | input filename | [EXISTS: line 1148] |

**FM-YAML-SAFE `[NEW]`** — serialization rule for every FM-* value: emit via a real YAML dumper or
`json.dumps(value)` (valid YAML scalar quoting), and round-trip self-check the emitted frontmatter (parse it
before writing; on failure fall back to a sanitized title + `ConversionNotes` warning). Today `postprocess`
builds frontmatter with naive f-strings (`f'title: "{doc_title}"'`, line 1130) — an embedded double quote
(`OPS : Deploy "v2"`) produces invalid YAML; Stage 2's gfm reader has `+yaml_metadata_block` (verified), and a
failed parse degrades the `---` block into document content: `title:`/`url:` lines leak into the first
section's chunks and ALL provenance is lost for every chunk of that document.

**Embedding rationale:** these keys flow through `DocumentMetadata` onto every `SemanticChunk`
(`title`/`source_url`/`space`/`labels`), making each exported record citable on its own — provenance lives in
metadata, never in embeddable prose.

---

## 8. Version-specific handling, Confluence 8.0 → 10.x (VER-*)

The official storage-format reference is frozen across 8.0–10.2 — **one rule base covers the whole window**
provided the following tolerances are in place:

| ID | Construct | Handling | Status |
|---|---|---|---|
| VER-EMOJI | DC 8.0+ emoji on `ac:emoticon` (`ac:emoji-shortname`, `ac:emoji-id`, `ac:emoji-fallback`; `ac:name="blue-star"` for non-legacy) | preference chain shortname → mapped word → literal fallback char LAST (SF-INLINE-EMOTICON); attributes not guaranteed present; deleted custom emojis orphan their ids | [CHANGE] |
| VER-CAPTION | `ac:caption` child of `ac:image` — Cloud-only, never written by DC, not preserved by Cloud→DC migration (CONFSERVER-99865) | tolerate on input → SF-IMG-CAPTION | [NEW] |
| VER-ADF | `ac:adf-extension`/`ac:adf-node`/`ac:adf-attribute`/`ac:adf-content`/`ac:adf-fallback` — present throughout 8.0–10.x, undocumented | render `ac:adf-fallback` when present; otherwise walk `ac:adf-content` (SF-ADF missing-fallback path); decision-list gets `**Decision:**` prefix (SF-ADF) | [NEW] |
| VER-DATALAYOUT | `table[data-layout][ac:local-id]`, `ac:custom-width/ac:original-height/ac:original-width/ac:queryparams` on images — Cloud-import only | strip silently (SF-TABLE-CLOUD, SF-IMG-ATTRS) | [EXISTS via scrub] |
| VER-RIVAS | `ri:version-at-save` on `ri:page`/`ri:attachment` — written by the editor in all versions, absent from doc examples | accept on any RI, discard | [EXISTS — attr never read] |
| VER-LEGACY-MACRO | `<ac:macro>`/`<ac:default-parameter>` (CONF 5.0-era) in old content | accept as input alias of `ac:structured-macro`/`ac:parameter[ac:name=""]`; never emit | [NEW] |
| VER-USERID | `ri:userkey` (DC) vs `ri:account-id` (Cloud import) vs `ri:username` (old exports) | accept all three in SF-LINK-USER | [NEW] |
| VER-CBL | `contentbylabel`: modern single `cql` param vs legacy discrete params (labels/spaces/operator/…) | accept both in SF-MACRO-CBL | [NEW] |
| VER-LOZENGE | `aui-lozenge-visual-refresh` added by DC 9/10 skins | class list already matched by prefix `aui-lozenge` (HX-STATUS) | [EXISTS] |
| VER-EXPORT-DECOR | `conf-macro output-block/output-inline` + `data-macro-name/data-hasbody` present in export_view (and Cloud), **absent** from space-tools HTML exports | match stable class names only; use data attrs opportunistically for the report (HX-EXPORTVIEW) | [EXISTS] |
| VER-LEGACY-ADMONITION | pre-5.x `div.panelMacro > table.{x}Macro` admonitions in ancient exports | HX-ADMONITION legacy branch | [NEW] |
| VER-CODE-PDL | pre-5.5 code panels without the `pdl` class suffix | selectors match on `div.code.panel` without requiring `pdl` | [EXISTS] |

---

## 9. Quality guards — rules ↔ lint checks (`quality.py`)

Every conversion must pass `sdd-pipeline lint` on its output. Mapping of rule families to the six checks:

| Lint check (quality.py) | Satisfied by | Failure meaning |
|---|---|---|
| `html_leakage` (block >3) | SF/HX attribute scrub + wrapper unwrap [lines 262–287, PFI-aware per the §1 contract — [CHANGE]], PF-HYGIENE-UNWRAP, PF-LOZENGE, PF-TABLE-SIMPLIFY (no raw `<table>` fallback), PF-INLINE-TEXT (u/sup/sub/strike), SF-TEXT-SMALLBIG / SF-TEXT-STRIKE / SF-INLINE-TIME (Stage A, both input kinds), HX-ANCHOR. **Lint blind spot [CHANGE to quality.py line 38]:** `_HTML_LEAKAGE` matches only `span|div|p|a|strong|em|table|td|tr|th` — extend it with `u|sup|sub|s|del|code|pre|img`, or this entire leak class stays invisible to the very lint this table claims verifies it | a Stage A/C unwrap rule missed a wrapper or a table fell back to raw HTML |
| `confluence_artifacts` (block) | SF-MACRO-* dispatcher + SF-MACRO-UNKNOWN catch-all [EXISTS `_drop_leftover_ac`], SF-CDATA, VER-LEGACY-MACRO | an `ac:`/`ri:` tag or `{macro}` wiki residue survived — ordering bug in Stage A1 |
| `code_ratio` (warn >0.75) | SF-MACRO-CODE/HX-CODE produce *bounded, correctly fenced* blocks; whole-page code dumps still warn **by design** (the lint flags the page, not the converter) | page is a raw dump — route to `--merge-definitions` or exclude |
| `link_density` (warn >0.5) | SF-MACRO-TOC/TOCZONE, HX-TOC, HX-CHROME-* (breadcrumbs, attachments section, footer), HX-CHILDREN-PAGETREE, HX-MENTION (de-linking), SF-LINK-PAGE plain-text fallback, summarize-to-text one-liners | a nav structure leaked — usually a new TOC/list macro variant |
| `content_density` (block <200 chars) | drop-with-no-trace policy keeps stubs honest; summarize-to-text adds minimal text *deliberately* so stub pages still get flagged rather than padded | the page is genuinely a stub — exclude from the corpus |
| `orphaned_headings` (warn) | PF-EXPAND emitting **bold**, not headings; PF-LAYOUT-FLATTEN keeping content under its original heading; SF-MACRO-* never emitting empty headings | a heading-producing rule fired with an empty body |

Additional embed-layer constraints (models.py/chunking.py):
- PF-CODELANG's alias map must target `models._EMBED_LANGS` names so `lang:` tags are trusted in `to_embed_text`.
- PF-TABLE-SIMPLIFY keeps header rows intact because `_summarize_table_for_embed` keys on them. Row-header
  tables (th in column 1) have no header row — `_summarize_table_for_embed` keys on row 1 regardless;
  acceptable, flag in ConversionNotes.
- MD-TOC-INJECT default-off keeps the `[[_TOC_]]` paragraph out of chunk streams.
- Conversion metrics/notes (`ConversionNotes`: warnings, macro_counts, languages [EXISTS]) are the **only**
  channel for unknown-macro names, unresolved links, and dropped dynamic content — never the markdown.

---

## 10. Resolved decisions

Decisions taken during drafting and review; each rule above states the *what*, this table records the *that
it was decided* (rejected alternatives are described in prose in the rules themselves, deliberately not by
name here).

| Decision | Resolution |
|---|---|
| Expand title rendering | bold paragraph (no heading, no `<details>`) — PF-EXPAND |
| Page-comments section | **drop** (user decision) — HX-CHROME-COMMENTS |
| Unresolvable page links | plain text, no `href="#"` stubs — SF-LINK-PAGE |
| Hidden excerpts (`hidden=true`) | keep body (authored summary text) — SF-MACRO-EXCERPT |
| Status lozenge | `**{title}**`; colour name only when title absent — SF-MACRO-STATUS/PF-LOZENGE |
| Layout flattening | plain concatenation, no `<hr>` separators — SF-LAYOUT/HX-LAYOUT/PF-LAYOUT-FLATTEN |
| Dynamic-macro one-liners | page-specific payload only; constant-payload → drop + report — SF-MACRO-ATTACHMENTS et al. |
| `[[_TOC_]]` injection | default OFF for the embedding corpus profile — MD-TOC-INJECT |
| Unknown macros | macro name/params never in prose (report only); authored bodies survive — rich body unwrapped, plain-text body fenced (~2 kB cap), bodiless deleted — SF-MACRO-UNKNOWN |
| Old wiki page (`confluence-storage-format-gitlab-markdown`) | superseded wholesale by this document |
| Smart punctuation | writer stays plain `gfm`; Unicode punctuation kept in the corpus — PD-WRITE |

---

## 11. Coverage matrix (appendix)

Generated from the research catalog (76 storage/rendering constructs + 11 version deltas). Column 1 is the
catalog's element `name` verbatim.

| Catalog element | Rule(s) |
|---|---|
| `Headings` | SF-TEXT-HEADING |
| `Paragraph / alignment` | SF-TEXT-PARA |
| `Strong (bold)` | SF-TEXT-BOLD |
| `Emphasis (italic)` | SF-TEXT-ITALIC |
| `Underline` | SF-TEXT-UNDERLINE → PF-INLINE-TEXT |
| `Strikethrough` | SF-TEXT-STRIKE / HX-TEXT-STRIKE, PF-INLINE-TEXT |
| `Superscript / Subscript` | SF-TEXT-SUPSUB → PF-INLINE-TEXT |
| `Monospace` | SF-TEXT-MONO |
| `Preformatted` | SF-TEXT-PRE, HX-PRE |
| `Blockquote` | SF-TEXT-BLOCKQUOTE |
| `Text color` | SF-TEXT-COLOR |
| `Small / Big` | SF-TEXT-SMALLBIG |
| `Line break` | SF-TEXT-BR |
| `Horizontal rule` | SF-TEXT-HR |
| `Dash entities` | SF-TEXT-ENTITY |
| `Bullet list` | SF-LIST-UL |
| `Numbered list` | SF-LIST-OL |
| `Task list` | SF-LIST-TASK, HX-TASKLIST |
| `External link` | SF-LINK-EXT |
| `Page link` | SF-LINK-PAGE |
| `Attachment link` | SF-LINK-ATTACH |
| `Anchor link` | SF-LINK-ANCHORLINK |
| `User mention link` | SF-LINK-USER, HX-MENTION |
| `Link bodies (plain vs rich)` | SF-LINK-BODY |
| `Shortcut link` | SF-LINK-SHORTCUT |
| `Image (attached)` | SF-IMG-ATTACH, HX-IMG |
| `Image (external)` | SF-IMG-EXT |
| `Image attributes` | SF-IMG-ATTRS |
| `Image caption (ac:caption)` | SF-IMG-CAPTION, VER-CAPTION |
| `Table` | SF-TABLE-BASIC, HX-TABLE, PF-TABLE-SIMPLIFY |
| `Merged cells` | SF-TABLE-MERGED, PF-TABLE-SIMPLIFY |
| `Table data-layout` | SF-TABLE-CLOUD, VER-DATALAYOUT |
| `Numbering column` | SF-TABLE-NUMCOL |
| `Page layout` | SF-LAYOUT, HX-LAYOUT, PF-LAYOUT-FLATTEN |
| `Emoticon (legacy)` | SF-INLINE-EMOTICON, HX-EMOTICON |
| `Emoticon (emoji form, DC 8.0+)` | SF-INLINE-EMOTICON, VER-EMOJI |
| `Date lozenge` | SF-INLINE-TIME |
| `Placeholder (instructional text)` | SF-INLINE-PLACEHOLDER |
| `Inline comment marker` | SF-INLINE-COMMENT, HX-INLINE-COMMENT |
| `Template variables (at: namespace)` | SF-TMPL-DECL, SF-TMPL-VAR |
| `ri:page` | SF-LINK-PAGE |
| `ri:blog-post` | SF-RI-MISC |
| `ri:attachment` | SF-LINK-ATTACH, SF-IMG-ATTACH |
| `ri:url` | SF-RI-MISC, SF-IMG-EXT |
| `ri:shortcut` | SF-LINK-SHORTCUT |
| `ri:user` | SF-LINK-USER, VER-USERID |
| `ri:space` | SF-RI-MISC |
| `ri:content-entity` | SF-RI-MISC |
| `Macro anatomy (ac:structured-macro)` | SF-MACRO-ANATOMY, SF-CDATA, VER-LEGACY-MACRO |
| `code macro` | SF-MACRO-CODE, HX-CODE, PF-CODELANG |
| `noformat macro` | SF-MACRO-NOFORMAT, HX-NOFORMAT |
| `info / tip / note / warning macros` | SF-MACRO-ADMONITION, HX-ADMONITION, PF-ADMONITION, VER-LEGACY-ADMONITION |
| `panel macro` | SF-MACRO-PANEL, HX-PANEL |
| `expand macro` | SF-MACRO-EXPAND, HX-EXPAND, PF-EXPAND |
| `status macro` | SF-MACRO-STATUS, HX-STATUS, PF-LOZENGE, VER-LOZENGE |
| `toc macro` | SF-MACRO-TOC, HX-TOC |
| `toc-zone macro` | SF-MACRO-TOCZONE |
| `anchor macro` | SF-MACRO-ANCHOR, HX-ANCHOR |
| `jira macro` | SF-MACRO-JIRA, HX-JIRA |
| `include macro` | SF-MACRO-INCLUDE |
| `excerpt macro` | SF-MACRO-EXCERPT |
| `excerpt-include macro` | SF-MACRO-INCLUDE |
| `attachments macro` | SF-MACRO-ATTACHMENTS, HX-CHROME-ATTACH-SECTION |
| `gallery macro` | SF-MACRO-GALLERY, HX-GALLERY |
| `children macro` | SF-MACRO-CHILDREN, HX-CHILDREN-PAGETREE |
| `pagetree macro` | SF-MACRO-CHILDREN, HX-CHILDREN-PAGETREE |
| `widget macro (Widget Connector)` | SF-MACRO-WIDGET |
| `view-file family (view-file, viewpdf, viewdoc, viewxls, viewppt)` | SF-MACRO-VIEWFILE, HX-VIEWFILE |
| `profile macro (User Profile)` | SF-MACRO-PROFILE, HX-PROFILE |
| `recently-updated macro` | SF-MACRO-RECENT |
| `contentbylabel macro` | SF-MACRO-CBL, VER-CBL |
| `multimedia macro` | SF-MACRO-MULTIMEDIA |
| `chart macro` | SF-MACRO-CHART |
| `section / column macros` | SF-MACRO-SECTION |
| `anchor/navigation report macros (misc bodiless)` | SF-MACRO-MISC |
| `ADF bridge (ac:adf-extension family)` | SF-ADF, VER-ADF |

**Version deltas** (11, from the catalog's version-change list; each row quotes a distinctive verbatim
substring):

| VC | Catalog version-change (distinctive quote) | Rule(s) / disposition |
|---|---|---|
| VC-01 | "Official storage-format reference is effectively FROZEN" across 8.0–10.x | §8 preamble — one rule base covers the window |
| VC-02 | "Confluence DC 8.0 added the emoji menu" | VER-EMOJI, SF-INLINE-EMOTICON |
| VC-03 | ADF bridge elements "exist throughout 8.0-10.x for decision lists" yet undocumented | VER-ADF, SF-ADF |
| VC-04 | "Cloud-only constructs that never entered DC 8-10 storage" (caption, data-layout, account-id, image extras) | VER-CAPTION, VER-DATALAYOUT, VER-USERID, SF-IMG-ATTRS |
| VC-05 | ri:version-at-save "absent from all official doc examples" | VER-RIVAS |
| VC-06 | "the unnamed default parameter as" `ac:parameter ac:name=""` + legacy serialization | SF-MACRO-ANATOMY, VER-LEGACY-MACRO |
| VC-07 | contentbylabel switched to "a single 'cql' parameter in modern storage" | VER-CBL, SF-MACRO-CBL |
| VC-08 | DC excerpt "still has no 'name' parameter through 10.2" | SF-MACRO-EXCERPT |
| VC-09 | "Storage Format Source Editor became bundled" (9.2.14 / 10.2.3) | tooling change, no format impact — correctly ignorable |
| VC-10 | URL churn: "the slug-only conf86 URL now 404s" | affects §13 citations only — no rule impact |
| VC-11 | "Nothing in the Confluence 9.0 or 10.0 platform-release notes changes page storage XML" | §8 preamble — confirms the single rule base |

---

## 12. Implementation roadmap

No code in this document — the `[CHANGE]`/`[NEW]` markers on each rule are the work items. Order of attack:

### 12.1 Fix first — verified data-loss bugs (and the lint blind spot)

1. **lxml CDATA destruction** — `html_to_gitlab_md.py:192` parses with `BeautifulSoup(html, "lxml")` while
   the code's own comment (line 679) concedes lxml DROPS CDATA: every code/noformat body and
   `ac:plain-text-link-body` is destroyed today on storage-format input. Swap Stage A1 to `html.parser`
   (§1). Flip `test_leftover_ac_stripped_no_xml` (tests/convert/test_html_to_gitlab_md.py:392), which currently
   enshrines the catch-all stripping as expected behavior.
2. **`_drop_leftover_ac` content destruction** — lines 747–764 `decompose()` every non-whitelisted `ac:*`
   element, including `ac:layout-cell` (whole columns of content) and `ac:adf-extension` (decision lists).
   Gate behind the specific handlers and ordering (SF-LAYOUT, SF-ADF, §2 preamble).
3. **pageSection attachment-list leak** — line 198 unconditionally unwraps `div.pageSection`, keeping
   Confluence's "Attachments"/"Comments" pageSections in output whenever the content root is `#content`
   (leak by omission). Drop those sections first (HX-CHROME-ATTACH-SECTION/-COMMENTS); flip
   `test_pagesection_unwrapped` (line 347). `test_prefers_content_view_over_main_content` (line 254)
   likewise enshrines the legacy root chain — revisit with HX-ROOT.
4. **`authors:` frontmatter mismatch** — `postprocess` writes `authors:` (line 1134) but
   `structural._extract_metadata` reads only `author` (singular): author provenance is silently lost
   end-to-end. Emit `author:` (FM-AUTHOR).
5. **`quality._HTML_LEAKAGE` blind spot** — the regex (quality.py lines 37–41) matches only
   `span|div|p|a|strong|em|table|td|tr|th`; extend it with `u|sup|sub|s|del|code|pre|img` (§9) so the
   inline-text leak class becomes visible to the lint.

### 12.2 Gating chain (each step unblocks the next)

`html.parser` swap (§1) → macro dispatcher (SF-MACRO-ANATOMY + the §2.9 dispatch table) → PFI-aware
unwrap/scrub (§1 PFI contract) → Stage C panflute filter (§5) → Stage D fence-aware regexes (§6).

### 12.3 [CHANGE]/[NEW] rule inventory by stage

| Stage | [CHANGE] | [NEW] |
|---|---|---|
| A1 (SF-*) | SF-TEXT-COLOR (PFI scrub), SF-TEXT-BR, SF-LIST-TASK, SF-LINK-PAGE, SF-LINK-BODY, SF-LINK-ANCHORLINK, SF-IMG-ATTRS, SF-LAYOUT, SF-INLINE-EMOTICON, SF-INLINE-PLACEHOLDER, SF-INLINE-COMMENT, SF-MACRO-ANATOMY, SF-MACRO-CODE, SF-MACRO-ADMONITION, SF-MACRO-PANEL, SF-MACRO-EXPAND, SF-MACRO-STATUS, SF-MACRO-ANCHOR | SF-TEXT-PRE, SF-TEXT-STRIKE, SF-TEXT-SMALLBIG, SF-INLINE-TIME, SF-LINK-USER, SF-LINK-SHORTCUT, SF-RI-MISC, SF-IMG-CAPTION, SF-TMPL-DECL, SF-CDATA, SF-MACRO-NOFORMAT, SF-MACRO-JIRA, SF-MACRO-INCLUDE, SF-MACRO-EXCERPT, SF-MACRO-ATTACHMENTS/-GALLERY/-RECENT/-CBL/-CHILDREN, SF-MACRO-VIEWFILE/-MULTIMEDIA/-WIDGET, SF-MACRO-CHART, SF-MACRO-SECTION, SF-MACRO-PROFILE, SF-MACRO-MISC, SF-MACRO-HTML, SF-ADF |
| A2 (HX-*) | HX-ROOT, HX-CHROME-TITLE, HX-CHROME-METADATA, HX-CHROME-ATTACH-SECTION, HX-ADMONITION, HX-NOFORMAT, HX-PRE, HX-PANEL, HX-EXPAND, HX-STATUS, HX-TABLE (minor), HX-IMG, HX-ANCHOR, HX-LAYOUT, HX-CHILDREN-PAGETREE (minor) | HX-CHROME-COMMENTS, HX-TEXT-STRIKE, HX-MENTION, HX-JIRA, HX-PROFILE, HX-GALLERY, HX-VIEWFILE, HX-IMG-DATA, HX-TOC (style deletion) |
| B (PD-*) | PD-WRITE | PD-PIPELINE |
| C (PF-*) | — | all PF-* rules (no filter stage exists today) |
| D (MD-*) | MD-UNESCAPE-EMPH (fence-aware), MD-TOC-INJECT (default OFF) | — (two draft Stage-D rules were deleted during review; §6) |
| FM (§7) | FM-TITLE, FM-AUTHOR | FM-DATE, FM-PAGEID, FM-VERSION, FM-YAML-SAFE |
| quality.py | `_HTML_LEAKAGE` tag-list extension (§9) | — |

### 12.4 Storage-format fixture acquisition

The repo's input corpus (`.tmp_dc/`) is 100% rendered HTML — zero `body.storage` samples — so every SF-*
rule is untestable today. Pull 5–10 representative pages via the §1.2 REST call covering at least:
code/CDATA (including a body with split `]]>` sections), layouts, task lists, a jira macro, and one ADF
decision list. **Fallback:** if no Confluence instance is reachable, hand-author storage-format fixtures
from the research catalog's exact `storage_syntax` samples (76 constructs), flagged as synthetic in the
fixture README.

---

## 13. Sources

Deduplicated bibliography from the three research artifacts (catalog 23, export-HTML 18, tooling 9;
duplicates merged by normalized URL — first-seen annotation kept).

### Storage-format catalog

- <https://confluence.atlassian.com/doc/confluence-storage-format-790796544.html>
- <https://confluence.atlassian.com/conf88/confluence-storage-format-1354499468.html>
- <https://confluence.atlassian.com/conf86/confluence-storage-format-1295818276.html>
- <https://confluence.atlassian.com/conf90/confluence-storage-format-1425052347.html>
- <https://confluence.atlassian.com/spaces/CONF50/pages/329980084/Confluence+Storage+Format+for+Macros>
- <https://confluence.atlassian.com/conf59/status-macro-792499207.html>
- <https://confluence.atlassian.com/conf59/info-tip-note-and-warning-macros-792499127.html>
- <https://confluence.atlassian.com/conf59/table-of-content-zone-macro-792499214.html>
- <https://confluence.atlassian.com/conf59/jira-issues-macro-792499129.html>
- <https://confluence.atlassian.com/conf59/user-profile-macro-792499223.html>
- <https://confluence.atlassian.com/doc/excerpt-include-macro-148067.html>
- <https://confluence.atlassian.com/doc/confluence-8-0-release-notes-1127254402.html>
- <https://confluence.atlassian.com/doc/confluence-8-1-release-notes-1206791873.html>
- <https://support.atlassian.com/confluence/kb/custom-emojis-are-not-displayed-as-expected-in-confluence-page/>
- <https://support.atlassian.com/confluence/kb/images-are-not-visible-on-the-page-although-they-are-listed-in-the-storage-format/>
- <https://support.atlassian.com/confluence/kb/keep-inline-comments-while-editing-confluence-pages/>
- <https://support.atlassian.com/confluence/kb/using-the-confluence-rest-api-to-upload-an-attachment-to-one-or-more-pages/>
- <https://github.com/quarto-dev/quarto-cli/discussions/2003>
- <https://jira.atlassian.com/browse/CONFSERVER-99865>
- <https://community.atlassian.com/t5/Confluence-questions/How-do-I-get-quot-lt-time-datetime-quot-2019-01-01-quot-gt-quot/qaq-p/1058486>
- <https://community.atlassian.com/forums/Confluence-questions/Display-single-issue-on-JIRA-macro-in-storage-format/qaq-p/1119319>
- <https://community.atlassian.com/forums/Data-Center-discussions/Feature-Spotlight-Emoji-experience-for-Confluence-Data-Center/td-p/2429697>
- <https://community.atlassian.com/forums/Confluence-questions/How-to-insert-numbering-column-to-a-table-and-how-to-make-the/qaq-p/2449647>

### Export-HTML patterns

- <https://confluence.atlassian.com/doc/export-content-to-word-pdf-html-and-xml-139475.html> — DC 10.2: HTML space-export contents, attachments layout, `Page.htmlexport.vm` customization, inline comments excluded
- <https://docs.atlassian.com/atlassian-confluence/5.8.8/com/atlassian/confluence/api/model/content/ContentRepresentation.html> — export_view semantics: absolute URLs, macros rendered as anonymous user
- <https://community.developer.atlassian.com/t/confluence-server-rest-api-prevent-macro-expansion-in-content-fetch-using-body-export-view/62550> — export_view renders macros in the body value
- <https://github.com/cmu-sei/SCALe> — real Confluence Server 2018 HTML space export (page chrome, contentLayout2 layers, information-macros, inline-task-list, emoticons, anchor links, attachments pageSection/greybox, footer)
- <https://github.com/adessoSE/Seed-Test> — table-wrap/confluenceTable, confluence-embedded-file-wrapper with `attachments/<pageId>/<attId>` src
- <https://github.com/blastroyale/blastroyale> — code panel pdl / `pre.syntaxhighlighter-pre` with `data-syntaxhighlighter-params`
- <https://github.com/Keyfactor/signserver-ce> — preformatted/noformat panels, information-macros with iconfont classes, inline-comment-marker, `aui-lozenge-visual-refresh`
- <https://github.com/jenkins-infra/docker-confluence-data> — `span.jira-issue.resolved` with data-jira-key, `?src=confmacro` links, code panels
- <https://github.com/SWM-FIRE/modoco-documentation> — newer `span.confluence-jim-macro.jira-issue` form
- <https://github.com/GaloisInc/hacrypto> — titled code blocks, comment sections, `a.confluence-userlink.user-mention`, legacy panelMacro/noteMacro tables
- <https://github.com/bgoonz/atlassian-templates> — status-macro lozenges, plugin-tabmeta-details page-properties rendering
- <https://github.com/meridius/confluence-to-markdown> — 2016 Server export fixtures + converter selectors (#content/#main-content/#attachments/#comments/.pageSection.group)
- <https://github.com/8bitsquid/confluence-html-importer> — conf-macro output-block data-macro-name decoration
- <https://github.com/Infosys/Infosys-Responsible-AI-Toolkit> — Cloud export_view: view-file embedded-file attrs, expand-control with onclick, client-side-toc-macro
- Apache OpenOffice 4.1.1 release-notes Confluence export (via GitHub code search) — `div.toc-macro.rbtoc<epoch> > ul.toc-indentation` verbatim
- GitHub code search (`gh api search/code`, text-match fragments) across `*.html` Confluence exports — toc-indentation, expand-control-text, data-inline-task-id, icons/emoticons, confluence-anchor-link, jira-macro-single-issue-export-pdf, plugin_pagetree_children, profile-macro/vcard/userLogoLink
- <https://aui.atlassian.com/aui/7.9/docs/lozenges.html> — AUI lozenge colour-variant class reference
- <https://confluence.atlassian.com/doc/status-macro-223222355.html>, <https://confluence.atlassian.com/doc/expand-macro-223222352.html>, <https://confluence.atlassian.com/doc/code-block-macro-139390.html> — DC 10.2 macro behaviour/params (do not document HTML output)

### Tooling (pandoc / panflute)

- <https://pandoc.org/MANUAL.html> — --wrap/--columns/--markdown-headings/--strip-comments, pipe-table limitation ("cells of pipe tables cannot contain block elements"), extension semantics
- Empirical verification: pandoc 3.9.0.2 (`--list-extensions=html` / `=gfm`, native-AST probes of namespaced tags, CDATA, data-attributes, table fallbacks, `[TABLE]` placeholder, task lists, smart, wrap, br) and panflute 2.3.1 in this repo's `.venv`
- <https://github.com/jgm/pandoc/issues/1756> — pandoc drops unknown HTML elements when converting to markdown
- <https://github.com/jgm/pandoc/issues/2155> — Confluence storage-format reader feature request (never implemented; confirms the pre-transform requirement)
- <https://scorreia.com/software/panflute/> and <https://scorreia.com/software/panflute/guide.html> — run_filter/prepare/finalize, return-value semantics, doc.get_metadata, convert_text round-trips
- <https://github.com/farbodsz/pandoc-confluence> — community pandoc writer (markdown → storage only; reverse unsupported, corroborating the gap)
- <https://github.github.com/gfm/> — GFM tables: `|` must be escaped as `\|` in cells, including inside code spans (pandoc does not do this inside Code inlines — verified)
- <https://github.com/jgm/pandoc/issues/5333> — HTML reader behavior for tags inside `<pre><code>`

*(The catalog's `confluence-storage-format-790796544.html` also appears in the tooling sources — merged here.)*
