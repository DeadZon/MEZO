# UpdateFile Import Report

**Date:** 2026-06-08

---

## Source

| Field | Value |
|---|---|
| Upstream repo URL | https://github.com/tiencv2006/nothingsvn_xiaomi-toolbuild |
| Upstream commit hash | f30904654789bbc0b1598b2c517e95dbb6c3791a |
| Source path | bin/modfile/UpdateFile |
| Target path | C:\Users\hyper\Desktop\DeadZone_MEZO\bin\modfile\UpdateFile |

---

## Files Copied

| Metric | Count |
|---|---|
| Total files copied | 741 |
| Total folders copied | 267 |

### Top-level folders copied from upstream

```
China_GoogleCTS4A13
DevicesUpdate
FixTheme
Fonts
Framework_FixDelayPowerMenu
Framework_FixDevicePolicy
Global
Global_ConvertPoco2MiuiLauncher
Global_MultiverConvert2MiDialer
Global_POCO2Xiaomi
Marble_FixGlobalSignal
MultiLang
Provisions_RegionPatch
Settings_AdvancedTexture
Settings_FixNotificationHistory
Settings_GlobalFixTheme
Settings_GoogleShowUpCN
Settings_ROMInformation
System_MultiDisableFeature
ThermalServices
Xiaomi_NoLowEnd
```

Plus top-level file: `insupdate.sh`

---

## Executable Permissions

All `.sh` files under `bin/modfile/UpdateFile` were preserved with their original permissions. Shell scripts:

```
China_GoogleCTS4A13/update.sh
DevicesUpdate/update.sh
FixTheme/update.sh
Fonts/update.sh
Framework_FixDelayPowerMenu/update.sh
Framework_FixDevicePolicy/update.sh
Global/update.sh
Global_ConvertPoco2MiuiLauncher/update.sh
Global_MultiverConvert2MiDialer/update.sh
Global_POCO2Xiaomi/update.sh
insupdate.sh
Marble_FixGlobalSignal/update.sh
MultiLang/update.sh
Provisions_RegionPatch/update.sh
Settings_AdvancedTexture/update.sh
Settings_FixNotificationHistory/update.sh
Settings_GlobalFixTheme/update.sh
Settings_GoogleShowUpCN/update.sh
Settings_ROMInformation/update.sh
System_MultiDisableFeature/update.sh
ThermalServices/update.sh
Xiaomi_NoLowEnd/update.sh
```

---

## Branding Replacements

### Phase 1 — Initial import (commit afda749)

**File: `Settings_ROMInformation/update.sh`**

| Original | Replacement | Line(s) |
|---|---|---|
| `NothingsVN OpenSource` | `DeadZone` | 70 (simposcode property value) |
| `MIUINT` | `DeadZone` | 23, 24, 25 (MIUI About Phone display tag) |
| `NothingsOS` | `DeadZone` | 68 (version property value) |

### Phase 2 — Post-restore fix (commit after afda749)

**Property keys — `Settings_ROMInformation/update.sh`**

| Original | Replacement | Lines |
|---|---|---|
| `ro.nothings.version` | `ro.deadzone.version` | 68 |
| `ro.nothings.osversion` | `ro.deadzone.osversion` | 69 |
| `ro.nothings.simposcode` | `ro.deadzone.simposcode` | 70 |

**Property keys — `Settings_ROMInformation/getMiuiVersionInCard.ini`**

| Original | Replacement |
|---|---|
| `ro.nothings.version` | `ro.deadzone.version` |

**Property keys — `Settings_ROMInformation/getSimpleOSVersion.ini`**

| Original | Replacement |
|---|---|
| `ro.nothings.simposcode` | `ro.deadzone.simposcode` |

All three files are consistent: `update.sh` now writes `ro.deadzone.*` keys and the `.ini` smali patches read the same `ro.deadzone.*` keys.

**File/folder renames — `Global/`**

APK files had upstream `Nothings.` prefix in their filenames (visible when installed as overlays):

| Original filename | New filename |
|---|---|
| `Nothings.MiuiSystemUIPlugin.apk` | `DeadZone.MiuiSystemUIPlugin.apk` |
| `Nothings.MiuiSystemUI.apk` | `DeadZone.MiuiSystemUI.apk` |
| `Nothings.HyperPhoneSystemUI.apk` | `DeadZone.HyperPhoneSystemUI.apk` |

`Global/update.sh` references updated to match new filenames.

**Note:** The internal APK package name (inside the binary) still contains the upstream package identifier — that requires rebuilding the APK from source, which is outside the scope of this import.

---

## Integration Status

**Status: ALREADY INTEGRATED**

`insupdate.sh` is discovered and called by the MEZO style engine via `mods.json` entries:

| File | Line | Call |
|---|---|---|
| `bin/styles/Lite/mods.json` | 111 | `"script_path": "bin/modfile/UpdateFile/insupdate.sh"` |
| `bin/styles/Legend/mods.json` | 112 | `"script_path": "bin/modfile/UpdateFile/insupdate.sh"` |
| `bin/styles/Ninja/mods.json` | 112 | `"script_path": "bin/modfile/UpdateFile/insupdate.sh"` |
| `bin/styles/Plus/mods.json` | 112 | `"script_path": "bin/modfile/UpdateFile/insupdate.sh"` |

The upstream `insupdate.sh` uses `find "$TARGET_DIR" -type f -name "*.sh"` to auto-discover and run all module scripts, which is compatible with the existing MEZO integration.

No hook changes were made.

---

## MEZO Local Modules Restored After Upstream Import

The upstream `bin/modfile/UpdateFile` does not contain MEZO-specific modules. After the initial import (commit afda749) removed them, the following three modules were restored from backup to keep the existing Lite/Legend build pipeline and checks working:

| Module | Status | Purpose |
|---|---|---|
| `DeadZone_FrameworkPatcher/` | **Restored** | Compatibility wrapper for framework patches (now handled by Lite style engine; exits 0) |
| `DeadZone_JarMods/` | **Restored** | Unified JAR mod installer (feature-flagged; exits 0 unless `ENABLE_DEADZONE_JAR_MODS=true`) |
| `DeadZone_KaoriosToolbox/` | **Restored** | Compatibility wrapper for Kaorios Toolbox (now handled by Lite style engine; exits 0) |

These modules are MEZO-local additions not present in the upstream repository. They are discovered automatically by `insupdate.sh` via `find ... -name "*.sh"` and run alongside the upstream modules. No manual hook wiring was added.

**MEZO checks/tests that depend on these modules (now passing):**
- `bin/checks/check_framework_patcher.py` — checks for `UpdateFile/DeadZone_FrameworkPatcher/install.sh`
- `bin/checks/check_jar_patch_engine.py` — checks for `UpdateFile/DeadZone_JarMods/install.sh`
- `bin/checks/check_kaorios_assets.py` — checks for `UpdateFile/DeadZone_KaoriosToolbox/install.sh`
- `bin/checks/check_kaorios_style_enabled.py` — checks for `insupdate.sh` and `DeadZone_KaoriosToolbox/install.sh`
- `bin/tests/test_lite_style.py` — checks for `DeadZone_FrameworkPatcher/install.sh` and `DeadZone_KaoriosToolbox/install.sh`

---

## Syntax Check Results

### UpdateFile shell scripts

All 25 shell scripts (22 upstream + 3 MEZO-local) passed `bash -n` syntax check: **PASS**

### Root shell scripts (unchanged, verified unmodified)

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

---

## Confirmations

| Check | Status |
|---|---|
| GitHub workflow files modified | NO |
| Fly workflow files modified | NO |
| Root Dockerfile modified | NO |
| bot/bot.py modified | NO |
| build.sh modified | NO |
| setup.sh modified | NO |
| packROM.sh modified | NO |
| docker-entrypoint.sh modified | NO |
| Secrets committed | NO |
| Temp clone inside repo | NO |
| Backup folder inside repo | NO |
| __pycache__ or .pyc files | NO |
| Xiaomi/MIUI/HyperOS technical names corrupted | NO |

---

## Backup Location

Previous MEZO UpdateFile backed up to:
`C:\Users\hyper\Desktop\backup_MEZO_UpdateFile_20260608`

This folder is outside the git repository and will not be committed.
