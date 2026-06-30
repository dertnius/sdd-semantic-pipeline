# validate-skills

Drop-in GitLab CI/CD gate that validates **Agent Skills** (`SKILL.md`) against the
[Agent Skills open standard](https://agentskills.io/specification) — the same idea as
[`gitlab-ci-skill`](https://gitlab.com/gitlab-org/ci-cd/gitlab-ci-skill)'s own pipeline,
but **self-contained and offline**: it validates with an inline, stdlib-only Python checker
(no pip, no pandoc, no Nexus proxy, no GitHub fetch — only a Python interpreter), so it
runs behind a corporate proxy / air-gap. See **[Using `validate-skills` in your
project](../../README.md#using-validate-skills-in-your-project)** in the parent README for
the full consumer guide and publishing steps.

## Quick reference

```yaml
include:
  - component: $CI_SERVER_FQDN/<group>/ci-components/validate-skills@1.0.0
    inputs:
      skills_dir: ".claude/skills"   # default
```

Keep your skills as `<skills_dir>/<name>/SKILL.md`. On every merge request and default-branch
push, the `validate:skills` job checks each `SKILL.md` and **fails the pipeline** on any
problem, writing a `skill-validation-report.txt` artifact (kept 30 days).

| Stage | Job | Does |
|---|---|---|
| `validate` | `validate:skills` | Inline stdlib-Python check of every `SKILL.md` frontmatter; exits non-zero on any error. |

### What it checks (mirrors `check_copilot.py::check_skills`, C6)

For each `<skills_dir>/*/SKILL.md` (or a single `<skills_dir>/SKILL.md` for a root-skill repo):

- a leading `---` YAML frontmatter block is present and terminated;
- `name` is present, **equals its directory**, matches the lowercase
  letters/digits/hyphens grammar (no leading/trailing/double hyphen) and is `<= 64` chars;
- `description` is present and `<= 1024` chars.

(The root-skill fallback relaxes only the `name == directory` rule, since the checkout dir
name is arbitrary.) The checks are an **invariant set**, deliberately the same rules the
`sdd-semantic-pipeline` repo enforces on its own skills — keep the inline validator in
`template.yml` in sync with that function, the single source of truth.

### Inputs

| Input | Default | Purpose |
|---|---|---|
| `skills_dir` | `.claude/skills` | dir holding `<name>/SKILL.md` skill folders (e.g. `.claude/skills`, `.github/skills`, `.agents/skills`). |
| `image` | `${NEXUS_DOCKER_REGISTRY}/python:3.11-slim` | container image with a Python 3 interpreter. Non-Nexus consumers: set e.g. `python:3.11-slim`. |
| `fail_on_empty` | `true` | fail if no `SKILL.md` is found under `skills_dir` (catches a misconfigured path). |

Requires only a runnable Python 3 image. The default `image` points at the org Nexus
registry (so it matches `python-nexus`/`docx-to-chunks`); a consumer **outside** that org
overrides `image` with any public Python image and needs **no** `NEXUS_*` variables.
