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

Only one file contained upstream branding text that required replacement:

**File: `Settings_ROMInformation/update.sh`**

| Original | Replacement | Line(s) |
|---|---|---|
| `NothingsVN OpenSource` | `DeadZone` | 70 |
| `MIUINT` | `DeadZone` | 23, 24, 25 |
| `NothingsOS` | `DeadZone` | 68 |

**Explanation:**
- Line 70: `ro.nothings.simposcode=NothingsVN OpenSource $myversion` → property value uses ROM brand name
- Lines 23-25: `sed` commands replace "MIUI"/"MIUI Pad"/"MIUI Fold" display text with the ROM tag; upstream used `MIUINT` (NothingsVN team tag), replaced with `DeadZone`
- Line 68: `ro.nothings.version=NothingsOS $myversion` → property value uses ROM brand name

**Not replaced (intentional):**
- `ro.nothings.` property key prefix — this is a system property key used by the ROM; changing it would break any code that reads this property. Only the VALUE was replaced, not the key.

### File/Folder Name Branding

No file or folder names contained upstream branding patterns (`NothingsVN`, `nothingsvn`, `EliteRom`, `HyperVN`, etc.). No renames were performed.

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

## Warnings

### MEZO-specific modules removed

The previous MEZO `bin/modfile/UpdateFile` contained three MEZO-specific modules that **do not exist in the upstream** and were removed when the folder was replaced:

| Removed module | Backed up at |
|---|---|
| `DeadZone_FrameworkPatcher/` | `C:\Users\hyper\Desktop\backup_MEZO_UpdateFile_20260608\DeadZone_FrameworkPatcher\` |
| `DeadZone_JarMods/` | `C:\Users\hyper\Desktop\backup_MEZO_UpdateFile_20260608\DeadZone_JarMods\` |
| `DeadZone_KaoriosToolbox/` | `C:\Users\hyper\Desktop\backup_MEZO_UpdateFile_20260608\DeadZone_KaoriosToolbox\` |

**Affected MEZO checks/tests that will now fail:**
- `bin/checks/check_framework_patcher.py` — checks for `UpdateFile/DeadZone_FrameworkPatcher/install.sh`
- `bin/checks/check_jar_patch_engine.py` — checks for `UpdateFile/DeadZone_JarMods/install.sh`
- `bin/checks/check_kaorios_assets.py` — checks for `UpdateFile/DeadZone_KaoriosToolbox/install.sh`
- `bin/checks/check_kaorios_style_enabled.py` — checks for both `insupdate.sh` and `DeadZone_KaoriosToolbox/install.sh`
- `bin/tests/test_lite_style.py` — checks for `DeadZone_FrameworkPatcher/install.sh` and `DeadZone_KaoriosToolbox/install.sh`

**Action required:** These MEZO-specific modules should be added back to the new UpdateFile from the backup, or the checks should be updated. This import task does not add integration hooks automatically.

---

## Syntax Check Results

### UpdateFile shell scripts

All 22 shell scripts passed `bash -n` syntax check: **PASS**

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
