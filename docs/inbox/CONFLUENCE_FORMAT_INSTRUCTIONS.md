# INSTRUCTIONS — Confluence Storage Format → GitLab Markdown
# Source: https://confluence.atlassian.com/doc/confluence-storage-format-790796544.html
# Target script: html_to_gitlab_md.py
# Confluence version: Data Center 8.5.x (LTS)
#
# This file is the authoritative reference for how every Confluence storage
# format element should be handled during HTML pre-processing.
# Read this before modifying any parsing or normalisation logic in the script.

---

## 1. DOCUMENT STRUCTURE

Confluence DC 8.5.x exports XHTML-based XML. It is NOT pure HTML.
The root content wrapper hierarchy is:

  <main>
    <header>                      ← REMOVE: page title, breadcrumbs, metadata
    <div id="content-view">       ← ENTRY POINT: pass as --selector "#content-view"
      <div class="wiki-content">  ← ACTUAL BODY: headings, paragraphs, tables, macros

Use `#content-view` as the default selector for DC 8.5.x exports.
The script's `_find_content_root()` should try this before any other selector.


---

## 2. HEADINGS

Storage format:  <h1> through <h6>
Exported HTML:   Standard HTML heading tags — pandoc handles these natively.
Action:          No special handling needed.
GitLab output:   # through ######


---

## 3. TEXT EFFECTS

Each effect maps directly to a standard HTML tag in the export.
Pandoc handles all of these natively — no pre-processing needed.

  <strong>text</strong>                           → **text**
  <em>text</em>                                   → *text*
  <u>text</u>                                     → <u>text</u>  (GitLab renders inline HTML)
  <span style="text-decoration:line-through;">    → ~~text~~
  <sup>text</sup>                                 → <sup>text</sup>
  <sub>text</sub>                                 → <sub>text</sub>
  <code>text</code>                               → `text`
  <pre>text</pre>                                 → fenced code block (see Section 8)
  <blockquote><p>text</p></blockquote>            → > text
  <span style="color: rgb(255,0,0);">text</span>  → text (colour lost — strip the span)
  <small>text</small>                             → strip tag, keep text
  <big>text</big>                                 → strip tag, keep text
  <p style="text-align: center;">text</p>         → text (alignment lost — strip style)
  <p style="text-align: right;">text</p>          → text (alignment lost — strip style)

Pre-processing rule:
  Strip all style= attributes EXCEPT those on <code> elements with language classes.


---

## 4. TEXT BREAKS

  <p>...</p>                → paragraph (pandoc handles)
  <br />                    → two trailing spaces + newline in GFM (pandoc handles)
  <hr />                    → --- (pandoc handles)
  &mdash;                   → — (pandoc handles)
  &ndash;                   → – (pandoc handles)
  &nbsp;                    → single space (strip or replace)

Pre-processing rule:
  Replace &nbsp; with a regular space to avoid non-breaking space artefacts
  in the markdown output.


---

## 5. LISTS

Standard HTML lists — pandoc handles natively:
  <ul><li>...</li></ul>     → - item
  <ol><li>...</li></ol>     → 1. item

Task lists use Confluence-specific XML — pandoc does NOT handle these:

  <ac:task-list>
    <ac:task>
      <ac:task-status>incomplete</ac:task-status>
      <ac:task-body>task text</ac:task-body>
    </ac:task>
    <ac:task>
      <ac:task-status>complete</ac:task-status>
      <ac:task-body>done task</ac:task-body>
    </ac:task>
  </ac:task-list>

Pre-processing rule (_normalise_task_lists):
  For each <ac:task-list>:
    Build a <ul> element.
    For each <ac:task>:
      Read <ac:task-status>: "complete" → [x], "incomplete" → [ ]
      Read <ac:task-body>: the task text (may contain inline markup)
      Build: <li>[ ] task text</li>  or  <li>[x] task text</li>
    Replace <ac:task-list> with the <ul>.

GitLab output:
  - [ ] incomplete task
  - [x] complete task


---

## 6. LINKS

6a. Standard external link — pandoc handles:
  <a href="http://example.com">text</a>   → [text](http://example.com)

6b. Confluence internal page link — NOT standard HTML:
  <ac:link>
    <ri:page ri:content-title="Page Title" ri:space-key="FOO" />
    <ac:plain-text-link-body><![CDATA[Link text]]></ac:plain-text-link-body>
  </ac:link>

Pre-processing rule (_normalise_ac_links):
  Extract ri:content-title from <ri:page>.
  Extract text from <ac:plain-text-link-body> CDATA or <ac:link-body>.
  If no link body: use ri:content-title as the text.
  Output: <a href="#">text</a>
  NOTE: The href cannot be resolved without a page URL map.
        Output a dead link with a comment: <!-- confluence-page: Page Title -->
        This allows post-processing to remap if a URL map is provided.

6c. Confluence anchor link (same page):
  <ac:link ac:anchor="anchor-name">
    <ac:plain-text-link-body><![CDATA[Link text]]></ac:plain-text-link-body>
  </ac:link>

Pre-processing rule:
  Output: [Link text](#anchor-name)
  GitLab auto-generates anchor IDs from heading text — verify they match.

6d. Attachment link:
  <ac:link>
    <ri:attachment ri:filename="file.pdf" />
    <ac:plain-text-link-body><![CDATA[Download PDF]]></ac:plain-text-link-body>
  </ac:link>

Pre-processing rule:
  Output: [Download PDF](./attachments/file.pdf)
  NOTE: Attachment files must be co-located in ./attachments/ for this to work.
        Flag these in the conversion report so the user knows to copy the files.

6e. Rich link body (contains inline markup):
  <ac:link>
    <ri:page ri:content-title="Page Title" />
    <ac:link-body>Some <strong>Rich</strong> Text</ac:link-body>
  </ac:link>

Pre-processing rule:
  Process the inner markup of <ac:link-body> normally.
  Wrap in <a href="#">...</a> as with 6b.

Permitted tags inside <ac:link-body>:
  <b>, <strong>, <em>, <i>, <code>, <tt>, <sub>, <sup>, <br>, <span>
  All others: strip tag, keep text.


---

## 7. IMAGES

7a. Attached image:
  <ac:image>
    <ri:attachment ri:filename="diagram.png" />
  </ac:image>

Pre-processing rule:
  Output: <img src="./attachments/diagram.png" alt="diagram.png" />
  Flag in conversion report: attachment must be co-located.

7b. External image:
  <ac:image>
    <ri:url ri:value="https://example.com/image.png" />
  </ac:image>

Pre-processing rule:
  Output: <img src="https://example.com/image.png" alt="" />
  Pandoc will convert to: ![](https://example.com/image.png)

7c. Image with attributes:
  <ac:image ac:width="400" ac:alt="My diagram" ac:title="Figure 1">
    <ri:attachment ri:filename="arch.png" />
  </ac:image>

Supported attributes to preserve:
  ac:alt    → alt attribute on <img>
  ac:title  → title attribute on <img>
  ac:width  → width attribute on <img>
  ac:height → height attribute on <img>
  ac:align  → align attribute on <img> (strip — not supported in GFM)
  ac:border → strip (not supported in GFM)
  ac:thumbnail → strip

Pre-processing rule (_normalise_ac_images):
  For each <ac:image>:
    Build attrs dict from supported ac:* attributes.
    Determine src from child <ri:attachment> or <ri:url>.
    Output: <img src="..." alt="..." width="..." />


---

## 8. CODE BLOCKS

DC 8.5.x code macro HTML export:

  <div class="code panel pdl">
    <div class="codeContent panelContent pdl">
      <pre class="syntaxhighlighter-pre"
           data-syntaxhighlighter-params="brush: sql; gutter: false; theme: Confluence"
           data-theme="Confluence">
        SELECT * FROM orders;
      </pre>
    </div>
  </div>

Language is in data-syntaxhighlighter-params as "brush: <lang>".

Brush → language identifier mapping:

  java        → java         javascript  → javascript
  sql         → sql          js          → javascript
  python      → python       ts          → typescript
  py          → python       typescript  → typescript
  bash        → bash         xml         → xml
  shell       → bash         html        → html
  sh          → bash         css         → css
  groovy      → groovy       yaml        → yaml
  scala       → scala        yml         → yaml
  kotlin      → kotlin       json        → json
  ruby        → ruby         hcl         → hcl
  rb          → ruby         terraform   → hcl
  cpp         → cpp          dockerfile  → dockerfile
  c           → c            docker      → dockerfile
  csharp      → csharp       powershell  → powershell
  cs          → csharp       ps1         → powershell
  go          → go           none        → (no language)
  golang      → go           text        → (no language)
  plain       → (no language)

Pre-processing rule (_normalise_code_blocks):
  1. Find div.code.panel or div.code-block or pre.syntaxhighlighter-pre
  2. Extract brush value from data-syntaxhighlighter-params using regex:
       re.search(r"brush:\s*(\w+)", params)
  3. Map brush to language identifier using table above
  4. Get raw text from <pre> (strip all child <span> elements — they are
     only syntax highlighting colour spans)
  5. Build: <pre><code class="language-{lang}">raw text</code></pre>
  6. Replace the entire div.code.panel wrapper with the new <pre>

IMPORTANT: The class attribute on <code> must be stored as a LIST in
BeautifulSoup, not a string:
  new_code["class"] = [f"language-{lang}"]   ← correct
  new_code["class"] = f"language-{lang}"     ← WRONG — BS4 stores as string,
                                                iteration breaks the guard check


---

## 9. TABLES

DC 8.5.x table HTML export:

  <table class="confluenceTable">
    <tbody>
      <tr>
        <th class="confluenceTh">Header 1</th>
        <th class="confluenceTh">Header 2</th>
      </tr>
      <tr>
        <td class="confluenceTd">Cell 1</td>
        <td class="confluenceTd">Cell 2</td>
      </tr>
    </tbody>
  </table>

The .confluenceTable / .confluenceTh / .confluenceTd classes are cosmetic.
Pandoc handles standard <table><tr><th><td> natively.
Action: Strip the class attributes — pandoc does the rest.

KNOWN LIMITATIONS:
  colspan / rowspan (merged cells):
    Pandoc cannot represent merged cells in GFM pipe tables.
    Pre-processing rule: detect any <td rowspan> or <td colspan> and log a
    WARNING in the conversion report. The cell content will be included but
    the merge will be lost. Flag for manual review.

  Nested tables:
    Not supported in GFM. Log a WARNING and attempt to flatten one level.

  Coloured headers (inline style="background-color:"):
    Strip the style. Content survives, colour is lost.


---

## 10. MACROS (ac:structured-macro)

All Confluence macros use this wrapper in the storage format:

  <ac:structured-macro ac:name="MACRO_NAME" ac:schema-version="1">
    <ac:parameter ac:name="PARAM">value</ac:parameter>
    <ac:rich-text-body>...</ac:rich-text-body>
    <ac:plain-text-body><![CDATA[...]]></ac:plain-text-body>
  </ac:structured-macro>

In the rendered/exported HTML, macros appear as styled divs.
The ac:name attribute does NOT survive in rendered HTML export —
only the CSS classes on the rendered divs are available.

10a. INFO / NOTE / WARNING / TIP PANELS

  Exported HTML class names (DC 8.5.x):

    Info:    div.confluence-information-macro.confluence-information-macro-information
    Note:    div.confluence-information-macro.confluence-information-macro-note
    Warning: div.confluence-information-macro.confluence-information-macro-warning
    Tip:     div.confluence-information-macro.confluence-information-macro-tip

  Each contains:
    span.aui-icon          ← icon image — REMOVE
    div.confluence-information-macro-body  ← keep this content

  Pre-processing rule (_normalise_macros):
    Remove span.aui-icon child.
    Extract text from div.confluence-information-macro-body.
    Wrap in blockquote with label prefix:
      info    → > ℹ️ **INFO**: {body text}
      note    → > 📝 **NOTE**: {body text}
      warning → > ⚠️ **WARNING**: {body text}
      tip     → > ✅ **TIP**: {body text}

10b. PANEL MACRO

  Exported HTML:
    <div class="panel" style="...">
      <div class="panelHeader">Panel Title</div>
      <div class="panelContent">body text</div>
    </div>

  Pre-processing rule:
    Extract title from div.panelHeader.
    Extract body from div.panelContent.
    Output: > 📋 **{title}**: {body}

10c. EXPAND MACRO (collapsible section)

  Exported HTML:
    <div class="expand-container">
      <div class="expand-control">
        <span class="expand-control-text">Toggle label</span>
      </div>
      <div class="expand-content">
        ... any content ...
      </div>
    </div>

  Pre-processing rule (_normalise_expand_macros):
    Extract label from span.expand-control-text (or div.expand-control text).
    Extract body from div.expand-content.
    Output as HTML <details> block — GitLab renders natively:
      <details>
      <summary>{label}</summary>
      {body content}
      </details>

10d. CODE MACRO — see Section 8.

10e. TABLE OF CONTENTS MACRO

  Exported HTML:
    <div class="toc-macro rbtoc...">
      <ul>...</ul>
    </div>

  Pre-processing rule:
    Decompose entirely. Replace with nothing.
    The script's postprocess() injects [[_TOC_]] at the top of the document
    which GitLab renders as a native auto-generated TOC.

10f. JIRA ISSUES MACRO

  Exported HTML: usually a <table> with Jira issue data, or a single link.
  Pre-processing rule: treat as a normal table or link — no special handling.

10g. STATUS MACRO (lozenge badges)

  Exported HTML:
    <span class="status-macro aui-lozenge aui-lozenge-success">APPROVED</span>
    <span class="status-macro aui-lozenge aui-lozenge-error">FAILED</span>
    <span class="status-macro aui-lozenge aui-lozenge-warning">IN PROGRESS</span>
    <span class="status-macro aui-lozenge aui-lozenge-current">CURRENT</span>
    <span class="status-macro aui-lozenge aui-lozenge-complete">DONE</span>
    <span class="status-macro aui-lozenge">DEFAULT</span>  ← grey, no extra class

  Lozenge class → prefix mapping:
    aui-lozenge-success  → ✅
    aui-lozenge-error    → ❌
    aui-lozenge-warning  → ⚠️
    aui-lozenge-current  → 🔵
    aui-lozenge-complete → ✓
    (none / grey)        → (no prefix)

  Pre-processing rule (_normalise_badges):
    For each span.status-macro:
      Determine prefix from lozenge class.
      text = span.get_text(strip=True)
      Replace with: <code>{prefix} {text}</code>

  GitLab output: `✅ APPROVED`  `❌ FAILED`  `⚠️ IN PROGRESS`

10h. RECENTLY UPDATED / CHILDREN / PAGE INFO MACROS

  These macros render dynamic content that is meaningless in a static export.
  Exported HTML classes: .pageInfoSection, .recently-updated, .children-macro

  Pre-processing rule: decompose entirely — no output.

10i. ANCHOR MACRO

  Storage format: <ac:structured-macro ac:name="anchor"><ac:parameter ac:name="">name</ac:parameter></ac:structured-macro>
  Exported HTML:  <span id="anchor-name"></span>  or  <ac:structured-macro ...>

  Pre-processing rule:
    Convert to: <a id="anchor-name"></a>
    GitLab Markdown supports inline HTML anchors.


---

## 11. EMOJIS / EMOTICONS

  Storage format: <ac:emoticon ac:name="smile" />
  Exported HTML:  <img class="emoticon" src="..." alt="(smile)" title="smile">
                  OR <ac:emoticon ac:name="smile" />

  Emoticon name → Unicode emoji mapping:

    smile        → 😊    sad          → 😞
    cheeky       → 😛    laugh        → 😄
    wink         → 😉    thumbs-up    → 👍
    thumbs-down  → 👎    information  → ℹ️
    tick         → ✅    cross        → ❌
    warning      → ⚠️    star         → ⭐
    heart        → ❤️    broken-heart → 💔
    light-on     → 💡    light-off    → 💡
    yellow-star  → ⭐    red-star     → 🌟
    green-star   → 💚    blue-star    → 💙

  Pre-processing rule (_normalise_emoticons):
    For <img class="emoticon">:
      Read alt attribute (format: "(smile)") — strip parens → key
      Look up key in emoji map
      Replace <img> with the unicode character
    For <ac:emoticon ac:name="...">:
      Read ac:name attribute → key
      Look up in emoji map
      Replace element with the unicode character
    Fallback (unknown emoticon): replace with alt text or name in parens.


---

## 12. PAGE LAYOUTS

  Storage format:
    <ac:layout>
      <ac:layout-section ac:type="two_equal">
        <ac:layout-cell>{content}</ac:layout-cell>
        <ac:layout-cell>{content}</ac:layout-cell>
      </ac:layout-section>
    </ac:layout>

  Exported HTML: usually rendered as a table or nested divs.
  GFM does not support multi-column layouts.

  Pre-processing rule (_normalise_layouts):
    Detect <ac:layout> or div.innerCell or div.columnLayout.
    Flatten all layout cells into a single linear sequence.
    Add a horizontal rule <hr> between cells so sections are visually separated.
    Log a WARNING in the conversion report: "Layout columns flattened — review manually."


---

## 13. TEMPLATE VARIABLES AND INSTRUCTIONAL TEXT

  Template variables: <at:var at:name="MyText" />
  Instructional text: <ac:placeholder>click to type...</ac:placeholder>

  These only appear in page templates, not in exported pages.
  If they appear in an export (rare):

  Pre-processing rule:
    <at:var at:name="X" />         → replace with: {X}
    <ac:placeholder>text</ac:placeholder> → replace with: *[text]*


---

## 14. RESOURCE IDENTIFIERS (ri: namespace)

These appear inside <ac:link> and <ac:image> elements.
They do NOT survive as-is in rendered HTML export — they are resolved
to standard HTML by the renderer. However they may appear in raw XML exports.

  <ri:page ri:content-title="Title" ri:space-key="KEY" />
    → resolve to href="#" with comment <!-- confluence-page: Title (KEY) -->

  <ri:attachment ri:filename="file.pdf" />
    → resolve to href="./attachments/file.pdf"

  <ri:url ri:value="https://example.com" />
    → resolve to href="https://example.com"

  <ri:user ri:userkey="abc123" />
    → resolve to: @abc123 (or strip if user directory not available)

  <ri:space ri:space-key="TST" />
    → resolve to text: [TST space](#) with comment <!-- confluence-space: TST -->


---

## 15. INLINE COMMENTS

  Exported HTML:
    <span class="inline-comment-marker" data-ref="comment-id">marked text</span>

  Pre-processing rule:
    Unwrap the span — keep only the inner text.
    The comment itself is not accessible in the HTML export.


---

## 16. CONVERSION REPORT

After processing, the script should output a conversion report listing:

  WARNINGS (require manual review):
    - Tables with merged cells (colspan/rowspan) — list table locations
    - Multi-column layouts that were flattened
    - Confluence internal links (cannot auto-resolve href)
    - Attachment links (files must be manually co-located)
    - Images referencing Confluence attachments

  INFO (informational):
    - Count of each macro type processed
    - Code blocks found and languages detected
    - Emoticons replaced
    - Task lists converted
    - Expand macros converted to <details>

  ERRORS (conversion failed for element):
    - Any element that raised an exception during processing


---

## 17. ELEMENT PRIORITY ORDER IN _normalise_code_blocks()

Process code blocks in this order to avoid double-processing:

  1. div.code.panel (DC 8.5.x full code macro wrapper)
  2. div.code-block (Cloud-style wrapper)
  3. pre.syntaxhighlighter-pre (DC rendered pre)
  4. pre > code (any remaining bare code blocks)

Stop after first match per element.


---

## 18. SELECTOR PRIORITY ORDER IN _find_content_root()

Try selectors in this order — first match wins:

  1. User-supplied --selector argument (highest priority)
  2. div#content-view          (DC 8.5.x primary)
  3. div.wiki-content          (DC 8.5.x / Server fallback)
  4. div#main-content          (DC older versions)
  5. div#page-content          (DC alternative)
  6. div.content-body          (some DC themes)
  7. div.content-area          (Cloud primary)
  8. div.view                  (Cloud alternative)
  9. main                      (semantic HTML fallback)
  10. article                  (semantic HTML fallback)
  11. [role="main"]            (ARIA fallback)
  12. body                     (last resort)


---

## 19. KNOWN DC 8.5.x QUIRKS

  - CDATA sections in <ac:plain-text-link-body> must be read with
    .string or .get_text() — BeautifulSoup handles CDATA as NavigableString.

  - The ac: and ri: namespace prefixes may or may not have xmlns declarations
    depending on whether the input is a raw storage format export or a
    rendered HTML export. The script targets rendered HTML, so ac:/ri: tags
    should appear only in edge cases (raw export or template pages).

  - DC 8.5.x sometimes wraps the entire page content in a <div id="main">
    inside <div id="content">. If #content-view is not found, try #main.

  - Confluence emoticons exported as <img class="emoticon"> will have
    absolute URLs to the Confluence instance — these will be broken in GitLab.
    Always replace with unicode characters, never keep the <img>.

  - Some DC exports include <div class="pageSection"> wrappers around
    content sections. These are purely structural — unwrap them, keep content.

  - The "Excerpt" macro body is inlined at export time and needs no special
    handling — it appears as normal paragraphs.

  - ac:structured-macro elements that survived rendering (template pages,
    raw exports) must be decomposed or converted. Never pass them to pandoc
    as-is — pandoc will output raw XML noise.
