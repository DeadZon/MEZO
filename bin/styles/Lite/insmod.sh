#!/usr/bin/env bash
# Bridge: delegates to bin/modfile/Styles/Lite/insmod.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/../../modfile/Styles/Lite/insmod.sh" "$@"
