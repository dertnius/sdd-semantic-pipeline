#!/usr/bin/env bash
# Rootless Podman helper for the SDD Semantic Pipeline (Linux / CI twin of
# scripts/podman.ps1). Wraps the verbose rootless flags behind a verb surface.
#
# Usage:
#   ./scripts/podman.sh build [--tag T] [--extras azure|azure,chroma] [--acr NAME]
#   ./scripts/podman.sh run <sdd-pipeline command> [args...]
#   ./scripts/podman.sh check
#   ./scripts/podman.sh push --acr NAME [--tag T]
#   ./scripts/podman.sh acr-build --acr NAME [--tag T]
#
# Examples:
#   ./scripts/podman.sh build --extras azure,chroma
#   ./scripts/podman.sh run convert
#   ./scripts/podman.sh run index inbox/sample/ --model all-MiniLM-L6-v2
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="sdd-pipeline"
TAG="latest"
EXTRAS="azure"
ACR=""

[[ $# -ge 1 ]] || { echo "usage: $0 <build|run|check|push|acr-build> ..." >&2; exit 2; }
VERB="$1"; shift

# Pull recognised --flags off the front; leave the rest for `run` to pass through.
REST=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)    TAG="$2"; shift 2 ;;
    --extras) EXTRAS="$2"; shift 2 ;;
    --acr)    ACR="$2"; shift 2 ;;
    --)       shift; REST+=("$@"); break ;;
    *)        REST+=("$1"); shift ;;
  esac
done

assert_podman() {
  command -v podman >/dev/null 2>&1 || {
    echo "podman not found on PATH. Install Podman, then 'podman machine start' if applicable." >&2
    exit 1
  }
}

ensure_env_file() {
  if [[ ! -f "$REPO_ROOT/.env" ]]; then
    echo "WARN: .env not found - creating from .env.example. Edit it to add Azure creds / overrides." >&2
    cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
  fi
}

local_ref() { echo "${IMAGE}:${TAG}"; }
acr_ref()   { echo "${ACR}.azurecr.io/${IMAGE}:${TAG}"; }

run_container() {
  ensure_env_file
  echo "==> podman run $(local_ref) $*" >&2
  exec podman run --rm \
    --userns=keep-id:uid=1000,gid=1000 \
    -v "$REPO_ROOT/inbox:/app/inbox:Z" \
    -v "$REPO_ROOT/outbox:/app/outbox:Z" \
    -v sdd-hf-cache:/app/.cache/huggingface \
    --env-file "$REPO_ROOT/.env" \
    "$(local_ref)" "$@"
}

case "$VERB" in
  build)
    assert_podman
    echo "==> podman build $(local_ref) (extras: $EXTRAS)" >&2
    podman build --build-arg "INSTALL_EXTRAS=$EXTRAS" -t "$(local_ref)" "$REPO_ROOT"
    if [[ -n "$ACR" ]]; then
      podman tag "$(local_ref)" "$(acr_ref)"
      echo "==> tagged $(acr_ref)" >&2
    fi
    ;;
  run)
    assert_podman
    [[ ${#REST[@]} -gt 0 ]] || { echo "usage: $0 run <sdd-pipeline command> [args...]" >&2; exit 2; }
    run_container "${REST[@]}"
    ;;
  check)
    assert_podman
    run_container check
    ;;
  push)
    assert_podman
    [[ -n "$ACR" ]] || { echo "push requires --acr NAME" >&2; exit 2; }
    echo "==> az acr login --name $ACR; podman push $(acr_ref)" >&2
    az acr login --name "$ACR"
    exec podman push "$(acr_ref)"
    ;;
  acr-build)
    [[ -n "$ACR" ]] || { echo "acr-build requires --acr NAME" >&2; exit 2; }
    echo "==> az acr build --registry $ACR --image ${IMAGE}:${TAG}" >&2
    exec az acr build --registry "$ACR" --image "${IMAGE}:${TAG}" \
      --file "$REPO_ROOT/Containerfile" "$REPO_ROOT"
    ;;
  *)
    echo "unknown verb: $VERB (build|run|check|push|acr-build)" >&2
    exit 2
    ;;
esac
