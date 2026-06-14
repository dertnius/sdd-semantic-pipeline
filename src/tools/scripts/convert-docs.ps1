<#
.SYNOPSIS
    Convert Confluence HTML exports to GitLab Markdown and quality-check the result.

.DESCRIPTION
    Runs the four-step "just convert documents" flow (Flow B) against the project
    venv. Pandoc-only: no embedding model is loaded or downloaded.

        1. check   - verify pandoc + Python deps (hard-stops if missing)
        2. convert - HTML -> Markdown (mirrors the input tree under -OutDir)
        3. review  - summarise the conversion report, list outputs, flag quarantine
        4. lint    - report-only quality pass over the converted Markdown

    Storage-format input and quarantined pages make `convert` exit non-zero; that
    is expected and does not stop the review/lint steps.

.PARAMETER InputDir
    Folder scanned recursively for *.html exports. Required.

.PARAMETER OutDir
    Where to write the .md files (mirrors the input tree).
    Default: <project>\build\md.

.PARAMETER Strict
    Pass --strict to lint so it exits non-zero on any block-severity issue.

.EXAMPLE
    .\scripts\convert-docs.ps1 -InputDir C:\exports\confluence

.EXAMPLE
    .\scripts\convert-docs.ps1 -InputDir .\tests\convert\examples -Strict
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$InputDir,
    [string]$OutDir,
    [switch]$Strict
)

# Don't let a native command's non-zero exit abort the script — we inspect
# $LASTEXITCODE ourselves (convert exits non-zero on a refused/quarantined file).
$ErrorActionPreference = 'Continue'
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false   # PowerShell 7.3+
}

# `check` (and `lint`) print non-ASCII glyphs (checkmarks); without UTF-8 the
# Windows cp1252 console crashes with UnicodeEncodeError when output is redirected.
$env:PYTHONUTF8 = '1'

# Project root = three levels up from this script (src\tools\scripts\ -> repo root); venv under it.
$proj = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$py   = Join-Path $proj '.venv\Scripts\python.exe'
if (-not (Test-Path $py))       { throw "venv interpreter not found at $py — create it or run 'pip install -e .[dev]' first." }
if (-not (Test-Path $InputDir)) { throw "InputDir not found: $InputDir" }
$InputDir = (Resolve-Path $InputDir).Path   # absolute, before we change directory

if (-not $OutDir) { $OutDir = Join-Path $proj 'build\md' }
$convRep = Join-Path $proj 'build\conversion-report.json'
$lintRep = Join-Path $proj 'build\quality-report.json'

Set-Location $proj

# 1) CHECK — pandoc + deps. Missing deps = stop here.
Write-Host "`n=== 1/4  check ===" -ForegroundColor Cyan
& $py -m sdd_pipeline.cli check
if ($LASTEXITCODE -ne 0) { throw "check failed (exit $LASTEXITCODE) — fix the environment first." }

# 2) CONVERT — HTML -> Markdown. Non-zero just means some files failed/quarantined.
Write-Host "`n=== 2/4  convert ===" -ForegroundColor Cyan
& $py -m sdd_pipeline.cli convert $InputDir --output $OutDir --report $convRep -v
$convExit = $LASTEXITCODE

# 3) REVIEW — summarise the report, list outputs, flag quarantine.
Write-Host "`n=== 3/4  review ===" -ForegroundColor Cyan
if (Test-Path $convRep) {
    $r = Get-Content $convRep -Raw | ConvertFrom-Json
    "converted: $($r.succeeded)/$($r.total_files)   failed: $($r.failed)   quarantined: $($r.quarantined)   warnings: $($r.warnings_total)"
    # anything that did not convert cleanly, with its error
    $r.files | Where-Object { $_.status -ne 'ok' } | ForEach-Object {
        "  [$($_.status)] $($_.source)"
        if ($_.error) { "      $($_.error)" }
    }
    # produced markdown
    Get-ChildItem -Recurse $OutDir -Filter *.md -ErrorAction SilentlyContinue |
        ForEach-Object { "  md: $($_.FullName)" }
    # quarantined output
    $q = Join-Path $OutDir '_quarantine'
    if (Test-Path $q) { Write-Warning "Quarantined output under $q — review before using." }
} else {
    Write-Warning "No conversion report at $convRep (convert may have aborted)."
}
if ($convExit -ne 0) {
    Write-Host "  (convert exit code $convExit — expected if a file was refused/quarantined)" -ForegroundColor DarkYellow
}

# 4) LINT — quality pass over the converted markdown.
Write-Host "`n=== 4/4  lint ===" -ForegroundColor Cyan
$lintArgs = @('-m', 'sdd_pipeline.cli', 'lint', $OutDir, '--report', $lintRep, '-v')
if ($Strict) { $lintArgs += '--strict' }
& $py @lintArgs
$lintExit = $LASTEXITCODE

Write-Host "`nDone. Reports: $convRep ; $lintRep" -ForegroundColor Green
exit $lintExit
