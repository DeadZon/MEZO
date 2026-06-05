#!/usr/bin/env python3
"""DeadZone JAR Patch Engine

Unified engine that applies all registered JAR mods in a single pass:
  1. Discover target JARs in the extracted ROM.
  2. Decode each JAR exactly once with apktool.
  3. Apply all registered mods for that JAR in the same decoded workspace.
  4. Rebuild each JAR exactly once.
  5. Replace the original JAR.
  6. Write clear reports.

Runs as a base mod for ALL DeadZone styles (Stable, Legend, and future).
Called via bin/modfile/UpdateFile/DeadZone_JarMods/install.sh.

Reports written to:
  output/reports/jar_patches/deadzone_mezo_jar_mods_report.txt
  output/reports/jar_patches/deadzone_mezo_jar_mods_error.txt  (on failure)
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── Paths ─────────────────────────────────────────────────────────────────────
WORK_DIR     = Path.cwd()
REPORTS_DIR  = WORK_DIR / "output" / "reports"
LOGS_DIR     = WORK_DIR / "output" / "logs"
DDEVICE_DIR  = WORK_DIR / "bin" / "ddevice"
BUILD_IMAGES = WORK_DIR / "build" / "baserom" / "images"

# ── JAR candidates (ordered by preference) ────────────────────────────────────
JAR_CANDIDATES: dict[str, list[str]] = {
    "framework": [
        "system/framework/framework.jar",
    ],
    "services": [
        "system/framework/services.jar",
    ],
    "telephony-common": [
        "system/framework/telephony-common.jar",
    ],
    "mediatek-telephony-common": [
        "system_ext/framework/mediatek-telephony-common.jar",
        "system/framework/mediatek-telephony-common.jar",
    ],
    "miui-framework": [
        "system_ext/framework/miui-framework.jar",
        "system/framework/miui-framework.jar",
        "product/framework/miui-framework.jar",
    ],
    "miui-services": [
        "system_ext/framework/miui-services.jar",
        "system/framework/miui-services.jar",
        "product/framework/miui-services.jar",
    ],
    "miui-wifi": [
        "system_ext/framework/miui-wifi-service.jar",
        "system/framework/miui-wifi-service.jar",
    ],
}


# ── Bootstrap: ensure jar_patches is importable ───────────────────────────────
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from jar_patches.common.jar_workspace import (
    find_java, find_apktool, find_jar, backup_jar,
    decompile_jar, rebuild_jar, replace_jar,
)
from jar_patches.deadzone_mezo_jar_mods import registry
from jar_patches.deadzone_mezo_jar_mods.report import (
    write_jar_mods_report, write_jar_error_report,
)


def _dread(fname: str) -> str:
    p = DDEVICE_DIR / fname
    return p.read_text(encoding="utf-8", errors="replace").strip() if p.is_file() else ""


def main() -> int:
    style    = _dread("dz_style") or os.environ.get("DZ_STYLE", "Stable")
    codename = _dread("codename") or os.environ.get("DZ_CODENAME", "unknown")

    print(f"[JAR-ENGINE] DeadZone MEZO JAR Mods — style={style} codename={codename}")

    java = find_java()
    if not java:
        msg = "java not found in PATH — cannot run apktool"
        print(f"[JAR-ENGINE] ERROR: {msg}", file=sys.stderr)
        write_jar_error_report(msg, REPORTS_DIR)
        return 1

    apktool = find_apktool(WORK_DIR)
    if not apktool:
        msg = "apktool.jar not found (checked bin/tools/, bin/apktool/, tools/, ./)"
        print(f"[JAR-ENGINE] ERROR: {msg}", file=sys.stderr)
        write_jar_error_report(msg, REPORTS_DIR)
        return 1

    print(f"[JAR-ENGINE] java={java}  apktool={apktool}")

    jar_names = registry.get_all_jar_names()
    run_data: dict = {
        "style":    style,
        "codename": codename,
        "jar_results": {},
    }

    overall_ok = True

    with tempfile.TemporaryDirectory(prefix="dz_jarmods_") as tmpdir:
        tmp = Path(tmpdir)

        for jar_name in jar_names:
            candidates = JAR_CANDIDATES.get(jar_name, [])
            jar_path   = find_jar(BUILD_IMAGES, candidates)
            mods       = registry.get_mods_for_jar(jar_name)

            jar_data: dict = {
                "path":    str(jar_path) if jar_path else "not found",
                "found":   jar_path is not None,
                "backup":  "",
                "rebuilt": False,
                "error":   "",
                "mods":    [],
            }
            run_data["jar_results"][jar_name] = jar_data

            if not jar_path:
                print(f"[JAR-ENGINE] {jar_name}: not found — skipping {len(mods)} mods")
                jar_data["mods"] = [
                    {"name": m["name"], "skipped": True, "note": "JAR not found in ROM", "error": "", "applied": False}
                    for m in mods
                ]
                continue

            print(f"[JAR-ENGINE] {jar_name}: found at {jar_path}")

            # Backup
            backup = backup_jar(jar_path)
            jar_data["backup"] = str(backup)

            # Decompile
            ws = tmp / jar_name.replace("-", "_") / "workspace"
            ok, err = decompile_jar(jar_path, apktool, java, ws)
            if not ok:
                msg = f"apktool d failed: {err[:200]}"
                print(f"[JAR-ENGINE] {jar_name}: DECOMPILE FAILED: {msg}", file=sys.stderr)
                jar_data["error"] = msg
                jar_data["mods"] = [
                    {"name": m["name"], "error": "JAR decompile failed", "skipped": False, "applied": False, "note": ""}
                    for m in mods
                ]
                # Check if any core mod
                if any(m["core"] for m in mods):
                    overall_ok = False
                continue

            # Apply all mods
            mod_results: list = []
            for mod in mods:
                print(f"[JAR-ENGINE]   mod: {mod['name']}")
                try:
                    mod["fn"](ws, mod_results)
                except Exception as exc:
                    mod_results.append({
                        "name":    mod["name"],
                        "applied": False,
                        "skipped": False,
                        "error":   str(exc),
                        "note":    "",
                    })
                    if mod["core"]:
                        overall_ok = False

            # Normalise mod_results to dicts
            norm_results: list[dict] = []
            for mr in mod_results:
                if hasattr(mr, "__dict__"):
                    norm_results.append({
                        "name":    mr.name,
                        "applied": mr.applied,
                        "skipped": mr.skipped,
                        "error":   mr.error,
                        "note":    mr.note,
                    })
                else:
                    norm_results.append(mr)
            jar_data["mods"] = norm_results

            # Check core failures
            core_names = {m["name"] for m in mods if m["core"]}
            for mr in norm_results:
                if mr["name"] in core_names and mr.get("error"):
                    overall_ok = False

            # Rebuild
            out_jar = tmp / jar_name.replace("-", "_") / "rebuilt.jar"
            ok, err = rebuild_jar(ws, apktool, java, out_jar)
            if not ok:
                msg = f"apktool b failed: {err[:200]}"
                print(f"[JAR-ENGINE] {jar_name}: REBUILD FAILED: {msg}", file=sys.stderr)
                jar_data["error"] = (jar_data.get("error") or "") + " | rebuild: " + msg
                if any(m["core"] for m in mods):
                    overall_ok = False
                continue

            # Replace original
            replace_jar(out_jar, jar_path)
            jar_data["rebuilt"] = True
            print(f"[JAR-ENGINE] {jar_name}: replaced successfully")

    # Write report
    report_path = write_jar_mods_report(run_data, REPORTS_DIR)
    print(f"[JAR-ENGINE] Report: {report_path}")

    if not overall_ok:
        write_jar_error_report("One or more core mods failed. See main report.", REPORTS_DIR)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
