#!/usr/bin/env bash
# DeadZone Legend — inherits Stable (-> Lite), then applies Legend-specific mods.
set -euo pipefail

work_dir=${work_dir:-$(pwd)}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STABLE_INSMOD="$SCRIPT_DIR/../Stable/insmod.sh"

echo "[STYLE] Legend: inheriting Stable (-> Lite) base mods..."

if ! bash "$STABLE_INSMOD"; then
    echo "[STYLE][ERROR] Stable insmod failed — aborting Legend." >&2
    exit 1
fi

echo "[STYLE] Legend: no extra Legend-only patches yet."
echo "[STYLE] Legend mods complete."
