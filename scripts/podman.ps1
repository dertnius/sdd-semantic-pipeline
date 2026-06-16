#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Rootless Podman helper for the SDD Semantic Pipeline (Windows-first).

.DESCRIPTION
    Wraps the verbose rootless flags (--userns=keep-id, :Z relabel, --env-file)
    behind a small verb surface. The bash twin is scripts/podman.sh.

.EXAMPLE
    ./scripts/podman.ps1 build
    ./scripts/podman.ps1 build -Tag 0.1.0 -Extras azure,chroma
    ./scripts/podman.ps1 run check
    ./scripts/podman.ps1 run convert
    ./scripts/podman.ps1 run index inbox/sample/ --model all-MiniLM-L6-v2
    ./scripts/podman.ps1 push -Acr myregistry -Tag 0.1.0
    ./scripts/podman.ps1 acr-build -Acr myregistry -Tag 0.1.0
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)]
    [ValidateSet('build', 'run', 'check', 'push', 'acr-build', 'help')]
    [string]$Verb,

    [string]$Tag = 'latest',
    [string]$Extras = 'azure',
    [string]$Acr = '',
    [string]$Image = 'sdd-pipeline',

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path $PSScriptRoot -Parent

function Assert-Podman {
    if (-not (Get-Command podman -ErrorAction SilentlyContinue)) {
        throw "podman not found on PATH. Install Podman / Podman Desktop, then run 'podman machine start'."
    }
}

function Ensure-EnvFile {
    $envPath = Join-Path $RepoRoot '.env'
    if (-not (Test-Path $envPath)) {
        $example = Join-Path $RepoRoot '.env.example'
        Write-Warning ".env not found - creating it from .env.example. Edit it to add Azure creds / overrides."
        Copy-Item $example $envPath
    }
    return $envPath
}

function Get-LocalRef { "$Image`:$Tag" }
function Get-AcrRef { param($a) "$a.azurecr.io/$Image`:$Tag" }

switch ($Verb) {
    'build' {
        Assert-Podman
        $ref = Get-LocalRef
        Write-Host "==> podman build $ref (extras: $Extras)" -ForegroundColor Cyan
        podman build --build-arg "INSTALL_EXTRAS=$Extras" -t $ref $RepoRoot
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        if ($Acr) {
            $acrRef = Get-AcrRef $Acr
            podman tag $ref $acrRef
            Write-Host "==> tagged $acrRef" -ForegroundColor Cyan
        }
    }
    { $_ -in 'run', 'check' } {
        Assert-Podman
        $envFile = Ensure-EnvFile
        $command = if ($Verb -eq 'check') { @('check') } else { $Rest }
        if (-not $command) { throw "Usage: ./scripts/podman.ps1 run <sdd-pipeline command> [args...]" }
        $flags = @(
            '--rm',
            '--userns=keep-id:uid=1000,gid=1000',
            '-v', "$RepoRoot/inbox:/app/inbox:Z",
            '-v', "$RepoRoot/outbox:/app/outbox:Z",
            '-v', 'sdd-hf-cache:/app/.cache/huggingface',
            '--env-file', $envFile
        )
        Write-Host "==> podman run $(Get-LocalRef) $($command -join ' ')" -ForegroundColor Cyan
        podman run @flags (Get-LocalRef) @command
        exit $LASTEXITCODE
    }
    'push' {
        Assert-Podman
        if (-not $Acr) { throw "push requires -Acr <registry-name>" }
        $acrRef = Get-AcrRef $Acr
        Write-Host "==> az acr login --name $Acr; podman push $acrRef" -ForegroundColor Cyan
        az acr login --name $Acr
        podman push $acrRef
        exit $LASTEXITCODE
    }
    'acr-build' {
        if (-not $Acr) { throw "acr-build requires -Acr <registry-name>" }
        Write-Host "==> az acr build --registry $Acr --image $Image`:$Tag" -ForegroundColor Cyan
        az acr build --registry $Acr --image "$Image`:$Tag" --file (Join-Path $RepoRoot 'Containerfile') $RepoRoot
        exit $LASTEXITCODE
    }
    'help' {
        Get-Help $PSCommandPath -Detailed
    }
}
