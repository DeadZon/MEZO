#!/usr/bin/env python3
"""DeadZone MEZO framework.jar patch module."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..common.smali_utils import (
    find_smali_file, read_smali, write_smali,
    already_patched, replace_method_body, patch_method_decl_flag,
    insert_after_pattern, get_method_bounds, get_method_text,
)


@dataclass
class ModResult:
    name:    str
    applied: bool       = False
    skipped: bool       = False
    error:   str        = ""
    note:    str        = ""


# ── 1. Build.isBuildConsistent → always return true ──────────────────────────

def patch_build_is_consistent(workspace: Path, results: list) -> None:
    r = ModResult(name="Build.isBuildConsistent → always true")
    f = find_smali_file(workspace, "Landroid/os/Build;")
    if not f:
        r.skipped = True
        r.note = "android/os/Build.smali not found"
        results.append(r)
        return
    text = read_smali(f)
    marker = "KaoriosHook;->isBuildConsistent" if False else ":deadzone_build_consistent"
    # Use the new trivial body as marker
    new_body = "    .registers 1\n\n    const/4 v0, 0x1\n\n    return v0\n"
    if already_patched(text, new_body.strip()[:30]):
        r.applied = True
        r.note = "already patched"
        results.append(r)
        return
    new_text = replace_method_body(text, "isBuildConsistent()Z", new_body)
    if new_text == text:
        r.skipped = True
        r.note = "isBuildConsistent()Z method not found"
        results.append(r)
        return
    write_smali(f, new_text)
    r.applied = True
    results.append(r)


# ── 2. Activity.setDisablePreviewScreenshots → add whitelist flag ─────────────

def patch_activity_preview_screenshots(workspace: Path, results: list) -> None:
    r = ModResult(name="Activity.setDisablePreviewScreenshots → whitelist")
    f = find_smali_file(workspace, "Landroid/app/Activity;")
    if not f:
        r.skipped = True
        r.note = "android/app/Activity.smali not found"
        results.append(r)
        return
    text = read_smali(f)
    sig = "setDisablePreviewScreenshots(Z)V"
    if "whitelist setDisablePreviewScreenshots" in text:
        r.applied = True
        r.note = "already patched"
        results.append(r)
        return
    new_text = patch_method_decl_flag(text, sig, "public setDisablePreviewScreenshots", "public whitelist setDisablePreviewScreenshots")
    if new_text == text:
        r.skipped = True
        r.note = "setDisablePreviewScreenshots(Z)V method decl not found"
        results.append(r)
        return
    write_smali(f, new_text)
    r.applied = True
    results.append(r)


# ── 3. ApplicationPackageManager.getDefaultIcon → IconCustomizer ──────────────

def patch_apm_get_default_icon(workspace: Path, results: list) -> None:
    r = ModResult(name="ApplicationPackageManager.getDefaultIcon → IconCustomizer")
    f = find_smali_file(workspace, "Landroid/app/ApplicationPackageManager;")
    if not f:
        r.skipped = True
        r.note = "ApplicationPackageManager.smali not found"
        results.append(r)
        return
    text = read_smali(f)
    marker = "IconCustomizer;->getCustomizedIcon"
    if already_patched(text, marker):
        r.applied = True
        r.note = "already patched"
        results.append(r)
        return

    # Find getDefaultIcon method; insert IconCustomizer lookup before return-object
    method_bounds = get_method_bounds(text, "getDefaultIcon(")
    if method_bounds is None:
        r.skipped = True
        r.note = "getDefaultIcon method not found"
        results.append(r)
        return

    method_text = text[method_bounds[0]:method_bounds[1]]
    # Insert before return-object lines in this method
    import re
    lines = method_text.split("\n")
    new_lines: list[str] = []
    inserted = False
    for line in lines:
        if re.match(r"[ \t]*return-object\b", line) and not inserted:
            indent = re.match(r"([ \t]*)", line).group(1)
            new_lines += [
                "",
                f"{indent}invoke-static {{p1}}, Lmiui/content/pm/IconCustomizer;->getCustomizedIcon(Landroid/content/pm/ApplicationInfo;)Landroid/graphics/drawable/Drawable;",
                f"{indent}move-result-object v0",
                "",
                f"{indent}if-eqz v0, :cond_deadzone_icon",
                f"{indent}return-object v0",
                "",
                f"{indent}:cond_deadzone_icon",
            ]
            inserted = True
        new_lines.append(line)
    new_method = "\n".join(new_lines)
    new_text = text[:method_bounds[0]] + new_method + text[method_bounds[1]:]
    write_smali(f, new_text)
    r.applied = True
    r.note = "inserted IconCustomizer lookup in getDefaultIcon"
    results.append(r)


# ── 4. PackagePartitions → add ro.xiaomi.eu.version.code_time fingerprint ────

def patch_package_partitions_fingerprints(workspace: Path, results: list) -> None:
    r = ModResult(name="PackagePartitions fingerprints → add eu.version.code_time")
    f = find_smali_file(workspace, "Landroid/content/pm/PackagePartitions;")
    if not f:
        r.skipped = True
        r.note = "PackagePartitions.smali not found"
        results.append(r)
        return
    text = read_smali(f)
    eu_marker = "ro.xiaomi.eu.version.code_time"
    if already_patched(text, eu_marker):
        r.applied = True
        r.note = "already patched"
        results.append(r)
        return

    # Change array size: add-int/lit8 v0, v0, 0x1 → 0x2 (only the one near "ro.build.fingerprint")
    import re
    # Find the block that initializes the fingerprints array
    fingerprint_pos = text.find('"ro.build.fingerprint"')
    if fingerprint_pos == -1:
        r.skipped = True
        r.note = '"ro.build.fingerprint" string not found'
        results.append(r)
        return

    # Change add-int/lit8 ... 0x1 → 0x2 in a window around the fingerprint
    window_start = max(0, fingerprint_pos - 500)
    window_end   = min(len(text), fingerprint_pos + 500)
    window = text[window_start:window_end]
    new_window = re.sub(r"(add-int/lit8\s+\S+,\s+\S+,\s+)0x1\b", r"\g<1>0x2", window, count=1)
    if new_window == window:
        r.skipped = True
        r.note = "add-int/lit8 ... 0x1 pattern not found near ro.build.fingerprint"
        results.append(r)
        return

    # Rebuild text with new window
    text = text[:window_start] + new_window + text[window_end:]

    # Now insert eu.version.code_time after "ro.build.fingerprint" aput-object block
    # Pattern: const-string vX, "ro.build.fingerprint" ... aput-object vX vY vZ
    # We insert: aput-object vX vY vZ  → aput-object vX vY vZ \n add-int 0x1 \n const-string "ro.xiaomi.eu.version.code_time" \n aput-object
    # Find the aput-object line that follows "ro.build.fingerprint"
    lines = text.split("\n")
    new_lines: list[str] = []
    fingerprint_seen = False
    aput_count = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        if '"ro.build.fingerprint"' in line:
            fingerprint_seen = True
        if fingerprint_seen and re.match(r"[ \t]*aput-object\b", line) and aput_count == 0:
            indent = re.match(r"([ \t]*)", line).group(1)
            # Parse register operands from: aput-object vB, vC, vA
            m = re.match(r"[ \t]*aput-object\s+(\S+),\s+(\S+),\s+(\S+)", line)
            if m:
                vB, vC, vA = m.group(1), m.group(2), m.group(3)
                # Find index register used (vA)
                # Next insertion: increment index, add new string, aput-object again
                new_lines.append(line)
                new_lines.append("")
                new_lines.append(f"{indent}add-int/lit8 {vA}, {vA}, 0x1")
                new_lines.append("")
                new_lines.append(f'{indent}const-string {vB}, "ro.xiaomi.eu.version.code_time"')
                new_lines.append("")
                new_lines.append(f"{indent}aput-object {vB}, {vC}, {vA}")
                aput_count = 1
                i += 1
                fingerprint_seen = False
                continue
        new_lines.append(line)
        i += 1

    if aput_count == 0:
        r.skipped = True
        r.note = "Could not locate aput-object after ro.build.fingerprint"
        results.append(r)
        return

    write_smali(f, "\n".join(new_lines))
    r.applied = True
    results.append(r)
