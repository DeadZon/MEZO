#!/usr/bin/env bash
# DeadZone Ninja — inherits Stable (-> Lite), then applies Ninja-specific mods.
set -euo pipefail

work_dir=${work_dir:-$(pwd)}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STABLE_INSMOD="$SCRIPT_DIR/../Stable/insmod.sh"

echo "[STYLE] Ninja: inheriting Stable (-> Lite) base mods..."

if ! bash "$STABLE_INSMOD"; then
    echo "[STYLE][ERROR] Stable insmod failed — aborting Ninja." >&2
    exit 1
fi

echo "[STYLE] Ninja: no extra Ninja-only patches yet."
echo "[STYLE] Ninja mods complete."
