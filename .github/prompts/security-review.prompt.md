---
mode: agent
description: Security review of the pending changes on the current branch — focus on secret handling, subprocess/SSRF, untrusted-input parsing, and the workspace guard.
---

# /security-review — review the pending changes for security

Security-review the diff on the current branch. Port of the Claude
`/security-review` skill, tuned to this pipeline's real risk surface.

## Steps

1. **Get the diff** (`git diff origin/main...HEAD`) and read the changed files.
2. **Review against this repo's risk surface:**
   - **Secrets are env-only.** `PIPELINE_DOWNLOAD_*` (SiteMinder), Azure
     `PIPELINE_AZURE_OPENAI_API_KEY`, etc. must come from env/`.env`, **never** CLI
     flags, logs, or committed files. The deterministic core must never read them.
     Flag any secret that leaks into argv, stdout, a report, or a test fixture.
   - **Subprocess / injection.** pandoc is the only subprocess in flow A
     (`ast_parser.py`) and the converter (`_run_pandoc`); `shell.py` may launch
     `pwsh`. All must use arg-lists (no `shell=True`), pinned UTF-8 decoding, and
     never interpolate untrusted page content into a command line.
   - **Untrusted input.** Converter/parser input is attacker-influenced HTML/docx.
     Watch for XML/HTML entity expansion, path traversal from archive/media
     extraction, and unbounded resource use. The storage-format **front door**
     (`_reject_if_storage_format`) and the convert **confidence/quarantine gate**
     are security controls — don't weaken them.
   - **SSRF / ingestion.** `download.py` fetches manifest URLs behind SSO — validate
     the manifest is trusted and URLs aren't user-controlled into internal hosts.
   - **Workspace guard.** `workspace.py` confines I/O to `inbox/`/`outbox/`. A change
     that lets a path escape the zones (or disables the guard by default) is a
     finding.
   - **Vector-store metadata** must stay scalar; don't smuggle executable/oversized
     payloads through it.
3. **Report** each finding with `file:line`, the threat, severity, and a fix. If the
   diff is clean, say so plainly — don't invent issues.

## Notes

- This is authorized defensive review of this repo's own changes.
- Prefer concrete, exploitable findings over generic advice.
