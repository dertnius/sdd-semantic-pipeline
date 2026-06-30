<#
.SYNOPSIS
    Download every file in one or more SharePoint Online folders into the pipeline
    inbox, using PnP.PowerShell.

.DESCRIPTION
    Reads a YAML manifest of {site, folder} entries and, for each, connects to
    SharePoint Online and downloads all files (recursively by default) into
    $PIPELINE_INBOX_DIR/<entry.dest> (default dest derived from the folder leaf),
    preserving the folder tree. Writes a JSON report to
    $PIPELINE_OUTBOX_DIR/reports/sharepoint-download-report.json that mirrors the
    HTTP downloader's download-report.json. Honours the inbox/outbox workspace
    contract (paths derived from env; a crafted server path cannot escape the inbox).

    It is the CANONICAL implementation: the `sharepoint-download` CI component inlines
    the same logic (a component cannot ship a loose file into a consumer's checkout),
    mirroring convert-doc-to-docx.ps1 <-> docx-to-chunks. Keep them in sync.

    AUTH MODES (-AuthMode):
      secret          (default) ACS app-only: -ClientId + -ClientSecret (env).
                      *** LEGACY: Azure ACS app-only for SharePoint was RETIRED on
                          2026-04-02. In a current tenant this WILL fail even with a
                          valid secret -- switch to 'certificate' or 'managedidentity'
                          (a one-flag change). Kept as the default per project request. ***
      certificate     Entra app + certificate: -ClientId + -Tenant +
                      -CertificateBase64Encoded + -CertificatePassword (env). The
                      Microsoft-recommended modern app-only path.
      managedidentity Azure Managed Identity: -ManagedIdentity
                      [+ -UserAssignedManagedIdentityClientId for a UAMI]. Secretless;
                      needs an Azure-hosted runner with the identity assigned and
                      granted SharePoint Sites permissions.

    SECRETS ARE ENV-ONLY (never parameters, never logged):
      $env:SHAREPOINT_CLIENT_SECRET   (secret mode)
      $env:SHAREPOINT_CERT_BASE64     (certificate mode; base64 PFX)
      $env:SHAREPOINT_CERT_PASSWORD   (certificate mode; PFX password, optional)

    Requires PowerShell 7 (pwsh) with the PnP.PowerShell and powershell-yaml modules
    installed. Cross-platform (Linux container, macOS, Windows).

.PARAMETER Manifest
    Path to the YAML manifest. Default: config/sharepoint-manifest.yaml. Shape:
        entries:
          - site:   "https://contoso.sharepoint.com/sites/Architecture"
            folder: "Shared Documents/SAD"     # site-relative
            dest:   "sharepoint/arch-sad"      # optional; default sharepoint/<folder leaf>
            recurse: true                      # optional; default true

.PARAMETER AuthMode
    secret (default) | certificate | managedidentity. See DESCRIPTION.

.PARAMETER ClientId
    Entra/ACS application (client) id. Required for secret and certificate modes.

.PARAMETER Tenant
    Tenant, e.g. contoso.onmicrosoft.com. Required for certificate mode (NOT secret).

.PARAMETER UserAssignedManagedIdentityClientId
    Client id of a user-assigned managed identity (managedidentity mode; omit for
    a system-assigned identity).

.PARAMETER IncludeExtensions
    Optional allow-list of file extensions (without the dot, e.g. docx,pdf,html). When
    set, only matching files are downloaded. Off by default (download every file).

.PARAMETER DryRun
    List the files that would be downloaded (and write the report) without downloading.

.EXAMPLE
    # Local dry-run (needs a reachable tenant + $env:SHAREPOINT_CLIENT_SECRET):
    pwsh ./download-sharepoint.ps1 -Manifest config/sharepoint-manifest.yaml `
        -AuthMode secret -ClientId 00000000-0000-0000-0000-000000000000 -DryRun
#>
[CmdletBinding()]
param(
    [string]$Manifest = "config/sharepoint-manifest.yaml",
    [ValidateSet('secret', 'certificate', 'managedidentity')]
    [string]$AuthMode = 'secret',
    [string]$ClientId,
    [string]$Tenant,
    [string]$UserAssignedManagedIdentityClientId,
    [string[]]$IncludeExtensions,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'   # Windows cp1252-safe; harmless elsewhere

# ── pure helpers (dot-sourceable; unit-tested by tests/download-sharepoint.Tests.ps1) ──

function Get-EnvOrDefault {
    param([string]$Name, [string]$Default)
    $v = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($v)) { return $Default }
    return $v
}

function Read-SharePointManifest {
    # Parse the YAML manifest into predictable PSCustomObjects with defaults applied.
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { throw "Manifest not found: $Path" }
    $doc = ConvertFrom-Yaml (Get-Content -Raw -LiteralPath $Path)
    if (-not $doc -or -not $doc.entries) { throw "Manifest '$Path' has no 'entries'." }
    $out = [System.Collections.ArrayList]::new()
    foreach ($e in $doc.entries) {
        $site = [string]$e.site
        $folder = [string]$e.folder
        if ([string]::IsNullOrWhiteSpace($site) -or [string]::IsNullOrWhiteSpace($folder)) {
            throw "Each manifest entry needs a non-empty 'site' and 'folder'."
        }
        $dest = if ($e.dest) { [string]$e.dest } else { 'sharepoint/' + ($folder.TrimEnd('/').Split('/')[-1]) }
        $recurse = if ($null -ne $e.recurse) { [bool]$e.recurse } else { $true }
        [void]$out.Add([pscustomobject]@{ site = $site; folder = $folder; dest = $dest; recurse = $recurse })
    }
    return $out.ToArray()
}

function Get-LocalTargetPath {
    # Map a SharePoint server-relative URL to a local path under $DestRoot, stripping the
    # web root and rejecting path traversal so a crafted server URL cannot escape the inbox.
    param(
        [Parameter(Mandatory = $true)][string]$DestRoot,
        [Parameter(Mandatory = $true)][string]$WebRoot,
        [Parameter(Mandatory = $true)][string]$ServerUrl
    )
    $rel = $ServerUrl
    $wr = $WebRoot.TrimEnd('/')
    if ($wr -and $rel.StartsWith($wr, [System.StringComparison]::OrdinalIgnoreCase)) {
        $rel = $rel.Substring($wr.Length)
    }
    $parts = $rel.Split('/') | Where-Object { $_ -ne '' -and $_ -ne '.' }
    if ($parts -contains '..') { throw "Refusing path traversal in server URL: $ServerUrl" }
    if (-not $parts) { throw "Empty relative path from server URL: $ServerUrl" }
    return (Join-Path $DestRoot ($parts -join [IO.Path]::DirectorySeparatorChar))
}

function Test-IncludedExtension {
    # $Include empty/null => everything is included.
    param([string]$FileName, [string[]]$Include)
    if (-not $Include -or $Include.Count -eq 0) { return $true }
    $ext = [IO.Path]::GetExtension($FileName).TrimStart('.')
    return ($Include | ForEach-Object { $_.TrimStart('.') }) -contains $ext
}

function New-DownloadReport {
    # Build the report object from the per-file result records (collect-and-report).
    param([object[]]$Results, [string]$AuthMode, [bool]$DryRun)
    $ok = @($Results | Where-Object { $_.status -eq 'ok' }).Count
    $errors = @($Results | Where-Object { $_.status -eq 'error' }).Count
    return [ordered]@{
        auth_mode = $AuthMode
        dry_run   = [bool]$DryRun
        total     = $Results.Count
        ok        = $ok
        errors    = $errors
        results   = $Results
    }
}

# ── PnP-backed steps (mockable in tests via Mock Connect-PnPOnline / Get-PnP*) ──

function Connect-ToSite {
    param(
        [Parameter(Mandatory = $true)][string]$Site,
        [string]$AuthMode = 'secret',
        [string]$ClientId,
        [string]$Tenant,
        [string]$UamiClientId
    )
    switch ($AuthMode) {
        'secret' {
            if (-not $ClientId) { throw "-ClientId is required for -AuthMode secret." }
            $secret = [Environment]::GetEnvironmentVariable('SHAREPOINT_CLIENT_SECRET')
            if ([string]::IsNullOrWhiteSpace($secret)) {
                throw "SHAREPOINT_CLIENT_SECRET env var is required for -AuthMode secret (env-only; never a parameter)."
            }
            # *** LEGACY ACS app-only (retired 2026-04-02). -ClientSecret takes NO -Tenant; realm is read from the URL. ***
            Connect-PnPOnline -Url $Site -ClientId $ClientId -ClientSecret $secret -ErrorAction Stop
        }
        'certificate' {
            if (-not $ClientId) { throw "-ClientId is required for -AuthMode certificate." }
            if (-not $Tenant) { throw "-Tenant is required for -AuthMode certificate." }
            $b64 = [Environment]::GetEnvironmentVariable('SHAREPOINT_CERT_BASE64')
            if ([string]::IsNullOrWhiteSpace($b64)) {
                throw "SHAREPOINT_CERT_BASE64 env var is required for -AuthMode certificate (env-only)."
            }
            $connectArgs = @{
                Url                      = $Site
                ClientId                 = $ClientId
                Tenant                   = $Tenant
                CertificateBase64Encoded = $b64
                ErrorAction              = 'Stop'
            }
            $certPw = [Environment]::GetEnvironmentVariable('SHAREPOINT_CERT_PASSWORD')
            if (-not [string]::IsNullOrWhiteSpace($certPw)) {
                $connectArgs.CertificatePassword = (ConvertTo-SecureString $certPw -AsPlainText -Force)
            }
            Connect-PnPOnline @connectArgs
        }
        'managedidentity' {
            if ($UamiClientId) {
                Connect-PnPOnline -Url $Site -ManagedIdentity -UserAssignedManagedIdentityClientId $UamiClientId -ErrorAction Stop
            }
            else {
                Connect-PnPOnline -Url $Site -ManagedIdentity -ErrorAction Stop
            }
        }
    }
}

function Get-SiteFilesRecursive {
    param([Parameter(Mandatory = $true)][string]$Rel, [bool]$Recurse)
    if (-not $Recurse) {
        return @(Get-PnPFolderItem -FolderSiteRelativeUrl $Rel -ItemType File)
    }
    try {
        return @(Get-PnPFolderItem -FolderSiteRelativeUrl $Rel -ItemType File -Recursive)
    }
    catch [System.Management.Automation.ParameterBindingException] {
        # Older PnP build without -Recursive: walk subfolders breadth-first.
        $acc = [System.Collections.ArrayList]::new()
        $queue = [System.Collections.Queue]::new()
        $queue.Enqueue($Rel)
        while ($queue.Count -gt 0) {
            $cur = $queue.Dequeue()
            foreach ($it in @(Get-PnPFolderItem -FolderSiteRelativeUrl $cur -ItemType All)) {
                if ($it.GetType().Name -eq 'Folder') { $queue.Enqueue("$cur/$($it.Name)") }
                else { [void]$acc.Add($it) }
            }
        }
        return $acc.ToArray()
    }
}

# ── orchestration ──

function Invoke-Main {
    if ([string]::IsNullOrWhiteSpace($Manifest)) {
        Write-Error "A -Manifest path is required (e.g. config/sharepoint-manifest.yaml)."
        return 2
    }
    foreach ($mod in 'PnP.PowerShell', 'powershell-yaml') {
        if (-not (Get-Module -ListAvailable -Name $mod)) {
            Write-Error "$mod is not installed. Install-Module $mod -Scope CurrentUser -Force"
            return 4
        }
        Import-Module $mod -ErrorAction Stop
    }

    $inbox = Get-EnvOrDefault 'PIPELINE_INBOX_DIR' (Join-Path $PWD 'inbox')
    $outbox = Get-EnvOrDefault 'PIPELINE_OUTBOX_DIR' (Join-Path $PWD 'outbox')
    $reportPath = Join-Path $outbox (Join-Path 'reports' 'sharepoint-download-report.json')
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $reportPath) | Out-Null

    try { $entries = Read-SharePointManifest -Path $Manifest }
    catch { Write-Error $_.Exception.Message; return 2 }

    $results = [System.Collections.ArrayList]::new()
    $failed = 0

    foreach ($entry in $entries) {
        Write-Host "== $($entry.site) :: $($entry.folder) -> inbox/$($entry.dest) (recurse=$($entry.recurse)) =="
        try {
            Connect-ToSite -Site $entry.site -AuthMode $AuthMode -ClientId $ClientId `
                -Tenant $Tenant -UamiClientId $UserAssignedManagedIdentityClientId
        }
        catch {
            $hint = ""
            if ($AuthMode -eq 'secret') {
                $hint = " If the tenant is post-2026-04-02, ACS app-only is retired -- use -AuthMode certificate or managedidentity."
            }
            Write-Error "Connect-PnPOnline failed for $($entry.site) (AuthMode=$AuthMode).$hint Error: $($_.Exception.Message)"
            $failed++
            continue
        }

        try {
            $webRoot = (Get-PnPWeb).ServerRelativeUrl
            $destRoot = Join-Path $inbox ($entry.dest -replace '/', [IO.Path]::DirectorySeparatorChar)
            $files = Get-SiteFilesRecursive -Rel $entry.folder -Recurse ([bool]$entry.recurse)

            foreach ($f in $files) {
                if (-not (Test-IncludedExtension -FileName $f.Name -Include $IncludeExtensions)) { continue }
                $serverUrl = $f.ServerRelativeUrl
                $local = Get-LocalTargetPath -DestRoot $destRoot -WebRoot $webRoot -ServerUrl $serverUrl
                $rec = [ordered]@{ site = $entry.site; url = $serverUrl; dest = $local; status = ''; bytes = 0; error = '' }
                if ($DryRun) {
                    $rec.status = 'dryrun'
                    Write-Host "DRYRUN  $serverUrl"
                }
                else {
                    try {
                        $dir = Split-Path -Parent $local
                        New-Item -ItemType Directory -Force -Path $dir | Out-Null
                        Get-PnPFile -Url $serverUrl -Path $dir -Filename ([IO.Path]::GetFileName($local)) -AsFile -Force -ErrorAction Stop
                        $rec.bytes = (Get-Item -LiteralPath $local).Length
                        $rec.status = 'ok'
                        Write-Host "OK      $serverUrl ($($rec.bytes) bytes)"
                    }
                    catch {
                        $rec.status = 'error'
                        $rec.error = $_.Exception.Message
                        $failed++
                        Write-Host "ERROR   $serverUrl : $($rec.error)"
                    }
                }
                [void]$results.Add([pscustomobject]$rec)
            }
        }
        catch {
            Write-Error "Failed enumerating $($entry.folder) on $($entry.site): $($_.Exception.Message)"
            $failed++
        }
        finally {
            try { Disconnect-PnPOnline -ErrorAction SilentlyContinue } catch { }
        }
    }

    $report = New-DownloadReport -Results $results.ToArray() -AuthMode $AuthMode -DryRun:$DryRun
    $report | ConvertTo-Json -Depth 6 | Out-File -FilePath $reportPath -Encoding utf8
    Write-Host "Report: $reportPath  (total=$($report.total) ok=$($report.ok) errors=$($report.errors))"

    if ($DryRun) { return 0 }
    if ($results.Count -eq 0) { Write-Host "No files matched; nothing downloaded."; return 0 }
    if ($failed -gt 0) { Write-Error "$failed item(s) failed (see $reportPath)."; return 1 }
    Write-Host "Downloaded $($report.ok) file(s) into inbox."
    return 0
}

# Run only when invoked directly (pwsh -File / & script.ps1), NOT when dot-sourced for testing.
if ($MyInvocation.InvocationName -ne '.') {
    exit (Invoke-Main)
}
