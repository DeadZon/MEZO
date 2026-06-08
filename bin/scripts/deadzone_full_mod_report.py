#!/usr/bin/env python3
"""DeadZone Full Mod Report — unified aggregation of all per-mod JSON/TXT reports.

Reads all known report files from bin/output/reports/ and merges them into one
structured document:
  bin/output/reports/deadzone_full_mod_report.txt
  bin/output/reports/deadzone_full_mod_report.json

CLI:
  python3 bin/scripts/deadzone_full_mod_report.py [--work-dir <path>] [--style <style>]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR   = Path(__file__).resolve().parent
BIN_DIR      = SCRIPT_DIR.parent
PROJECT_ROOT = BIN_DIR.parent
REPORTS_DIR  = PROJECT_ROOT / "bin" / "output" / "reports"


def _ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())


# ── Report file lists ──────────────────────────────────────────────────────────

# JSON reports beyond *_mod_report.json
_EXTRA_JSON_REPORTS = [
    "deadzone_patch_report.json",
    "lite_apk_patches_report.json",
    "poco_launcher_spoof_report.json",
    "active_mods_report.json",
]

# Text-only reports (kaorios writes TXT but no JSON)
_TEXT_ONLY_REPORTS = [
    "kaorios_assets_report.txt",
    "kaorios_toolbox_report.txt",
    "kaorios_framework_patch_report.txt",
]


# ── Group assignment ───────────────────────────────────────────────────────────

_APK_PATCH_NAMES = frozenset({
    "provision_mezo_strings", "miuisystemui_volte_cn",
    "powerkeeper_cn_global_patches", "powerkeeper_cn_global",
})
_FW_MOD_IDS = frozenset({
    "deadzone_patches", "signature_bypass", "framework_patches",
    "signature_verification_bypass", "invoke_custom_handling",
    "fix_bootloop_a15", "miui_services_cn_global_patches",
})


def _assign_group(entry: dict, source_file: str) -> str:
    """Assign a display group based on source report and entry fields."""
    src = source_file.lower()
    patch_name = entry.get("patch_name", "")
    mod_id = str(entry.get("id", entry.get("patch", ""))).lower()

    if "deadzone_patch_report" in src or "framework" in src:
        return "Framework/JAR"
    if "lite_apk_patches" in src or patch_name in _APK_PATCH_NAMES:
        return "APK/App"
    if "poco" in src:
        return "Device props"
    if "kaorios" in src:
        return "Toolbox"
    if "final_zip" in src:
        return "Packaging"
    # Heuristic for mod_report entries
    if any(x in mod_id for x in ("apk", "provision", "miuisystem", "powerkeeper")):
        return "APK/App"
    if any(x in mod_id for x in _FW_MOD_IDS):
        return "Framework/JAR"
    if "poco" in mod_id:
        return "Device props"
    if "kaorios" in mod_id:
        return "Toolbox"
    if any(x in mod_id for x in ("zip", "pack", "final")):
        return "Packaging"
    return "Other"


# ── Report collection ──────────────────────────────────────────────────────────

def _load_json_report(path: Path, out: list) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["_source_file"] = path.name
        out.append(data)
    except Exception as exc:
        out.append({"_source_file": path.name, "_error": f"Failed to parse: {exc}"})


def _parse_text_report(path: Path) -> dict:
    """Convert a text-only report to a minimal dict with a synthetic result entry."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        return {"_source_file": path.name, "_error": str(exc)}

    # Detect overall status from text
    text_lower = text.lower()
    if "validation: pass" in text_lower or "status: pass" in text_lower:
        status = "success"
    elif "validation: fail" in text_lower or "status: fail" in text_lower:
        status = "failed"
    elif "pass" in text_lower and "fail" not in text_lower:
        status = "success"
    else:
        status = "skipped"

    return {
        "_source_file": path.name,
        "_text_only": True,
        "results": [{
            "id": path.stem,
            "patch_name": path.stem,
            "target_file": str(path),
            "found": True,
            "status": status,
            "detail": f"Text report: {path.name}",
            "report_present": True,
            "raw_report_path": str(path),
        }],
    }


def _collect_mod_reports(reports_dir: Path) -> tuple[list[dict], list[str], list[str]]:
    """Collect all mod reports. Returns (reports, loaded_names, missing_names)."""
    collected: list[dict] = []
    seen: set[str] = set()
    skip = {"deadzone_full_mod_report.json"}

    # 1. *_mod_report.json (style_mod_runner output)
    for json_path in sorted(reports_dir.glob("*_mod_report.json")):
        if json_path.name in skip:
            continue
        seen.add(json_path.name)
        _load_json_report(json_path, collected)

    # 2. Extra known JSON reports
    missing: list[str] = []
    for name in _EXTRA_JSON_REPORTS:
        if name in seen:
            continue
        p = reports_dir / name
        if p.is_file():
            _load_json_report(p, collected)
            seen.add(name)
        else:
            missing.append(name)

    # 3. Text-only reports
    for name in _TEXT_ONLY_REPORTS:
        p = reports_dir / name
        if p.is_file():
            collected.append(_parse_text_report(p))
            seen.add(name)
        else:
            missing.append(name)

    # 4. final_zip_summary.json (packaging entry)
    fzs = reports_dir / "final_zip_summary.json"
    if fzs.is_file() and fzs.name not in seen:
        _load_json_report(fzs, collected)
        seen.add(fzs.name)
    elif not fzs.is_file():
        missing.append(fzs.name)

    loaded = sorted(seen)
    return collected, loaded, missing


# ── Result iteration ──────────────────────────────────────────────────────────

def _iter_all_results(mod_report: dict) -> list[dict]:
    """Yield all result entries from a mod report (handles all known schemas)."""
    # Flat results list (poco_launcher_spoof, text-only synthetic)
    if "results" in mod_report:
        return list(mod_report["results"])
    # Nested patches format (deadzone_patch_report, lite_apk_patches_report)
    if "patches" in mod_report:
        all_r: list[dict] = []
        for patch_data in mod_report["patches"].values():
            if isinstance(patch_data, dict):
                all_r.extend(patch_data.get("results", []))
        return all_r
    # Style_mod_runner format: top-level "mods" list
    if "mods" in mod_report:
        return list(mod_report["mods"])
    return []


# ── Status normalization ───────────────────────────────────────────────────────

_CHANGED_STATUSES  = frozenset({"changed", "applied", "success"})
_SKIPPED_STATUSES  = frozenset({"skipped", "skipped_not_found", "skipped_not_target_rom",
                                  "skipped_no_match", "skipped_already_applied",
                                  "skipped_unsafe", "skipped_unsafe_try_range"})
_FAILED_STATUSES   = frozenset({"failed", "failed_optional", "failed_fatal"})

_NORMALIZED_DISPLAY: dict[str, str] = {
    "changed":                    "CHANGED",
    "applied":                    "APPLIED",
    "success":                    "SUCCESS",
    "skipped":                    "SKIPPED",
    "skipped_not_found":          "SKIPPED_NOT_FOUND",
    "skipped_not_target_rom":     "SKIPPED_NOT_TARGET_ROM",
    "skipped_no_match":           "SKIPPED_NO_MATCH",
    "skipped_already_applied":    "SKIPPED_ALREADY_APPLIED",
    "skipped_unsafe":             "SKIPPED_UNSAFE",
    "skipped_unsafe_try_range":   "SKIPPED_UNSAFE",
    "failed":                     "FAILED",
    "failed_optional":            "FAILED_OPTIONAL",
    "failed_fatal":               "FAILED_FATAL",
}


def _normalize_status(status: str) -> str:
    return _NORMALIZED_DISPLAY.get(status.lower(), status.upper())


def _classify_status(status: str, detail: str = "") -> str:
    s = status.lower()
    if "applied via group" in detail.lower():
        return "applied_via_group"
    if s in _CHANGED_STATUSES:
        return "changed"
    if s in _FAILED_STATUSES:
        return "failed"
    return "skipped"


# ── Totals ────────────────────────────────────────────────────────────────────

def _is_restore_applicable(entry: dict) -> bool:
    """True only for entries that represent a restorable file (APK/JAR/prop).

    Individual smali-class or strings.xml patch entries lack original_path and
    should not be counted as restore failures — they are internal sub-entries,
    not final build artifacts.
    """
    return bool(entry.get("original_path") or entry.get("restored_path"))


def _summarize_results(mod_reports: list[dict]) -> dict[str, Any]:
    totals: dict[str, int] = {
        "changed": 0, "skipped": 0, "skipped_not_found": 0,
        "failed": 0, "failed_optional": 0, "failed_fatal": 0,
        "applied_via_group": 0,
        "restore_success": 0, "restore_failed": 0, "restore_not_applicable": 0,
        "total": 0,
    }
    for report in mod_reports:
        if report.get("_error"):
            continue
        for r in _iter_all_results(report):
            status = str(r.get("status", ""))
            detail = str(r.get("detail", ""))
            totals["total"] += 1
            cat = _classify_status(status, detail)
            totals[cat] = totals.get(cat, 0) + 1
            s = status.lower()
            if s == "skipped_not_found":
                totals["skipped_not_found"] += 1
            if s == "failed_optional":
                totals["failed_optional"] += 1
            if s == "failed_fatal":
                totals["failed_fatal"] += 1

            # Restore totals — count only entries that represent restorable files.
            # Individual smali-class and strings.xml entries have no original_path
            # and must not inflate the failure count.
            if _is_restore_applicable(r):
                rip = r.get("restore_in_place")
                if rip is True:
                    totals["restore_success"] += 1
                elif rip is False and cat in ("changed", "failed"):
                    totals["restore_failed"] += 1
            else:
                totals["restore_not_applicable"] += 1
    return totals


# ── Text report ───────────────────────────────────────────────────────────────

_STATUS_MARKS: dict[str, str] = {
    "changed":                "[OK]      ",
    "applied":                "[OK]      ",
    "success":                "[OK]      ",
    "applied_via_group":      "[GROUP]   ",
    "skipped":                "[SKIP]    ",
    "skipped_not_found":      "[SKIP_NF] ",
    "skipped_not_target_rom": "[SKIP_ROM]",
    "failed":                 "[FAIL]    ",
    "failed_optional":        "[FAIL_OPT]",
    "failed_fatal":           "[FAIL_FAT]",
}

_GROUP_ORDER = [
    "Framework/JAR",
    "APK/App",
    "Device props",
    "Toolbox",
    "Legacy OS mods",
    "Packaging",
    "Other",
]


def _format_txt(
    dz_style: str,
    mod_reports: list[dict],
    totals: dict[str, Any],
    final_zip: str,
    loaded: list[str] | None = None,
    missing: list[str] | None = None,
    pixeldrain_url: str = "",
) -> str:
    loaded = loaded or []
    missing = missing or []
    restore_ok   = totals.get("restore_success", 0)
    restore_fail = totals.get("restore_failed", 0)
    restore_na   = totals.get("restore_not_applicable", 0)
    restore_line = f"{restore_ok} OK / {restore_fail} FAIL"
    if restore_na:
        restore_line += f" ({restore_na} not applicable — class/string sub-entries)"
    lines = [
        "DeadZone Full Mod Report",
        "=" * 60,
        f"Generated     : {_ts()}",
        f"DZ_STYLE      : {dz_style}",
        f"Final ZIP     : {final_zip or '(not built yet)'}",
    ]
    if pixeldrain_url:
        lines.append(f"PixelDrain    : {pixeldrain_url}")
    lines += [
        "",
        "Summary:",
        f"  Applied/Changed/Success : {totals['changed']}",
        f"  Skipped                 : {totals['skipped']} (not_found: {totals.get('skipped_not_found', 0)})",
        f"  Failed Optional         : {totals.get('failed_optional', 0)}",
        f"  Failed Fatal            : {totals.get('failed_fatal', 0)}",
        f"  Total                   : {totals['total']}",
        f"  Restore in place        : {restore_line}",
        "",
        f"Reports loaded  : {', '.join(loaded) if loaded else '(none)'}",
        f"Reports missing : {', '.join(missing) if missing else '(none)'}",
        "",
    ]

    # Collect all entries keyed by group
    groups: dict[str, list[tuple[dict, str]]] = {g: [] for g in _GROUP_ORDER}

    for report in mod_reports:
        src = report.get("_source_file", "unknown")
        if report.get("_error"):
            lines += [f"[REPORT ERROR] {src}", f"  {report['_error']}", ""]
            continue
        for r in _iter_all_results(report):
            group = _assign_group(r, src)
            if group not in groups:
                groups[group] = []
            groups[group].append((r, src))

    # Print grouped sections
    for group in _GROUP_ORDER:
        entries = groups.get(group, [])
        if not entries:
            continue
        lines.append(f"{group}:")
        for r, src in entries:
            status = r.get("status", "?")
            detail = r.get("detail", "") or r.get("reason", "")
            err = r.get("error", "")
            target = r.get("target_file", r.get("patch", "?"))
            mod_id = r.get("mod", r.get("id", r.get("patch_name", "")))
            cat = _classify_status(status, detail)
            mark = _STATUS_MARKS.get(status.lower(), _STATUS_MARKS.get(cat, "  [???]    "))

            summary = detail or err or target
            if len(summary) > 100:
                summary = summary[:97] + "..."

            lines.append(f"  {mark} {mod_id or target}")
            if summary:
                lines.append(f"           {summary}")

            rip = r.get("restore_in_place")
            if rip is not None:
                rip_tag = "YES" if rip else "NO "
                restored = r.get("restored_path") or r.get("rebuilt_path") or ""
                perm = r.get("permission") or ""
                lines.append(f"           restore_in_place={rip_tag}  path={restored}  perm={perm}")

            searched = r.get("searched_paths", [])
            if searched and status in ("skipped_not_found", "failed_optional", "failed"):
                for sp in searched[:5]:
                    lines.append(f"             - {sp}")
                if len(searched) > 5:
                    lines.append(f"             ... ({len(searched) - 5} more)")
        lines.append("")

    return "\n".join(lines)


# ── Build / write ─────────────────────────────────────────────────────────────

def build_full_report(
    reports_dir: Path,
    dz_style: str = "",
    final_zip: str = "",
    pixeldrain_url: str = "",
) -> dict[str, Any]:
    reports_dir = Path(reports_dir)
    mod_reports, loaded, missing = _collect_mod_reports(reports_dir)
    totals = _summarize_results(mod_reports)

    # Auto-load final_zip from final_zip_summary.json if not explicitly provided
    if not final_zip:
        fzs = reports_dir / "final_zip_summary.json"
        if fzs.is_file():
            try:
                s = json.loads(fzs.read_text(encoding="utf-8"))
                final_zip = s.get("final_zip_name", "")
            except Exception:
                pass

    # Auto-load pixeldrain_url from pixeldrain_upload_report.json
    if not pixeldrain_url:
        pd_report = reports_dir / "pixeldrain_upload_report.json"
        if pd_report.is_file():
            try:
                s = json.loads(pd_report.read_text(encoding="utf-8"))
                pixeldrain_url = s.get("url", "")
            except Exception:
                pass

    full: dict[str, Any] = {
        "generated":       _ts(),
        "dz_style":        dz_style or os.environ.get("DZ_STYLE", ""),
        "final_zip":       final_zip,
        "pixeldrain_url":  pixeldrain_url,
        "totals":          totals,
        "reports_loaded":  loaded,
        "reports_missing": missing,
        "mod_reports":     mod_reports,
    }
    return full


def write_full_report(
    reports_dir: Path,
    dz_style: str = "",
    final_zip: str = "",
    pixeldrain_url: str = "",
    output_name: str = "deadzone_full_mod_report",
) -> None:
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    full = build_full_report(
        reports_dir, dz_style=dz_style, final_zip=final_zip, pixeldrain_url=pixeldrain_url
    )

    txt = _format_txt(
        dz_style=full["dz_style"],
        mod_reports=full["mod_reports"],
        totals=full["totals"],
        final_zip=full["final_zip"],
        loaded=full["reports_loaded"],
        missing=full["reports_missing"],
        pixeldrain_url=full.get("pixeldrain_url", ""),
    )

    txt_path  = reports_dir / f"{output_name}.txt"
    json_path = reports_dir / f"{output_name}.json"

    txt_path.write_text(txt, encoding="utf-8")
    json_path.write_text(json.dumps(full, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[FULL_REPORT] TXT  → {txt_path}")
    print(f"[FULL_REPORT] JSON → {json_path}")
    t = full["totals"]
    print(
        f"[FULL_REPORT] Totals: changed={t['changed']}  "
        f"skipped={t['skipped']} (nf={t.get('skipped_not_found', 0)})  "
        f"failed={t['failed']} (opt={t.get('failed_optional', 0)})  "
        f"total={t['total']}"
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="DeadZone Full Mod Report aggregator")
    ap.add_argument("--work-dir", default=None,
                    help="Project root. Defaults to repo root.")
    ap.add_argument("--style", default=None,
                    help="DZ style (lite/plus/legend/ninja). Overrides DZ_STYLE env var.")
    args = ap.parse_args()

    work_dir = Path(args.work_dir).resolve() if args.work_dir else PROJECT_ROOT
    rdir = work_dir / "bin" / "output" / "reports"
    style = args.style or os.environ.get("DZ_STYLE", "")

    # final_zip and pixeldrain_url are auto-loaded inside write_full_report
    write_full_report(rdir, dz_style=style)
    sys.exit(0)
