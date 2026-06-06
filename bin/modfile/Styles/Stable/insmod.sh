#!/usr/bin/env bash
# DeadZone Stable — compat wrapper; delegates to Plus (the successor style).
set -euo pipefail

work_dir=${work_dir:-$(pwd)}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUS_INSMOD="$SCRIPT_DIR/../Plus/insmod.sh"

echo "[STYLE] Stable: compat alias — delegating to Plus..."

if ! bash "$PLUS_INSMOD"; then
    echo "[STYLE][ERROR] Plus insmod failed — aborting Stable compat." >&2
    exit 1
fi

echo "[STYLE] Stable (via Plus) mods complete."
