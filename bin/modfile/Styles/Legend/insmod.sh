#!/usr/bin/env bash
# DeadZone Legend — inherits Plus (-> Lite), then applies Legend-specific mods.
set -euo pipefail

work_dir=${work_dir:-$(pwd)}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUS_INSMOD="$SCRIPT_DIR/../Plus/insmod.sh"

echo "[STYLE] Legend: inheriting Plus (-> Lite) base mods..."

if ! bash "$PLUS_INSMOD"; then
    echo "[STYLE][ERROR] Plus insmod failed — aborting Legend." >&2
    exit 1
fi

echo "[STYLE] Legend: no extra Legend-only patches yet."
echo "[STYLE] Legend mods complete."
