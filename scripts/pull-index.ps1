# Pull the latest CI-published lexical index into the local workspace so Copilot's
# local MCP server (lexical mode) searches a fresh corpus — no SSO, no model, no rebuild.
#
# Env:
#   GITLAB_URL      GitLab base URL (default https://gitlab.com)
#   GITLAB_PROJECT  project id or URL-encoded path (e.g. 1234 or group%2Frepo)
#   GITLAB_TOKEN    personal/CI token with read_api (masked; never commit)
#   PULL_REF        branch/tag the artifact was built on (default main)
#   PULL_JOB        artifact job name (default publish)
$ErrorActionPreference = "Stop"

$GitlabUrl = if ($env:GITLAB_URL) { $env:GITLAB_URL } else { "https://gitlab.com" }
$Ref       = if ($env:PULL_REF)   { $env:PULL_REF }   else { "main" }
$Job       = if ($env:PULL_JOB)   { $env:PULL_JOB }   else { "publish" }
if (-not $env:GITLAB_PROJECT) { throw "set GITLAB_PROJECT" }
if (-not $env:GITLAB_TOKEN)   { throw "set GITLAB_TOKEN" }

$url = "$GitlabUrl/api/v4/projects/$($env:GITLAB_PROJECT)/jobs/artifacts/$Ref/download?job=$Job"
$tmp = New-Item -ItemType Directory -Path (Join-Path $env:TEMP ([System.Guid]::NewGuid()))
$zip = Join-Path $tmp "artifacts.zip"

Write-Host "Downloading index artifact from $Job@$Ref..."
Invoke-WebRequest -Uri $url -Headers @{ "PRIVATE-TOKEN" = $env:GITLAB_TOKEN } -OutFile $zip

if (Test-Path "outbox/index") { Remove-Item -Recurse -Force "outbox/index" }
Expand-Archive -Path $zip -DestinationPath "." -Force   # artifact contains outbox/index + outbox/reports
Remove-Item -Recurse -Force $tmp
Write-Host "Index refreshed at ./outbox/index - restart the MCP server in VS Code to pick it up."
