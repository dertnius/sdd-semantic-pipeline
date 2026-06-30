# sharepoint-download

A turnkey GitLab CI/CD component that downloads files from **SharePoint Online** folders into
a pipeline's `inbox/` using **[PnP.PowerShell](https://github.com/pnp/powershell)**, with the
SharePoint credential fetched at run time from **HashiCorp Vault** — **secretless** from
GitLab's side via an OIDC ID token (`id_tokens:` → Vault JWT auth).

It adds one job (`sharepoint-download`, in the `download` stage by default) that reads a YAML
manifest of `{ site, folder }` entries and downloads every file (recursively) from each into
`inbox/<dest>`, so the rest of a pipeline (e.g. `convert` → `export` → `index`) can process them.

> ## ⚠️ ACS retirement — read before using `auth_mode: secret`
> The default `auth_mode` is **`secret`**, which is the legacy **Azure ACS app-only** path
> (`-ClientId` + `-ClientSecret`). Microsoft **retired ACS app-only for SharePoint on
> 2026-04-02**. In a current tenant this **will fail even with a valid secret**. Use
> **`auth_mode: certificate`** (Entra app + certificate — the supported modern path) or
> **`auth_mode: managedidentity`** (Azure Managed Identity, secretless). `secret` is kept as
> the default only because the originating project requested it; switching is a one-input change.

## What it does

```
sharepoint-download (download stage)
  id_tokens -> Vault JWT login -> read SharePoint secret from KV
  -> PnP Connect-PnPOnline (secret | certificate | managedidentity)
  -> for each manifest entry: enumerate folder (recursive) + Get-PnPFile into inbox/<dest>
  -> write outbox/reports/sharepoint-download-report.json (collect-and-report; non-zero on any failure)
```

**No inline PowerShell.** The download logic is the single canonical script
[`scripts/download-sharepoint.ps1`](../../scripts/download-sharepoint.ps1) (Pester-tested,
locally runnable). A component included by another repo does **not** receive this repo's
`scripts/`, so the job **fetches** the script at run time from a Nexus raw repo (the `script_url`
input) — the same idiom `python-nexus` uses for the pandoc binary and `.install-vault` uses for
the `vault` CLI. Publish a **version-pinned** copy of the script to that raw repo on each
component release so a consumer pinned to `@<version>` fetches the matching script.

## Inputs

| Input | Default | Purpose |
|---|---|---|
| `manifest` | `config/sharepoint-manifest.yaml` | YAML manifest of `{ site, folder, dest?, recurse? }` entries to download |
| `auth_mode` | `secret` | `secret` = ACS app-only (**LEGACY, retired 2026-04-02**) · `certificate` = Entra app + cert · `managedidentity` = Azure MI |
| `client_id` | `""` | Entra/ACS application (client) id. Required for `secret` and `certificate` |
| `tenant` | `""` | Tenant, e.g. `contoso.onmicrosoft.com`. Required for `certificate` |
| `uami_client_id` | `""` | User-assigned managed identity client id (`managedidentity`; omit for system-assigned) |
| `stage` | `download` | Pipeline stage to attach the job to (must exist in the consuming pipeline) |
| `pwsh_image` | `${NEXUS_DOCKER_REGISTRY}/dotnet/powershell:7.4-debian-12` | Linux image with PowerShell 7; non-Nexus consumers override (e.g. `mcr.microsoft.com/dotnet/powershell:7.4-debian-12`) |
| `script_url` | `${NEXUS_SHAREPOINT_SCRIPT_URL}` | URL of `download-sharepoint.ps1` in a Nexus raw repo, fetched at job start. Pin to the component version's copy. |
| `vault_addr` | `""` | Vault address, e.g. `https://vault.corp.example.com`. Also the OIDC token audience (`aud`) |
| `vault_jwt_role` | `sdd-sharepoint` | Vault JWT auth role bound to this project's GitLab claims |
| `vault_secret_path` | `secret/sharepoint/sdd` | Vault KV path read with `vault kv get` (no `/data/` infix) |
| `vault_secret_field` | `client_secret` | KV field holding the client secret (`secret` mode) |
| `vault_cert_field` | `cert_base64` | KV field holding the base64 PFX (`certificate` mode) |
| `vault_cert_pw_field` | `cert_password` | KV field holding the PFX password (`certificate` mode; optional) |
| `nexus_vault_url` | `${NEXUS_VAULT_URL}` | URL of the `vault` CLI binary in a Nexus raw repo (fetched onto PATH at job start) |
| `nexus_psgallery_url` | `${NEXUS_PSGALLERY_URL}` | PowerShell-Gallery proxy URL for `Install-Module` (`PnP.PowerShell`, `powershell-yaml`) |

## Using it in *your* project

```yaml
# your-repo/.gitlab-ci.yml
include:
  - component: $CI_SERVER_FQDN/<group>/ci-components/sharepoint-download@1.0.0
    inputs:
      vault_addr: "https://vault.corp.example.com"
      client_id:  "00000000-0000-0000-0000-000000000000"
      auth_mode:  "certificate"        # recommended (see ACS note above)
      tenant:     "contoso.onmicrosoft.com"
```

Commit a `config/sharepoint-manifest.yaml`:

```yaml
entries:
  - site: "https://contoso.sharepoint.com/sites/Architecture"
    folder: "Shared Documents/SAD"     # site-relative (display name)
    dest: "sharepoint/arch-sad"        # optional; default sharepoint/<folder leaf>
    recurse: true                      # optional; default true
  - site: "https://contoso.sharepoint.com/sites/Platform"
    folder: "Shared Documents/ADRs"
```

The job runs on a **schedule** or a **manual "Run pipeline"** (Web) trigger. Downloaded files
land under `inbox/` (a `download`-stage artifact, 1-day retention) and a per-run report under
`outbox/reports/sharepoint-download-report.json`.

### Prerequisites

| Prerequisite | Notes |
|---|---|
| GROUP CI/CD variables `NEXUS_DOCKER_REGISTRY`, `NEXUS_VAULT_URL`, `NEXUS_PSGALLERY_URL`, `NEXUS_SHAREPOINT_SCRIPT_URL` | the pwsh image, the `vault` CLI binary (raw repo), a PowerShell-Gallery proxy, and the `download-sharepoint.ps1` script (raw repo). Override the corresponding inputs if you bring your own image / public egress. |
| A HashiCorp Vault reachable from the runner, with JWT auth configured for this GitLab | see *Vault setup* below. |
| An Entra app (service principal) with SharePoint **Sites** application permission (admin-consented) | the identity PnP connects as; its secret/cert lives in Vault. For `managedidentity`, grant the MI the Sites permission instead. |

### Vault setup (platform team, one-time)

```bash
vault auth enable jwt
vault write auth/jwt/config \
    oidc_discovery_url="https://gitlab.example.com" bound_issuer="https://gitlab.example.com"

# Role bound to this project's GitLab OIDC claims (least privilege).
vault write auth/jwt/role/sdd-sharepoint role_type="jwt" user_claim="user_email" \
    bound_audiences="https://vault.corp.example.com" bound_claims_type="glob" \
    bound_claims='{"project_path":"group/your-repo","ref_protected":"true"}' \
    token_policies="sdd-sharepoint-ro" token_ttl="10m"

# Read-only policy on the KV path.  (Note the KV v2 /data/ infix in the POLICY path.)
#   path "secret/data/sharepoint/sdd" { capabilities = ["read"] }
vault policy write sdd-sharepoint-ro sdd-sharepoint-ro.hcl

# Store the SharePoint credential.
vault kv put secret/sharepoint/sdd client_secret="<entra-app-secret>"
# certificate mode instead: cert_base64="<base64 PFX>" cert_password="<pfx pw>"
```

- **`vault_addr` must equal the role's `bound_audiences`** — the `id_tokens: aud:` is sent as the
  JWT audience; a mismatch fails the login.
- **KV v2 `/data/` quirk:** the *policy* path is `secret/data/sharepoint/sdd`, but the job runs
  `vault kv get secret/sharepoint/sdd` (the CLI inserts `/data/`). A common 403 cause.
- On GitLab **Premium/Ultimate** you can use the native `secrets:` keyword instead of the
  `vault` CLI; this component uses the CLI so it works on **any tier** and stays portable.

## Auth modes

| `auth_mode` | PnP connect | Vault stores | Notes |
|---|---|---|---|
| `secret` (default) | `-ClientId -ClientSecret` | `client_secret` | **LEGACY ACS, retired 2026-04-02.** May fail in a current tenant. |
| `certificate` | `-ClientId -Tenant -CertificateBase64Encoded -CertificatePassword` | `cert_base64` (+ `cert_password`) | Microsoft-recommended modern app-only. |
| `managedidentity` | `-ManagedIdentity [-UserAssignedManagedIdentityClientId]` | *(nothing)* | Secretless; needs an Azure-hosted runner with the identity assigned + Sites permission. |

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `Connect-PnPOnline failed … ACS app-only retired` | `auth_mode: secret` against a post-2026-04-02 tenant — switch to `certificate` or `managedidentity`. |
| Vault login `400 invalid audience` | `vault_addr` (the `aud`) doesn't match the role's `bound_audiences`. |
| `vault kv get` `403` / `not found` | KV v2 `/data/` infix in the policy path, or the role's `bound_claims` don't match this project/ref. |
| `Install-Module … not found` | `nexus_psgallery_url` unset or the proxy can't reach PowerShell Gallery; register/point it correctly. |
| `curl … vault` fails in `before_script` | `nexus_vault_url` unset or pointing at a missing artifact; verify it's reachable from a runner. |
| Folder downloads nothing | `folder` must be **site-relative** by display name (e.g. `Shared Documents/SAD`, not the internal `Documents`); check the manifest. |
| Files re-download every run | by design — full overwrite (`Get-PnPFile -Force`) each scheduled/manual run. |
