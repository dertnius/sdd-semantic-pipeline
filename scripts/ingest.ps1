<#
.SYNOPSIS
    Convert a whole folder of mixed files (HTML + docx + gliffy) in one run.

.DESCRIPTION
    Chains the existing batch converters over one folder — each already processes ALL
    matching files recursively, so this is just a convenience wrapper (pandoc-only; no
    embedding model). It points the workspace zones at -InputDir / -OutDir, then runs:

        convert        *.html   -> <OutDir>\md\
        convert-docx   *.docx   -> <OutDir>\md\
        resolve-gliffy *.gliffy -> <OutDir>\media\   (or -Drawio: convert-drawio -> drawio\)

    Reports land under <OutDir>\reports\. A non-zero exit from a step (a failed or
    quarantined file) is reported but does not stop the other steps.

.PARAMETER InputDir
    Folder scanned recursively for *.html / *.docx / *.gliffy. Default: project inbox\.

.PARAMETER OutDir
    Output root (subfolders md\, media\, drawio\, reports\). Default: project outbox\.

.PARAMETER Types
    Comma-separated subset of: html, docx, gliffy. Default: all three.

.PARAMETER Drawio
    Emit draw.io XML (convert-drawio) instead of SVG (resolve-gliffy) for gliffy files.

.PARAMETER Lint
    Run a report-only quality pass over the produced Markdown afterwards.

.EXAMPLE
    .\scripts\ingest.ps1 -InputDir C:\exports\space-PLATFORM

.EXAMPLE
    .\scripts\ingest.ps1 -Types html,gliffy -Drawio -Lint
#>
[CmdletBinding()]
param(
    [string]$InputDir,
    [string]$OutDir,
    [string]$Types = "html,docx,gliffy",
    [switch]$Drawio,
    [switch]$Lint
)

# Inspect $LASTEXITCODE ourselves — a quarantined/failed file makes a step exit non-zero,
# which must not abort the remaining steps.
$ErrorActionPreference = 'Continue'
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false   # PowerShell 7.3+
}
$env:PYTHONUTF8 = '1'   # Windows cp1252 console crashes on non-ASCII glyphs otherwise

# Project root = two levels up from this script (scripts\ -> repo root); venv under it.
$proj = Split-Path -Parent $PSScriptRoot
$py   = Join-Path $proj '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw "venv interpreter not found at $py - run 'pip install -e .[dev]' first." }

if (-not $InputDir) { $InputDir = Join-Path $proj 'inbox' }
if (-not $OutDir)   { $OutDir   = Join-Path $proj 'outbox' }
if (-not (Test-Path $InputDir)) { throw "InputDir not found: $InputDir" }
$InputDir = (Resolve-Path $InputDir).Path
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path

# Point the workspace contract at the chosen folders, then run bare commands: each reads
# this inbox and writes its standard subfolder under this outbox (contract satisfied).
$env:PIPELINE_INBOX_DIR  = $InputDir
$env:PIPELINE_OUTBOX_DIR = $OutDir

$typeSet = $Types.Split(',') | ForEach-Object { $_.Trim().ToLower() }
$steps = @()
if ($typeSet -contains 'html')   { $steps += ,@('convert',      'HTML  -> md') }
if ($typeSet -contains 'docx')   { $steps += ,@('convert-docx', 'docx  -> md') }
if ($typeSet -contains 'gliffy') {
    $steps += ,@($(if ($Drawio) { 'convert-drawio' } else { 'resolve-gliffy' }), 'gliffy -> diagram')
}

$failures = @()
$i = 0
foreach ($step in $steps) {
    $i++
    $cmd, $desc = $step
    Write-Host "`n=== $i/$($steps.Count)  $cmd  ($desc) ===" -ForegroundColor Cyan
    & $py -m sdd_pipeline.cli $cmd -v
    if ($LASTEXITCODE -ne 0) {
        $failures += "$cmd (exit $LASTEXITCODE)"
        Write-Host "  ($cmd exit $LASTEXITCODE - some files failed/quarantined; continuing)" -ForegroundColor DarkYellow
    }
}

if ($Lint) {
    Write-Host "`n=== lint (Markdown quality) ===" -ForegroundColor Cyan
    & $py -m sdd_pipeline.cli lint (Join-Path $OutDir 'md') -v
}

Write-Host "`nDone. Outputs under $OutDir (md\, media\, reports\)." -ForegroundColor Green
if ($failures.Count) {
    Write-Warning ("Steps with non-zero exit: " + ($failures -join ', ') + " - see outbox\reports\.")
    exit 1
}
