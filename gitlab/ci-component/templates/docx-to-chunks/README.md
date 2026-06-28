# docx-to-chunks

Drop-in GitLab CI/CD pipeline that turns a repo full of Word documents into **semantic
chunks + a model-free lexical index**, with a Windows+Office pre-stage that converts legacy
binary `.doc` to `.docx` (the pipeline reads OOXML `.docx` only). See **[Using
`docx-to-chunks` in your project](../../README.md#using-docx-to-chunks-in-your-project)** in
the parent README for the full consumer guide (prerequisites, the Windows runner, the local
`.doc` fallback, pinning, troubleshooting) and publishing steps.

## Quick reference

```yaml
include:
  - component: $CI_SERVER_FQDN/<group>/ci-components/docx-to-chunks@1.0.0
    inputs:
      lang: "de"          # default
```

Commit your `.doc`/`.docx` under `inbox/` and push. Outputs land as the `publish` job's
artifact `chunks-<sha>`: `outbox/chunks/` (portable `.chunks.json`), `outbox/index/` (BM25
lexical index), `outbox/reports/`.

| Stage | Job | Does |
|---|---|---|
| `prepare` | `prepare:doc-to-docx` | Windows+Word: `.doc` → `.docx` in place (skipped if `convert_legacy_doc: false`; no-op if no `.doc`). |
| `convert` | `convert` | `sdd-pipeline convert-docx` (docx → md) + `lint --strict`. |
| `chunks` | `chunks` | `sdd-pipeline export` (chunks) + `index --lexical` (model-free). |
| `publish` | `publish` | bundles chunks + index + reports as a 30-day artifact. |

### Inputs

| Input | Default | Purpose |
|---|---|---|
| `pipeline_install` | `sdd-pipeline[lang]` | pip spec for the pipeline (Nexus PyPI proxy), or a `git+https://…@<tag>` spec. |
| `lang` | `de` | enrichment language (`de`/`en`/`fr`/`it`/`auto`). |
| `merge_mode` | `prose` | `prose` → `--merge-prose`, `definitions` → `--merge-definitions`, `none` → neither. |
| `convert_legacy_doc` | `true` | run the Windows `.doc`→`.docx` job. Set `false` for all-`.docx` repos with no Windows runner. |
| `windows_runner_tags` | `["windows","office"]` | runner tags selecting the Windows shell runner with Microsoft Word. |
| `python_version` | `3.11` | `python:<ver>-slim` Nexus image tag (Linux jobs). |
| `pandoc_version` | `3.5` | keys the pandoc binary cache; pair with `NEXUS_PANDOC_URL`. |

Requires the group-level `NEXUS_DOCKER_REGISTRY` / `NEXUS_PYPI_INDEX_URL` / `NEXUS_PANDOC_URL`
CI/CD variables (same as `python-nexus`), the pipeline package installable from Nexus, and —
only when converting `.doc` — a Windows runner with Microsoft Word tagged to match
`windows_runner_tags` (**shell executor, logged-in interactive session** — Word COM hangs
otherwise). No Windows runner? Set `convert_legacy_doc: false` and run
[`scripts/convert-doc-to-docx.ps1`](../../scripts/convert-doc-to-docx.ps1) locally first.
