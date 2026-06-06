#!/usr/bin/env bash
# DeadZone Ninja style mods — Stable + performance/gaming extras (placeholder).
# Called after base mods run, before repacking.
set -e

work_dir=${work_dir:-$(pwd)}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
PATCHES_PY="$PROJECT_ROOT/bin/scripts/deadzone_framework_patches.py"

echo "[STYLE] Ninja: running DeadZone framework patches (Stable base)..."

if ! python3 "$PATCHES_PY" --work-dir "$work_dir" --style stable; then
    echo "[STYLE][ERROR] deadzone_framework_patches.py exited with error — aborting." >&2
    exit 1
fi

echo "[STYLE] Ninja mods complete (performance/gaming extras: placeholder for future additions)."
