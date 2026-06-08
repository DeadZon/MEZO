#!/usr/bin/env bash
# DeadZone Stable — compat alias for Lite (backward compatibility).
# Stable and Free are canonical aliases for Lite.
# This script must NOT delegate to Plus — Stable is Lite, not Plus.
set -euo pipefail

work_dir=${work_dir:-$(pwd)}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LITE_INSMOD="$SCRIPT_DIR/../Lite/insmod.sh"

echo "[STYLE] Stable: compat alias — resolves directly to Lite..."

if ! bash "$LITE_INSMOD"; then
    echo "[STYLE][ERROR] Lite insmod failed — aborting Stable compat." >&2
    exit 1
fi

echo "[STYLE] Stable (via Lite) mods complete."
