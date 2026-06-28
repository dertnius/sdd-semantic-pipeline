#!/usr/bin/env bash
# Convert a whole folder of mixed files (HTML + docx + gliffy) in one run.
#
# Chains the existing batch converters over one folder — each already processes ALL
# matching files recursively, so this is a convenience wrapper (pandoc-only, no model).
# It points the workspace zones at the input/output dirs, then runs:
#     convert        *.html   -> <out>/md/
#     convert-docx   *.docx   -> <out>/md/
#     resolve-gliffy *.gliffy -> <out>/media/   (or --drawio: convert-drawio -> drawio/)
# Reports land under <out>/reports/. A failed/quarantined file makes a step exit non-zero;
# that is reported but does not stop the other steps.
#
# Usage:
#   scripts/ingest.sh [-i INPUT_DIR] [-o OUT_DIR] [-t html,docx,gliffy] [--drawio] [--lint]
set -uo pipefail

proj="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
py="$proj/.venv/bin/python"
[ -x "$py" ] || py="$(command -v python3 || command -v python)"

input_dir="$proj/inbox"
out_dir="$proj/outbox"
types="html,docx,gliffy"
drawio=0
lint=0

while [ $# -gt 0 ]; do
  case "$1" in
    -i|--input)  input_dir="$2"; shift 2 ;;
    -o|--output) out_dir="$2"; shift 2 ;;
    -t|--types)  types="$2"; shift 2 ;;
    --drawio)    drawio=1; shift ;;
    --lint)      lint=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

[ -d "$input_dir" ] || { echo "InputDir not found: $input_dir" >&2; exit 1; }
mkdir -p "$out_dir"
input_dir="$(cd "$input_dir" && pwd)"
out_dir="$(cd "$out_dir" && pwd)"

# Point the workspace contract at the chosen folders, then run bare commands.
export PIPELINE_INBOX_DIR="$input_dir"
export PIPELINE_OUTBOX_DIR="$out_dir"
export PYTHONUTF8=1

gliffy_cmd="resolve-gliffy"; [ "$drawio" -eq 1 ] && gliffy_cmd="convert-drawio"

steps=()
case ",$types," in *,html,*)   steps+=("convert") ;; esac
case ",$types," in *,docx,*)   steps+=("convert-docx") ;; esac
case ",$types," in *,gliffy,*) steps+=("$gliffy_cmd") ;; esac

failures=()
n=${#steps[@]}; i=0
for cmd in "${steps[@]}"; do
  i=$((i+1))
  echo ""
  echo "=== $i/$n  $cmd ==="
  "$py" -m sdd_pipeline.cli "$cmd" -v || failures+=("$cmd (exit $?)")
done

if [ "$lint" -eq 1 ]; then
  echo ""
  echo "=== lint (Markdown quality) ==="
  "$py" -m sdd_pipeline.cli lint "$out_dir/md" -v || true
fi

echo ""
echo "Done. Outputs under $out_dir (md/, media/, reports/)."
if [ "${#failures[@]}" -gt 0 ]; then
  echo "Steps with non-zero exit: ${failures[*]} - see $out_dir/reports/." >&2
  exit 1
fi
