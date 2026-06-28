#!/usr/bin/env bash
# Pull the latest CI-published lexical index into the local workspace so Copilot's
# local MCP server (lexical mode) searches a fresh corpus — no SSO, no model, no rebuild.
#
# Env:
#   GITLAB_URL      GitLab base URL (default https://gitlab.com)
#   GITLAB_PROJECT  project id or URL-encoded path (e.g. 1234 or group%2Frepo)
#   GITLAB_TOKEN    personal/CI token with read_api (masked; never commit)
#   PULL_REF        branch/tag the artifact was built on (default main)
#   PULL_JOB        artifact job name (default publish)
set -euo pipefail

GITLAB_URL="${GITLAB_URL:-https://gitlab.com}"
PULL_REF="${PULL_REF:-main}"
PULL_JOB="${PULL_JOB:-publish}"
: "${GITLAB_PROJECT:?set GITLAB_PROJECT}"
: "${GITLAB_TOKEN:?set GITLAB_TOKEN}"

url="${GITLAB_URL}/api/v4/projects/${GITLAB_PROJECT}/jobs/artifacts/${PULL_REF}/download?job=${PULL_JOB}"
tmp="$(mktemp -d)"
echo "Downloading index artifact from ${PULL_JOB}@${PULL_REF}..."
curl -fsSL --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" "$url" -o "${tmp}/artifacts.zip"

# Replace only the index (the artifact contains outbox/index + outbox/reports).
rm -rf outbox/index
unzip -oq "${tmp}/artifacts.zip" 'outbox/index/*' -d .
rm -rf "$tmp"
echo "Index refreshed at ./outbox/index — restart the MCP server in VS Code to pick it up."
