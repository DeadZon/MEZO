# Package Import Report

**Date:** 2026-06-08

---

## Source

| Field | Value |
|---|---|
| Upstream repo URL | https://github.com/tiencv2006/nothingsvn_xiaomi-toolbuild |
| Upstream commit hash | f30904654789bbc0b1598b2c517e95dbb6c3791a |
| Source path | bin/package |
| Target path | C:\Users\hyper\Desktop\DeadZone_MEZO\bin\package |

---

## Files Copied

| Metric | Count |
|---|---|
| Total files copied | 678 |
| Total folders copied | 73 |

### Top-level modules copied from upstream

```
COREPATCH         (new — not in previous MEZO bin/package)
DISABLE_AVB       (updated from upstream)
KouseiPatcher     (new — not in previous MEZO bin/package)
NOTIFICATION_FIX  (new — not in previous MEZO bin/package)
RefreshRate       (updated from upstream)
patchpackage.sh   (updated — now calls all 5 modules)
```

### patchpackage.sh change (upstream → active)

Previous MEZO `patchpackage.sh` called only:
- `DISABLE_AVB/DISABLEavb.sh`
- `RefreshRate/1hz.sh`

Upstream `patchpackage.sh` now calls all 5 modules:
- `COREPATCH/update.sh`
- `DISABLE_AVB/DISABLEavb.sh`
- `KouseiPatcher/update.sh`
- `NOTIFICATION_FIX/notificationFIX.sh`
- `RefreshRate/1hz.sh`

---

## Branding Replacements

Only one file contained upstream branding requiring replacement:

**File: `COREPATCH/tools.sh`**

| Change | Description |
|---|---|
| Removed hardcoded GitHub Actions runner paths | Replaced with dynamic `$(dirname BASH_SOURCE)` relative path |

Original (upstream):
```bash
: "${TOOLS_DIR:=/home/runner/work/nothingsvn_xiaomi-toolbuild/nothingsvn_xiaomi-toolbuild/bin/apktool}"
: "${WORK_DIR:=/home/runner/work/nothingsvn_xiaomi-toolbuild/nothingsvn_xiaomi-toolbuild}"
```

Replaced with (branding removed + path compatibility):
```bash
: "${WORK_DIR:=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
: "${TOOLS_DIR:=${WORK_DIR}/bin/apktool}"
```

This is a combined branding replacement (`nothingsvn_xiaomi-toolbuild` removed) and minimal path compatibility fix (relative path resolution instead of hardcoded GitHub Actions runner path).

### Remaining branding matches

None — no other branding text found in bin/package text files.

---

## Integration Status

**Status: ALREADY INTEGRATED — enhanced with env flag**

### Existing hook

`build.sh` line 163 already called `patchpackage.sh`. The call was updated to:
1. Add `ENABLE_DEADZONE_PACKAGE_PATCHES` flag (default: `true`)
2. Pass `WORK_DIR` and `TOOLS_DIR` as environment variables to prevent COREPATCH from falling back to wrong paths

```bash
if [ "${ENABLE_DEADZONE_PACKAGE_PATCHES:-true}" = "true" ]; then
    WORK_DIR="$work_dir" TOOLS_DIR="$work_dir/bin/apktool" bash "$work_dir/bin/package/patchpackage.sh"
else
    echo "[package] ENABLE_DEADZONE_PACKAGE_PATCHES=false — skipping patchpackage.sh"
fi
```

To skip all package patches: set `ENABLE_DEADZONE_PACKAGE_PATCHES=false` in the build environment.

### KouseiPatcher config

`KouseiPatcher/update.sh` reads `install_toolbox` from `config.env`. MEZO's `config.env` already has:
```
install_toolbox=true
```
No changes required.

---

## Old Overlapping MEZO Systems — Status

### Overlap audit

| Upstream module | Old MEZO overlap | Status |
|---|---|---|
| `COREPATCH` | `DeadZone_FrameworkPatcher`, `DeadZone_JarMods` | Already disabled — both exit 0 by default |
| `KouseiPatcher` | `DeadZone_KaoriosToolbox` | Already disabled — exits 0 by default |
| `DISABLE_AVB` | Previous `bin/package/DISABLE_AVB` | Replaced by upstream version |
| `RefreshRate` | Previous `bin/package/RefreshRate` | Replaced by upstream version |
| `NOTIFICATION_FIX` | No prior MEZO equivalent | No overlap — purely new module |

### Detail: DeadZone_FrameworkPatcher (COREPATCH overlap)

- **Old path:** `bin/modfile/UpdateFile/DeadZone_FrameworkPatcher/install.sh`
- **Old invocation:** Auto-discovered by `insupdate.sh` via `find ... -name "*.sh"`
- **Current status:** Already effectively disabled — `install.sh` is a compatibility wrapper that exits 0 (unless `ENABLE_DEADZONE_FRAMEWORK_PATCHER=true`)
- **New replacement:** `bin/package/COREPATCH/` (per-Android-version JAR patcher)
- **How to re-enable old:** Set `ENABLE_DEADZONE_FRAMEWORK_PATCHER=true` in build environment

### Detail: DeadZone_JarMods (COREPATCH overlap)

- **Old path:** `bin/modfile/UpdateFile/DeadZone_JarMods/install.sh`
- **Old invocation:** Auto-discovered by `insupdate.sh` via `find ... -name "*.sh"`
- **Current status:** Already effectively disabled — `install.sh` is a feature-flagged wrapper that exits 0 (unless `ENABLE_DEADZONE_JAR_MODS=true`)
- **New replacement:** `bin/package/COREPATCH/` (handles JAR patching for A13/A14/A15/A16)
- **How to re-enable old:** Set `ENABLE_DEADZONE_JAR_MODS=true` in build environment

### Detail: DeadZone_KaoriosToolbox (KouseiPatcher overlap)

- **Old path:** `bin/modfile/UpdateFile/DeadZone_KaoriosToolbox/install.sh`
- **Old invocation:** Auto-discovered by `insupdate.sh` via `find ... -name "*.sh"`
- **Current status:** Already effectively disabled — `install.sh` is a compatibility wrapper that exits 0 (unless `ENABLE_DEADZONE_KAORIOS_TOOLBOX=true`)
- **New replacement:** `bin/package/KouseiPatcher/` (reads `install_toolbox=true` from `config.env`)
- **How to re-enable old:** Set `ENABLE_DEADZONE_KAORIOS_TOOLBOX=true` in build environment

### Non-overlapping UpdateFile modules (unchanged)

The following UpdateFile modules are NOT affected and remain active:
- `Settings_ROMInformation`
- `Global`
- `Fonts`
- `ThermalServices`
- `Xiaomi_NoLowEnd`
- `FixTheme`
- `DevicesUpdate`
- `MultiLang`
- `Provisions_RegionPatch`
- All other non-overlapping modules

---

## Syntax Check Results

### bin/package shell scripts

All 29 shell scripts passed `bash -n` syntax check: **PASS**

Checked:
```
COREPATCH/apk_ops.sh
COREPATCH/helper.sh
COREPATCH/jar_patcher_a13.sh
COREPATCH/jar_patcher_a14.sh
COREPATCH/jar_patcher_a15.sh
COREPATCH/jar_patcher_a16.sh
COREPATCH/logging.sh
COREPATCH/patching.sh
COREPATCH/tools.sh
COREPATCH/update.sh
DISABLE_AVB/DISABLEavb.sh
DISABLE_AVB/HMATools/aosp/system/extras/f2fs_utils/mkf2fsuserimg.sh
DISABLE_AVB/HMATools/aosp/system/tools/mkbootimg/gki/boot_signature_info.sh
KouseiPatcher/fakelock_patch.sh
KouseiPatcher/patcher.sh
KouseiPatcher/update.sh
NOTIFICATION_FIX/A13/patchMIUIFramework.sh
NOTIFICATION_FIX/A13/patchMIUIServices.sh
NOTIFICATION_FIX/A13/PowerKeeper.sh
NOTIFICATION_FIX/A14/patchMIUIFramework.sh
NOTIFICATION_FIX/A14/patchMIUIServices.sh
NOTIFICATION_FIX/A14/PowerKeeper.sh
NOTIFICATION_FIX/A15/patchMIUIServices.sh
NOTIFICATION_FIX/A15/PowerKeeper.sh
NOTIFICATION_FIX/A16/patchMIUIServices.sh
NOTIFICATION_FIX/A16/PowerKeeper.sh
NOTIFICATION_FIX/notificationFIX.sh
patchpackage.sh
RefreshRate/1hz.sh
```

### Root shell scripts

| Script | Result |
|---|---|
| setup.sh | PASS |
| build.sh | PASS |
| packROM.sh | PASS |
| docker-entrypoint.sh | PASS |

### Python files

| Script | Result |
|---|---|
| bin/scripts/package_rom.py | PASS |
| bin/scripts/telegram.py | PASS |
| bin/scripts/pixeldrain_upload.py | PASS |
| bot/bot.py | PASS |
| bin/checks/check_framework_patcher.py | PASS |
| bin/checks/check_kaorios_style_enabled.py | PASS |

---

## Confirmations

| Check | Status |
|---|---|
| GitHub workflow files modified | NO |
| Fly workflow files modified | NO |
| Root Dockerfile modified | NO |
| bot/bot.py modified | NO |
| setup.sh modified | NO |
| packROM.sh modified | NO |
| docker-entrypoint.sh modified | NO |
| build.sh modified | YES — added ENABLE_DEADZONE_PACKAGE_PATCHES flag + WORK_DIR/TOOLS_DIR env vars |
| Secrets committed | NO |
| Temp clone inside repo | NO |
| Backup folder inside repo | NO |
| __pycache__ or .pyc files | NO |
| Xiaomi/MIUI/HyperOS technical names corrupted | NO |

---

## Backup Location

Previous MEZO bin/package backed up to:
`C:\Users\hyper\Desktop\backup_MEZO_package_20260608`

This folder is outside the git repository and will not be committed.
