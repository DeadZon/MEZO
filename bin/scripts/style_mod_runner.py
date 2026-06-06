#!/usr/bin/env python3
"""DeadZone MEZO Style Mod Runner

Reads bin/styles/<STYLE>/mods.json and runs all enabled mods in declared order.

Group deduplication:
  Multiple manifest entries can share the same ``group`` string.
  The first entry in a group triggers actual execution; subsequent entries in the
  same group are marked as 'applied via group leader' and skipped — avoiding
  duplicate calls when several manifest entries map to the same Python script.

Failure behaviour:
  - required=true  → write reports and exit 1 immediately.
  - required=false → log warning, mark status='failed', continue.
  - Script/module missing → mark status='skipped' (reason: not found), continue.

CLI:
  python3 bin/scripts/style_mod_runner.py --style lite --work-dir <project_root>

Reports:
  bin/output/reports/<style>_mod_report.txt
  bin/output/reports/<style>_mod_report.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).resolve().parent   # bin/scripts
BIN_DIR      = SCRIPT_DIR.parent                 # bin
PROJECT_ROOT = BIN_DIR.parent                    # repo root


def _ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())


def _load_manifest(style: str, project_root: Path) -> dict:
    manifest_path = project_root / "bin" / "styles" / style.capitalize() / "mods.json"
    if not manifest_path.is_file():
        # Also try lowercase
        manifest_path = project_root / "bin" / "styles" / style.lower() / "mods.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Mods manifest not found: {manifest_path}")
    with manifest_path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _run_python_mod(
    mod: dict,
    project_root: Path,
    style: str,
) -> tuple[bool, str]:
    """Run a Python mod entry. Returns (success, detail_message)."""
    python_entry = mod.get("python_entry", "")
    script = project_root / python_entry
    if not script.is_file():
        return False, f"python_entry not found: {script}"

    args: list[str] = list(mod.get("args", []))

    # Always inject --work-dir for scripts that accept it (deadzone_framework_patches.py does)
    if "--work-dir" not in args:
        args += ["--work-dir", str(project_root)]

    cmd = [sys.executable, str(script)] + args
    env = os.environ.copy()
    env.setdefault("DZ_STYLE_ID", style)
    env.setdefault("work_dir", str(project_root))

    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_root),
            env=env,
            capture_output=False,  # let stdout/stderr flow to terminal
        )
        if result.returncode == 0:
            return True, "exit 0"
        return False, f"exit {result.returncode}"
    except Exception as exc:
        return False, f"exception: {exc}"


def _run_shell_mod(
    mod: dict,
    project_root: Path,
    style: str,
) -> tuple[bool, str]:
    """Run a shell script mod entry. Returns (success, detail_message)."""
    script_path = mod.get("script_path", "")
    script = project_root / script_path
    if not script.is_file():
        return False, f"script_path not found: {script}"

    env = os.environ.copy()
    env["work_dir"] = str(project_root)
    env.setdefault("DZ_STYLE_ID", style)

    try:
        result = subprocess.run(
            ["bash", str(script)],
            cwd=str(project_root),
            env=env,
            capture_output=False,
        )
        if result.returncode == 0:
            return True, "exit 0"
        return False, f"exit {result.returncode}"
    except Exception as exc:
        return False, f"exception: {exc}"


def run_style(style: str, project_root: Path) -> list[dict[str, Any]]:
    """Run all mods for the given style. Returns list of result dicts."""
    manifest = _load_manifest(style, project_root)
    mods: list[dict] = manifest.get("mods", [])

    executed_groups: set[str] = set()
    results: list[dict[str, Any]] = []

    for mod in mods:
        mod_id    = mod.get("id", "unknown")
        mod_name  = mod.get("name", mod_id)
        enabled   = mod.get("enabled", True)
        required  = mod.get("required", False)
        group     = mod.get("group")
        desc      = mod.get("description", "")
        reports   = []  # report files this mod is known to generate

        entry: dict[str, Any] = {
            "id":          mod_id,
            "name":        mod_name,
            "enabled":     enabled,
            "required":    required,
            "source_stage": mod.get("source_stage", ""),
            "status":      "unknown",
            "reason":      "",
            "error":       None,
            "files_touched": [],
            "report_files":  reports,
            "description": desc,
        }

        # ── Disabled ──────────────────────────────────────────────────────────
        if not enabled:
            entry["status"] = "skipped"
            entry["reason"] = "disabled in manifest"
            results.append(entry)
            print(f"[MOD_RUNNER] SKIP  {mod_name!r}  (disabled)")
            continue

        # ── Group deduplication ───────────────────────────────────────────────
        if group and group in executed_groups:
            entry["status"] = "skipped"
            entry["reason"] = f"applied via group leader: {group}"
            results.append(entry)
            print(f"[MOD_RUNNER] SKIP  {mod_name!r}  (group {group!r} already executed)")
            continue

        # ── Execute ───────────────────────────────────────────────────────────
        print(f"[MOD_RUNNER] RUN   {mod_name!r}  ({'required' if required else 'optional'})")

        python_entry = mod.get("python_entry")
        script_path  = mod.get("script_path")

        if python_entry:
            ok, detail = _run_python_mod(mod, project_root, style)
        elif script_path:
            ok, detail = _run_shell_mod(mod, project_root, style)
        else:
            ok, detail = False, "no python_entry or script_path in manifest"

        # ── Result handling ───────────────────────────────────────────────────
        if ok:
            entry["status"] = "success"
            entry["reason"] = detail
            if group:
                executed_groups.add(group)
            print(f"[MOD_RUNNER] OK    {mod_name!r}")
        else:
            entry["status"] = "failed"
            entry["error"]  = detail
            print(f"[MOD_RUNNER] FAIL  {mod_name!r}: {detail}", file=sys.stderr)
            if required:
                results.append(entry)
                return results  # caller writes reports and exits

        results.append(entry)

    return results


def _write_reports(
    results: list[dict[str, Any]],
    style: str,
    project_root: Path,
) -> None:
    reports_dir = project_root / "bin" / "output" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    counts = {"success": 0, "skipped": 0, "failed": 0}
    for r in results:
        st = r.get("status", "unknown")
        counts[st] = counts.get(st, 0) + 1

    summary: dict[str, Any] = {
        "style":      style,
        "work_dir":   str(project_root),
        "generated":  _ts(),
        "mods":       results,
        "summary": {
            "total":   len(results),
            "success": counts.get("success", 0),
            "skipped": counts.get("skipped", 0),
            "failed":  counts.get("failed", 0),
        },
    }

    json_path = reports_dir / f"{style}_mod_report.json"
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    lines: list[str] = [
        f"DeadZone {style.capitalize()} Mod Report",
        "=" * 50,
        f"Generated : {_ts()}",
        f"Style     : {style}",
        f"Work dir  : {project_root}",
        "",
        f"Mods ({len(results)}):",
    ]
    for r in results:
        enabled_tag = "[ON ]" if r.get("enabled") else "[OFF]"
        req_tag     = "required" if r.get("required") else "optional"
        status      = r.get("status", "unknown").upper()
        name        = r.get("name", r.get("id", "?"))
        reason      = r.get("reason", "")
        error       = r.get("error", "")
        detail      = error or reason or ""
        lines.append(
            f"  {enabled_tag} [{status:<7}] [{req_tag:<8}]  {name}"
            + (f"  — {detail}" if detail else "")
        )
    lines += [
        "",
        "Summary:",
        f"  Total  : {len(results)}",
        f"  Success: {counts.get('success', 0)}",
        f"  Skipped: {counts.get('skipped', 0)}",
        f"  Failed : {counts.get('failed', 0)}",
        "",
    ]

    txt_path = reports_dir / f"{style}_mod_report.txt"
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[MOD_RUNNER] Report: {json_path}")
    print(f"[MOD_RUNNER] Report: {txt_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--style", required=True,
                    help="Style to run mods for (lite/stable/legend/ninja)")
    ap.add_argument("--work-dir", required=True,
                    help="Project root directory")
    args = ap.parse_args()

    style       = args.style.lower()
    project_root = Path(args.work_dir).resolve()

    if not project_root.is_dir():
        print(f"[MOD_RUNNER] ERROR: --work-dir does not exist: {project_root}", file=sys.stderr)
        sys.exit(1)

    manifest_path = project_root / "bin" / "styles" / style.capitalize() / "mods.json"
    if not manifest_path.is_file():
        manifest_path = project_root / "bin" / "styles" / style / "mods.json"
    if not manifest_path.is_file():
        print(f"[MOD_RUNNER] ERROR: manifest not found for style {style!r}", file=sys.stderr)
        print(f"[MOD_RUNNER]        Looked at: {manifest_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[MOD_RUNNER] Style      : {style}")
    print(f"[MOD_RUNNER] Work dir   : {project_root}")
    print(f"[MOD_RUNNER] Manifest   : {manifest_path}")

    results = run_style(style, project_root)
    _write_reports(results, style, project_root)

    # Always generate the aggregate full mod report — even if optional mods failed
    try:
        from deadzone_full_mod_report import write_full_report as _write_full_report
        _write_full_report(
            project_root / "bin" / "output" / "reports",
            dz_style=style,
        )
    except Exception as _fmr_exc:
        print(f"[MOD_RUNNER] WARN: deadzone_full_mod_report generation failed: {_fmr_exc}",
              file=sys.stderr)

    # Exit 1 if any required mod failed
    failed_required = [
        r for r in results
        if r.get("status") == "failed" and r.get("required")
    ]
    if failed_required:
        names = ", ".join(r["name"] for r in failed_required)
        print(f"[MOD_RUNNER] ERROR: required mod(s) failed: {names}", file=sys.stderr)
        sys.exit(1)

    print(f"[MOD_RUNNER] All mods complete for style={style!r}")


if __name__ == "__main__":
    main()
