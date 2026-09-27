#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "list-targets" ]]; then
  shift
  exec python3 "$SCRIPT_DIR/zmk.py" list-targets "$@"
fi
exec python3 "$SCRIPT_DIR/zmk.py" build "$@"
