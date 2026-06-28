# python-nexus

Stock `python:3.x-slim` from the enterprise Nexus registry + pip-on-Nexus + runtime
pandoc — no custom container image. See **[Using `python-nexus` in your
project](../../README.md#using-python-nexus-in-your-project)** in the parent README for the
full consumer guide (prerequisites, scenarios, cache gotcha, pinning, troubleshooting) and
the publishing steps.

## Quick reference

```yaml
include:
  - component: $CI_SERVER_FQDN/<group>/ci-components/python-nexus@1.0.0
    inputs:
      python_version: "3.11"   # default
      pandoc_version: "3.5"    # default

build:
  before_script:
    - !reference [.nexus-pip-bootstrap, before_script]
    - !reference [.nexus-install-pandoc, before_script]   # only if the job needs pandoc
    - pip install -e ".[dev]"
  script:
    - pytest
```

| Provides | |
|---|---|
| `default: image:` | `${NEXUS_DOCKER_REGISTRY}/python:<python_version>-slim` |
| `default: cache:` | pip wheel cache + `pandoc-<pandoc_version>` binary cache |
| `variables:` | `PIP_INDEX_URL`, `PIP_CACHE_DIR`, `PIP_DISABLE_PIP_VERSION_CHECK`, `PANDOC_VERSION` |
| `.nexus-pip-bootstrap` | upgrades pip from the Nexus proxy |
| `.nexus-install-pandoc` | installs pandoc ≥ 3 on PATH from `NEXUS_PANDOC_URL` |

Requires the group-level `NEXUS_DOCKER_REGISTRY` / `NEXUS_PYPI_INDEX_URL` /
`NEXUS_PANDOC_URL` CI/CD variables.
