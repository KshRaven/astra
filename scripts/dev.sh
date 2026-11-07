#!/usr/bin/env bash
# Developer setup: install in editable mode and run against a throwaway config folder.
set -euo pipefail
cd "$(dirname "$0")/.."
export ASTRA_HOME="${ASTRA_HOME:-$PWD/.dev-home}"
python3 -m pip install -q -e . 
echo "Config folder: $ASTRA_HOME  (service/firewall/nginx tabs need root)"
exec astra web --host 127.0.0.1 "$@"
