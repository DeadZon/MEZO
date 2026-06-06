#!/usr/bin/env bash
# Bridge: delegates to bin/modfile/Styles/Legend/insmod.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/../../modfile/Styles/Legend/insmod.sh" "$@"
