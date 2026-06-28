<#
.SYNOPSIS
    Convert legacy binary Word .doc files to modern .docx using Microsoft Word.

.DESCRIPTION
    The sdd-pipeline reads OOXML .docx only; legacy binary .doc is rejected. This
    script converts every .doc under an inbox directory to .docx via Word COM
    automation, so the documents can flow through `sdd-pipeline convert-docx`.

    It is the CANONICAL implementation: the docx-to-chunks CI component inlines the
    same three-step logic into its Windows `prepare:doc-to-docx` job. Keep them in sync.

    Behaviour (exit codes match the CI job):
      * no .doc found       -> prints a notice, exits 0 (no-op)
      * Word not available  -> prints an error, exits 3 (so CI fails clearly)
      * Word available      -> SaveAs2(.docx) for each file (wdFormatDocumentDefault = 16)

    Requires Microsoft Word on a Windows host (Word COM is not available on Linux,
    nor in a container). Run it on Windows PowerShell 5.1 or PowerShell 7+ (pwsh).

    IMPORTANT — Word COM needs an INTERACTIVE desktop session. In a non-interactive
    automation context (a service account, a background/headless session, or a CI runner
    not running as a logged-in user) Documents.Open / SaveAs2 can hang. On a Windows CI
    runner use the shell executor running as a logged-in user (autologon). Locally, just
    run it in your own logged-in session. Password-protected .doc files also hang (Word
    prompts for a password) — unprotect them first.

.PARAMETER InboxDir
    Directory scanned for .doc files. Default: ./inbox

.PARAMETER Recurse
    Recurse into subdirectories. Default: on (use -Recurse:$false to disable).

.PARAMETER RemoveOriginal
    Delete each .doc after a successful conversion. Default: off (originals kept;
    `sdd-pipeline convert-docx` globs **/*.docx and ignores .doc anyway).

.EXAMPLE
    # Local fallback when CI has no Windows+Office runner:
    pwsh ./convert-doc-to-docx.ps1 -InboxDir inbox -Recurse
    git add inbox; git commit -m "convert .doc -> .docx"; git push
#>
[CmdletBinding()]
param(
    [string]$InboxDir = "inbox",
    [switch]$Recurse = $true,
    [switch]$RemoveOriginal
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $InboxDir)) {
    Write-Host "No inbox at '$InboxDir'; nothing to convert."
    exit 0
}

$gciArgs = @{ Path = $InboxDir; File = $true; Filter = "*.doc" }
if ($Recurse) { $gciArgs.Recurse = $true }
# -Filter "*.doc" also matches .docx on some providers; keep only true .doc.
$docs = Get-ChildItem @gciArgs | Where-Object { $_.Extension -ieq ".doc" }

if (-not $docs) {
    Write-Host "No legacy .doc files under '$InboxDir'; nothing to convert."
    exit 0
}
Write-Host "Found $($docs.Count) legacy .doc file(s) to convert."

try {
    $word = New-Object -ComObject Word.Application -ErrorAction Stop
} catch {
    Write-Error ("Microsoft Word is not available on this machine. Legacy .doc files are " +
        "NOT supported by the pipeline. Install Word, or convert these files to .docx with " +
        "another tool, then commit the .docx. Offending files: " + ($docs.FullName -join ', '))
    exit 3
}

$word.Visible = $false
$failed = 0
try {
    foreach ($d in $docs) {
        $docx = [System.IO.Path]::ChangeExtension($d.FullName, ".docx")
        Write-Host "Converting $($d.FullName) -> $docx"
        try {
            # ConfirmConversions=$false, ReadOnly=$true so a corrupt/locked file can't hang
            $doc = $word.Documents.Open($d.FullName, $false, $true)
            $doc.SaveAs2($docx, 16)   # 16 = wdFormatDocumentDefault (.docx)
            $doc.Close($false)
            if ($RemoveOriginal) { Remove-Item -LiteralPath $d.FullName -Force }
        } catch {
            Write-Host "ERROR converting $($d.FullName): $_"
            $failed++
        }
    }
} finally {
    $word.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
    [GC]::Collect(); [GC]::WaitForPendingFinalizers()
}

if ($failed -gt 0) {
    Write-Error "$failed file(s) failed to convert."
    exit 1
}
Write-Host "Converted $($docs.Count) .doc file(s) to .docx."
exit 0
