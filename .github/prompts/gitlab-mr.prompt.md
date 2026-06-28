---
mode: agent
description: Generate a concise, well-structured GitLab Merge Request description by diffing the current branch against origin/main.
---

# /gitlab-mr — draft a GitLab Merge Request description

Port of the `gitlab-mr-generator` skill. Produce a clean MR description for the
current branch by diffing against `origin/main`. This repo ships to **GitLab**
(`.gitlab-ci.yml`, GitLab Pages), so the output targets GitLab conventions.

## Steps

1. **Gather the change.** Run:

   ```bash
   git fetch origin
   git log --oneline origin/main..HEAD
   git diff --stat origin/main...HEAD
   git diff origin/main...HEAD
   ```

   Read the diff in full — group the changes by intent, not by file.

2. **Write the description** in this structure:

   ```markdown
   ## What & why
   1–3 sentences: the problem and the approach.

   ## Changes
   - Bullet per meaningful change, grouped by area (core / CLI / docs / CI).

   ## How tested
   - The commands run and their result (e.g. `pytest -m "not slow"`, `ruff check`,
     `check_docs.py`, the relevant `sdd-pipeline` path).

   ## Risk / rollout
   - Anything reviewers must watch: guardrail boundaries touched, a new config field
     or CLI flag, an `EMBED_FORMAT_VERSION` bump (consumers must re-index), a CI
     change.

   ## Checklist
   - [ ] Fast tests pass (`pytest -m "not slow"`)
   - [ ] `ruff format --check` + `ruff check` clean
   - [ ] Docs reconciled (`check_docs.py` green) if CLI/config changed
   - [ ] Copilot assets valid (`check_copilot.py` green) if `.github/` changed
   ```

3. **Tailor it.** Drop sections that don't apply; never invent testing that wasn't
   run. Link related issues with GitLab syntax (`Closes #123`).

## Notes

- Keep it tight and skimmable — reviewers read the summary, then the diff.
- Match the verify gates the GitLab pipeline actually runs (`verify:quality`).
