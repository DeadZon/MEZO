#!/usr/bin/env bash
# DeadZone Ninja — inherits Plus (-> Lite), then applies Ninja-specific mods.
set -euo pipefail

work_dir=${work_dir:-$(pwd)}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUS_INSMOD="$SCRIPT_DIR/../Plus/insmod.sh"

echo "[STYLE] Ninja: inheriting Plus (-> Lite) base mods..."

if ! bash "$PLUS_INSMOD"; then
    echo "[STYLE][ERROR] Plus insmod failed — aborting Ninja." >&2
    exit 1
fi

echo "[STYLE] Ninja: no extra Ninja-only patches yet."
echo "[STYLE] Ninja mods complete."
