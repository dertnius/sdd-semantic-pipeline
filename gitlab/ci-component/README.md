# ci-components

Shared **GitLab CI/CD Components** for the enterprise org, importable by **any project
on the GitLab instance** via `include: component:`. Currently one component:

## `python-nexus`

Bootstraps a CI job on a **stock `python:3.x-slim` pulled from the enterprise Nexus
Docker registry**, with pip pinned to the **Nexus PyPI proxy** and an optional
**runtime pandoc install** from a Nexus raw repo — so a project needs **no custom
container image**. It provides:

- `default: image:` → `${NEXUS_DOCKER_REGISTRY}/python:<python_version>-slim`
- `default: cache:` → the pip wheel cache + a version-keyed pandoc-binary cache
- `variables:` → `PIP_INDEX_URL` (Nexus proxy), `PIP_CACHE_DIR`,
  `PIP_DISABLE_PIP_VERSION_CHECK`, `PANDOC_VERSION`
- two hidden `before_script` fragments you compose with `!reference`:
  - `.nexus-pip-bootstrap` — upgrade pip (resolves from the Nexus proxy)
  - `.nexus-install-pandoc` — fetch + cache pandoc ≥ 3 on PATH (stdlib `urllib`, no curl/apt)

### Inputs

| Input | Default | Purpose |
|---|---|---|
| `python_version` | `3.11` | the `python:<ver>-slim` Nexus image tag |
| `pandoc_version` | `3.5` | keys the pandoc binary cache; pair with `NEXUS_PANDOC_URL` |

---

## Using `python-nexus` in *your* project

### Prerequisites (one-time, per org/group — ask your platform team)

The component reads three **group-level CI/CD variables**, inherited by every project in
the group. They must be set once (Group → Settings → CI/CD → Variables); you do **not**
re-declare them per project:

| Variable | Example |
|---|---|
| `NEXUS_DOCKER_REGISTRY` | `nexus.corp.example.com:8891` |
| `NEXUS_PYPI_INDEX_URL` | `https://nexus.corp.example.com/repository/pypi-group/simple/` |
| `NEXUS_PANDOC_URL` | `https://nexus.corp.example.com/repository/raw-hosted/pandoc/pandoc-3.5-1-amd64.deb` |

If your project lives in a different group, either set them on your group too or ask for
them to be defined at the instance level. `NEXUS_PANDOC_URL` is only needed by jobs that
use `.nexus-install-pandoc`.

### How it works (mental model)

`include: component:` merges the component into your pipeline **before** it runs. After the
merge, the component's `default: image`/`default: cache`, its `variables:`, and the two
hidden fragments are part of *your* pipeline — the fragments behave exactly like hidden
jobs you wrote yourself, so `!reference [.nexus-pip-bootstrap, before_script]` just works.
You add the `include:` once and opt each job into the bootstrap it needs.

### Scenario 1 — pure-Python job, pip only (no pandoc)

The common case: lint/test a Python package. You get the Nexus image + pip-on-Nexus for free.

```yaml
include:
  - component: $CI_SERVER_FQDN/<group>/ci-components/python-nexus@1.0.0

test:
  before_script:
    - !reference [.nexus-pip-bootstrap, before_script]
    - pip install -e ".[dev]"       # resolves from the Nexus PyPI proxy
  script:
    - pytest
```

No `image:` line needed — the component's `default: image` supplies it. No `inputs:` needed
— `python_version` defaults to `3.11`.

### Scenario 2 — a job that also needs pandoc

Add the second fragment. It installs pandoc ≥ 3 on PATH (cached after the first run), so any
tool that shells out to `pandoc` finds it.

```yaml
docs:
  before_script:
    - !reference [.nexus-pip-bootstrap, before_script]
    - !reference [.nexus-install-pandoc, before_script]
    - pip install -e ".[docs]"
  script:
    - mytool-that-uses-pandoc build
```

Only add `.nexus-install-pandoc` to the jobs that actually need pandoc — keep it off
lint/test jobs so they stay fast.

### Scenario 3 — choose Python / pandoc versions

Override the inputs at include time (they shape the image tag and the pandoc cache key):

```yaml
include:
  - component: $CI_SERVER_FQDN/<group>/ci-components/python-nexus@1.0.0
    inputs:
      python_version: "3.12"     # → python:3.12-slim from Nexus
      pandoc_version: "3.5"      # must match the binary at NEXUS_PANDOC_URL
```

`pandoc_version` only keys the cache — make sure `NEXUS_PANDOC_URL` points at that pandoc
build. To matrix over Python versions, include the component twice in separate config files,
or use `parallel:matrix` with a per-job `image:` override (Scenario 5).

### Scenario 4 — add a project-specific cache (important gotcha)

The component sets the pip + pandoc caches under **`default: cache`**. GitLab's rule: a job
that declares its **own** `cache:` **replaces** `default.cache` for that job (caches do not
merge). So if a job needs an extra cache (e.g. a model/download dir), **re-list the shared
entries** so you don't lose pip/pandoc caching:

```yaml
variables:
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"   # already set by the component; shown for clarity

train:
  cache:
    - { key: "pip-$CI_COMMIT_REF_SLUG",  paths: [.cache/pip] }   # keep the component's pip cache
    - { key: "pandoc-$PANDOC_VERSION",   paths: [.cache/bin] }   # keep the component's pandoc cache
    - { key: "models-$CI_COMMIT_REF_SLUG", paths: [.cache/models] }  # your extra cache
  before_script:
    - !reference [.nexus-pip-bootstrap, before_script]
    - pip install -e ".[ml]"
  script:
    - python train.py
```

If you set a **top-level** `cache:` in your `.gitlab-ci.yml`, it overrides the component's
`default.cache` for the *whole* pipeline — usually not what you want. Prefer per-job caches.

### Scenario 5 — override the image for one job

The component's image is a `default:`, so any job can override it locally without affecting
the rest:

```yaml
build-wheels:
  image: "${NEXUS_DOCKER_REGISTRY}/python:3.11"   # full (non-slim) image for this job only
  before_script:
    - !reference [.nexus-pip-bootstrap, before_script]
  script:
    - python -m build
```

### Pinning & upgrades

| Pin | Resolves to | Use for |
|---|---|---|
| `@1.0.0` | exact release | **production** (recommended) — reproducible |
| `@1` | latest `1.x` | auto-pick patches/minors within a major |
| `@~latest` | latest published release | always-newest (accepts churn) |
| `@<branch>` / `@<sha>` | unreleased revision | testing a component change before it's tagged |

Pin to an exact tag in production and bump deliberately. A component change is a new tag in
`ci-components`; consumers adopt it by editing one `@<version>` line.

### Troubleshooting

| Symptom | Likely cause |
|---|---|
| Pipeline pulls `python` from Docker Hub / `401 Unauthorized` on the image | `NEXUS_DOCKER_REGISTRY` not set on your group, or its value doesn't match the registry host:port |
| `pip` reaches `pypi.org` instead of Nexus / TLS errors | `NEXUS_PYPI_INDEX_URL` unset, or Nexus uses an internal CA — set `PIP_TRUSTED_HOST` (or trust the corp CA) |
| `.nexus-install-pandoc` fails to download | `NEXUS_PANDOC_URL` unset or pointing at a missing artifact; verify the URL is reachable from a runner |
| `!reference [.nexus-pip-bootstrap, …]` "could not be found" | the `include: component:` line is missing, or the component address/`@version` is wrong |
| `@1.0.0` not found | that version isn't published in the Catalog yet — publish/tag it first, or pin a branch/SHA to test |

> Validate your `.gitlab-ci.yml` before pushing: open it in the GitLab **Pipeline Editor →
> Validate**, and check the **Merged YAML** tab — it should show the component's
> `default.image`/`default.cache`, its `variables:`, and the two hidden jobs inlined.

---

## Publishing / maintaining this component

This source is **scaffolded inside the `sdd-semantic-pipeline` repo** under
`gitlab/ci-component/` for review, but a CI/CD Catalog component must live in its **own**
GitLab project. To publish:

1. Create a GitLab project `<group>/ci-components` and push the **contents of this
   `gitlab/ci-component/` directory to its root** (so `templates/python-nexus/template.yml`
   sits at the repo root).
2. Add a project description + this README, then **Settings → CI/CD → CI/CD Catalog
   resource → ON**.
3. Set the three `NEXUS_*` variables at the **group** level.
4. Push a branch / open an MR → the `component-selftest` job validates the component at
   `@$CI_COMMIT_SHA` (pulls the Nexus image, installs pandoc, does a trivial pip install).
5. Tag a semver release (e.g. `1.0.0`) → the `release` job publishes it to the org Catalog.
6. Bump consumers' `@<version>` deliberately when the component changes.

> This directory is **not** consumed by the `sdd-semantic-pipeline` pipeline — it is inert
> to that repo's CI, doc-health, lint, type, test, and packaging gates.
