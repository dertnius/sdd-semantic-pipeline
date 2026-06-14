# Confluence Storage Format GitLab Markdown

> **SUPERSEDED (2026-06-12):** this page is superseded **wholesale** by
> [docs/confluence-conversion-rules.md](../confluence-conversion-rules.md) — the definitive
> Confluence Server/DC 8.0–10.x → GitLab-Markdown rule set for the embedding pipeline. Two statements
> below are directly contradicted by the new document: the `#content-view` content-root **Decision**
> (a legacy code-derived selector; the catalog documents `div#content.view` — see HX-ROOT) and the
> `[[ _TOC_ ]]`-injection **Key Fact** (injection is default OFF for the embedding corpus — see
> MD-TOC-INJECT). Do not follow this page for new work; it is kept for history only.

**Last Updated:** 2026-06-06
**Sources:** `docs/inbox/CONFLUENCE_FORMAT_INSTRUCTIONS.md`
**Related:** [convert-html-gitlab-markdown-linux](convert-html-gitlab-markdown-linux.md), [convert-html-gitlab-markdown-windows](convert-html-gitlab-markdown-windows.md)

---

## Summary
This page documents the authoritative handling rules for Confluence Storage Format exports when converting them to GitLab-flavoured Markdown. It covers document structure, text normalization, links, images, code blocks, tables, and macro handling for Confluence Data Center 8.5.x.

## Key Facts
- Confluence DC 8.5.x exports XHTML-based XML, not pure HTML, so the converter must target the content root under `#content-view` first (source: `docs/inbox/CONFLUENCE_FORMAT_INSTRUCTIONS.md`)
- Headings, standard text effects, lists, tables, and external links are handled natively by pandoc after light preprocessing (source: `docs/inbox/CONFLUENCE_FORMAT_INSTRUCTIONS.md`)
- Task lists, internal Confluence links, attachment links, images, and macros require preprocessing into GitLab-compatible HTML or Markdown forms (source: `docs/inbox/CONFLUENCE_FORMAT_INSTRUCTIONS.md`)
- Code macros must be rewritten into fenced code blocks with a detected language class derived from the Confluence brush value (source: `docs/inbox/CONFLUENCE_FORMAT_INSTRUCTIONS.md`)
- Tables with rowspan or colspan cannot be represented cleanly in GFM pipe tables and must be flagged for manual review (source: `docs/inbox/CONFLUENCE_FORMAT_INSTRUCTIONS.md`)
- The converter strips cosmetic Confluence classes and styles while preserving content so pandoc can produce the final Markdown output (source: `docs/inbox/CONFLUENCE_FORMAT_INSTRUCTIONS.md`)
- Table of contents macros are removed during preprocessing because the script injects `[[ _TOC_ ]]` at the top during post-processing (source: `docs/inbox/CONFLUENCE_FORMAT_INSTRUCTIONS.md`)

## Decisions and Constraints
> **Decision [2026-06-06]:** Use `#content-view` as the default content root for Confluence DC 8.5.x exports. Source: `docs/inbox/CONFLUENCE_FORMAT_INSTRUCTIONS.md`
> **Decision [2026-06-06]:** Normalize task lists, Confluence links, images, code blocks, and panel macros before pandoc conversion so GitLab Markdown output stays valid. Source: `docs/inbox/CONFLUENCE_FORMAT_INSTRUCTIONS.md`
> **Decision [2026-06-06]:** Preserve attachment references in output paths and flag co-location requirements in the conversion report. Source: `docs/inbox/CONFLUENCE_FORMAT_INSTRUCTIONS.md`

## Open Questions
- No open questions.

## Contradictions
No contradictions.

## Detail
Confluence Storage Format exports from Confluence Data Center 8.5.x use XHTML-based XML with a nested wrapper hierarchy. The conversion entry point should be the content region under `#content-view`, with the page header and metadata removed before processing. Standard heading tags, paragraphs, common inline formatting, external links, ordinary lists, and standard tables are handled by pandoc once cosmetic classes and style attributes are stripped.

Task lists are Confluence-specific and must be converted into standard unordered lists with `[ ]` or `[x]` prefixes. Internal page links, anchor links, attachment links, and rich link bodies need explicit normalization because the exported HTML does not preserve them in a GitLab-ready form. Attachment-backed images and links must point to `./attachments/...` and are only valid if the files are copied alongside the converted document.

Code macros export as syntax-highlighted HTML wrappers and must be rewritten into fenced code blocks with a proper language class. Brush values such as `js`, `py`, `ps1`, and `terraform` map to GitLab-recognized identifiers, while unsupported or plain text brushes produce unlabeled code fences. Tables with merged cells, nested tables, or styled headers lose fidelity in GitLab Markdown and are flagged for manual review. Macro handling also covers info, note, warning, tip, panel, expand, and table-of-contents content, with the TOC macro removed because the post-processor injects a native `[[ _TOC_ ]]` directive instead.
