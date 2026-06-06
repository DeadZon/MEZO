#!/usr/bin/env bash
# DeadZone Plus — inherits Lite, then applies Plus-specific mods.
# Plus is the successor to Stable (compat alias).
set -euo pipefail

work_dir=${work_dir:-$(pwd)}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LITE_INSMOD="$SCRIPT_DIR/../Lite/insmod.sh"

echo "[STYLE] Plus: inheriting Lite base mods..."

if ! bash "$LITE_INSMOD"; then
    echo "[STYLE][ERROR] Lite insmod failed — aborting Plus." >&2
    exit 1
fi

echo "[STYLE] Plus: no extra Plus-only patches yet."
echo "[STYLE] Plus mods complete."
