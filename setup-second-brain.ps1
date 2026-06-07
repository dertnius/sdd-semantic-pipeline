# setup-second-brain.ps1
# Run from your project root.
# Creates the second brain folder structure and copies the template files.
#
# Usage:
#   cd C:\your\project
#   .\setup-second-brain.ps1
#
# Optional: point to a custom template location
#   .\setup-second-brain.ps1 -TemplatePath "C:\shared\second-brain-template"

param(
    [string]$TemplatePath = $PSScriptRoot
)

$ErrorActionPreference = "Stop"

function Create-Dir($path) {
    if (-not (Test-Path $path)) {
        New-Item -ItemType Directory -Path $path | Out-Null
        Write-Host "  created  $path" -ForegroundColor Green
    } else {
        Write-Host "  exists   $path" -ForegroundColor DarkGray
    }
}

function Create-File($path, $content) {
    if (-not (Test-Path $path)) {
        $content | Set-Content -Path $path -Encoding UTF8
        Write-Host "  created  $path" -ForegroundColor Green
    } else {
        Write-Host "  exists   $path (not overwritten)" -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "Second Brain Setup" -ForegroundColor Cyan
Write-Host "Project root: $(Get-Location)"
Write-Host ""

# ── Folders ──────────────────────────────────────────────────────────────
Write-Host "Folders:"
Create-Dir ".github"
Create-Dir "raw"
Create-Dir "wiki"

# ── Core instruction file ─────────────────────────────────────────────────
Write-Host ""
Write-Host "Instruction file:"
$instructionsSrc = Join-Path $TemplatePath ".github\copilot-instructions.md"
if (Test-Path $instructionsSrc) {
    if (-not (Test-Path ".github\copilot-instructions.md")) {
        Copy-Item $instructionsSrc ".github\copilot-instructions.md"
        Write-Host "  created  .github/copilot-instructions.md" -ForegroundColor Green
    } else {
        Write-Host "  exists   .github/copilot-instructions.md (not overwritten)" -ForegroundColor DarkGray
    }
} else {
    Write-Host "  WARNING: template not found at $instructionsSrc" -ForegroundColor Yellow
    Write-Host "           Copy copilot-instructions.md manually to .github/" -ForegroundColor Yellow
}

# ── Wiki seed files ───────────────────────────────────────────────────────
Write-Host ""
Write-Host "Wiki seed files:"

$today = Get-Date -Format "yyyy-MM-dd"

$indexContent = @"
# Wiki Index

_Last updated: $today_

| Page | Summary | Last Updated |
|------|---------|--------------|

_No pages yet. Drop a file into ``raw/`` and run ``/ingest <filename>`` in Copilot Chat._
"@
Create-File "wiki\index.md" $indexContent

$logContent = @"
# Second Brain Log

_Append-only. The agent writes here; do not edit manually._

---
"@
Create-File "wiki\log.md" $logContent

# ── .gitkeep for raw/ ─────────────────────────────────────────────────────
if (-not (Get-ChildItem "raw" -ErrorAction SilentlyContinue)) {
    "" | Set-Content "raw\.gitkeep" -Encoding UTF8
    Write-Host "  created  raw/.gitkeep" -ForegroundColor Green
}

# ── Done ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Done. Next steps:" -ForegroundColor Cyan
Write-Host "  1. Open this project in VS Code with GitHub Copilot enabled."
Write-Host "  2. Drop source files (docs, ADRs, release notes, standards) into raw/"
Write-Host "  3. Open Copilot Chat in Agent Mode and run:"
Write-Host "       /ingest <filename>"
Write-Host ""
Write-Host "Commands available once set up:"
Write-Host "  /ingest <file>   - ingest a raw source into the wiki"
Write-Host "  /query <topic>   - query the wiki for a grounded answer"
Write-Host "  /lint            - scan for broken links, orphans, stale pages"
Write-Host "  /apply           - apply safe lint fixes"
Write-Host ""
