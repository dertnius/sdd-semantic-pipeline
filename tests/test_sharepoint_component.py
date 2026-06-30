"""Structural tests for the SharePoint download CI capability.

Model-free, no network, no pwsh: these assert the *structure* of the assets that CI and a
consuming repo rely on — the `sharepoint-download` component template parses and documents
its inputs, the canonical PowerShell script keeps its auth contract, and the root pipeline
wires the job. The live PnP path is exercised only against a real tenant (out of scope here);
the PowerShell helpers themselves are unit-tested by ``tests/download-sharepoint.Tests.ps1``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
COMPONENT_DIR = REPO / "gitlab" / "ci-component" / "templates" / "sharepoint-download"
TEMPLATE = COMPONENT_DIR / "template.yml"
README = COMPONENT_DIR / "README.md"
SCRIPT = REPO / "gitlab" / "ci-component" / "scripts" / "download-sharepoint.ps1"
MANIFEST = REPO / "config" / "sharepoint-manifest.yaml"
ROOT_CI = REPO / ".gitlab-ci.yml"


class _GitLabLoader(yaml.SafeLoader):
    """SafeLoader that understands GitLab's `!reference [job, key]` custom tag."""


_GitLabLoader.add_constructor("!reference", lambda loader, node: loader.construct_sequence(node))


def _template_docs() -> list[dict]:
    """The component template is a two-document YAML file: spec, then the body."""
    return [
        d for d in yaml.load_all(TEMPLATE.read_text(encoding="utf-8"), Loader=_GitLabLoader) if d
    ]


def _spec() -> dict:
    return _template_docs()[0]["spec"]


def _body() -> dict:
    return _template_docs()[1]


def _job() -> dict:
    return _body()["sharepoint-download"]


# ── template parses + inputs documented ─────────────────────────────────────────


def test_template_is_two_documents_with_spec_and_job() -> None:
    docs = _template_docs()
    assert len(docs) == 2, "template.yml must be spec + body (two YAML documents)"
    assert "inputs" in docs[0]["spec"]
    assert "sharepoint-download" in docs[1]


def test_every_input_is_documented_in_readme() -> None:
    inputs = _spec()["inputs"]
    expected = {
        "manifest",
        "auth_mode",
        "client_id",
        "tenant",
        "uami_client_id",
        "stage",
        "pwsh_image",
        "script_url",
        "vault_addr",
        "vault_jwt_role",
        "vault_secret_path",
        "vault_secret_field",
        "vault_cert_field",
        "vault_cert_pw_field",
        "nexus_vault_url",
        "nexus_psgallery_url",
    }
    assert expected <= set(inputs), f"missing inputs: {expected - set(inputs)}"
    readme = README.read_text(encoding="utf-8")
    for key in inputs:
        assert f"`{key}`" in readme, f"input '{key}' is not documented in README.md"


def test_auth_mode_default_and_options() -> None:
    am = _spec()["inputs"]["auth_mode"]
    assert am["default"] == "secret"
    assert set(am["options"]) == {"secret", "certificate", "managedidentity"}


# ── the component job wiring ─────────────────────────────────────────────────────


def test_job_has_oidc_id_token_and_inbox_artifact() -> None:
    job = _job()
    assert "VAULT_ID_TOKEN" in job["id_tokens"]
    assert job["id_tokens"]["VAULT_ID_TOKEN"]["aud"] == "$[[ inputs.vault_addr ]]"
    assert "inbox/" in job["artifacts"]["paths"]


def test_component_does_vault_login_and_fetches_the_script() -> None:
    raw = TEMPLATE.read_text(encoding="utf-8")
    assert "auth/jwt/login" in raw, "component must do a Vault JWT login"
    assert "vault kv get" in raw, "component must read the secret from Vault KV"
    assert "download-sharepoint.ps1" in raw, "component must fetch + run the canonical script"
    assert "$[[ inputs.script_url ]]" in raw, "component must fetch the script from script_url"


def test_component_has_no_inline_powershell() -> None:
    """The PnP logic must live only in the canonical script, never inlined in the template."""
    raw = TEMPLATE.read_text(encoding="utf-8")
    for forbidden in ("Connect-PnPOnline", "Get-PnPFile", "Get-PnPFolderItem", "ConvertFrom-Yaml"):
        assert forbidden not in raw, f"template must not inline PowerShell ({forbidden})"


# ── canonical PowerShell script contract ─────────────────────────────────────────


def test_script_supports_all_three_auth_modes() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for marker in ("-ClientSecret", "-CertificateBase64Encoded", "-ManagedIdentity"):
        assert marker in text, f"script missing auth marker {marker}"


def test_script_reads_secret_from_env_only() -> None:
    """The client secret must come from the environment, never a script parameter."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "SHAREPOINT_CLIENT_SECRET" in text
    # Isolate the param(...) block and assert the secret name is not a parameter.
    start = text.index("param(")
    depth = 0
    end = start
    for i in range(start + len("param"), len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    param_block = text[start : end + 1]
    assert "SHAREPOINT_CLIENT_SECRET" not in param_block, "secret must not be a parameter"


def test_script_is_dot_source_safe() -> None:
    """A main-guard keeps Pester dot-sourcing from executing the download."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "$MyInvocation.InvocationName" in text


def test_script_warns_about_acs_retirement() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "2026-04-02" in text, "the ACS-retirement caveat must be in the script"


# ── manifest seed + root pipeline wiring ─────────────────────────────────────────


def test_manifest_seed_is_valid_with_entries() -> None:
    doc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert doc and "entries" in doc and doc["entries"]
    for entry in doc["entries"]:
        assert entry.get("site") and entry.get("folder")


def test_root_pipeline_wires_the_job() -> None:
    ci = yaml.load(ROOT_CI.read_text(encoding="utf-8"), Loader=_GitLabLoader)
    assert "download:sharepoint" in ci, "root pipeline must define download:sharepoint"
    job = ci["download:sharepoint"]
    assert job["stage"] == "download"
    assert "VAULT_ID_TOKEN" in job["id_tokens"]
    raw = ROOT_CI.read_text(encoding="utf-8")
    assert "gitlab/ci-component/scripts/download-sharepoint.ps1" in raw
    assert ".install-vault" in raw
