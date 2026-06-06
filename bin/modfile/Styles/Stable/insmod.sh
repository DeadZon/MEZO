#!/usr/bin/env bash
# DeadZone Stable — inherits Lite, then applies Stable-specific mods.
set -euo pipefail

work_dir=${work_dir:-$(pwd)}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LITE_INSMOD="$SCRIPT_DIR/../Lite/insmod.sh"

echo "[STYLE] Stable: inheriting Lite base mods..."

if ! bash "$LITE_INSMOD"; then
    echo "[STYLE][ERROR] Lite insmod failed — aborting Stable." >&2
    exit 1
fi

echo "[STYLE] Stable: no extra Stable-only patches yet."
echo "[STYLE] Stable mods complete."
