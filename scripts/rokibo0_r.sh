#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/zmk.py" build \
  --compose "$SCRIPT_DIR/../docker-compose-rokibo_0.yml" \
  --target rokibo_0-right \
  "$@"
