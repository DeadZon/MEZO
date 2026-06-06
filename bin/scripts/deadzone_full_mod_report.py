#!/usr/bin/env python3
"""DeadZone Full Mod Report — unified aggregation of all per-mod JSON reports.

Reads all *_mod_report.json files from bin/output/reports/, merges them into a
single structured document, and writes:
  bin/output/reports/deadzone_full_mod_report.txt
  bin/output/reports/deadzone_full_mod_report.json

CLI:
  python3 bin/scripts/deadzone_full_mod_report.py [--work-dir <path>]
"""
from __future__ import annotations

import argparse
import json
import os
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


def _collect_mod_reports(reports_dir: Path) -> list[dict[str, Any]]:
    """Collect all *_mod_report.json files (excluding the full report itself)."""
    collected: list[dict[str, Any]] = []
    skip = {"deadzone_full_mod_report.json"}
    for json_path in sorted(reports_dir.glob("*_mod_report.json")):
        if json_path.name in skip:
            continue
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            data["_source_file"] = json_path.name
            collected.append(data)
        except Exception as exc:
            collected.append({
                "_source_file": json_path.name,
                "_error": f"Failed to parse: {exc}",
            })
    return collected


_CHANGED_STATUSES  = frozenset({"changed", "applied", "success"})
_SKIPPED_STATUSES  = frozenset({"skipped", "skipped_not_found", "skipped_not_target_rom"})
_FAILED_STATUSES   = frozenset({"failed", "failed_optional", "failed_fatal"})


def _classify_status(status: str, detail: str = "") -> str:
    """Map any status string to a canonical category."""
    s = status.lower()
    if "applied via group" in detail.lower():
        return "applied_via_group"
    if s in _CHANGED_STATUSES:
        return "changed"
    if s in _FAILED_STATUSES:
        return "failed"
    return "skipped"


def _iter_all_results(mod_report: dict) -> list[dict]:
    """Yield all result entries from a mod report (handles flat and nested formats)."""
    # Flat: report has top-level "results" list
    if "results" in mod_report:
        return list(mod_report["results"])
    # Nested: lite_apk_patches_report has "patches" → {patch_name: {results: [...]}}
    if "patches" in mod_report:
        all_r: list[dict] = []
        for patch_data in mod_report["patches"].values():
            all_r.extend(patch_data.get("results", []))
        return all_r
    return []


def _summarize_results(mod_reports: list[dict]) -> dict[str, Any]:
    """Count across all mod result entries."""
    totals = {
        "changed": 0,
        "skipped": 0,
        "skipped_not_found": 0,
        "failed": 0,
        "failed_optional": 0,
        "applied_via_group": 0,
        "total": 0,
    }
    for report in mod_reports:
        for r in _iter_all_results(report):
            status = r.get("status", "")
            detail = r.get("detail", "")
            totals["total"] += 1
            cat = _classify_status(status, detail)
            totals[cat] += 1
            if status == "skipped_not_found":
                totals["skipped_not_found"] += 1
            if status == "failed_optional":
                totals["failed_optional"] += 1
    return totals


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


def _format_txt(
    dz_style: str,
    mod_reports: list[dict],
    totals: dict[str, Any],
    final_zip: str,
) -> str:
    lines = [
        "DeadZone Full Mod Report",
        "=" * 50,
        f"Generated     : {_ts()}",
        f"DZ_STYLE      : {dz_style}",
        f"Final ZIP     : {final_zip or '(not built yet)'}",
        "",
        f"Totals — changed: {totals['changed']}  "
        f"skipped: {totals['skipped']} (not_found: {totals.get('skipped_not_found', 0)})  "
        f"failed: {totals['failed']} (opt: {totals.get('failed_optional', 0)})  "
        f"via-group: {totals['applied_via_group']}  "
        f"total: {totals['total']}",
        "",
    ]

    for report in mod_reports:
        source = report.get("_source_file", "unknown")
        error = report.get("_error")
        if error:
            lines += [f"[REPORT] {source}", f"  ERROR: {error}", ""]
            continue

        style = report.get("style", "?")
        ts = report.get("generated", "?")

        lines.append(f"── {source} (style={style}, {ts}) ──")

        for r in _iter_all_results(report):
            status   = r.get("status", "?")
            detail   = r.get("detail", "")
            target   = r.get("target_file", r.get("patch", "?"))
            mod_id   = r.get("mod", r.get("id", r.get("patch_name", "")))
            err      = r.get("error", "")
            searched = r.get("searched_paths", [])

            cat = _classify_status(status, detail)
            mark = _STATUS_MARKS.get(status.lower(), _STATUS_MARKS.get(cat, "  [???]    "))

            summary = detail or err or target
            if len(summary) > 120:
                summary = summary[:117] + "..."

            lines.append(f"  {mark} {mod_id or target} — {summary}")

            # Show searched paths for missing/not-found entries
            if searched and status in ("skipped_not_found", "failed_optional", "failed"):
                lines.append(f"    Searched paths ({len(searched)}):")
                for sp in searched[:8]:
                    lines.append(f"      - {sp}")
                if len(searched) > 8:
                    lines.append(f"      ... ({len(searched) - 8} more)")

        lines.append("")

    return "\n".join(lines)


def build_full_report(
    reports_dir: Path,
    dz_style: str = "",
    final_zip: str = "",
) -> dict[str, Any]:
    mod_reports = _collect_mod_reports(reports_dir)
    totals = _summarize_results(mod_reports)

    full: dict[str, Any] = {
        "generated":   _ts(),
        "dz_style":    dz_style or os.environ.get("DZ_STYLE", "plus"),
        "final_zip":   final_zip,
        "totals":      totals,
        "mod_reports": mod_reports,
    }
    return full


def write_full_report(
    reports_dir: Path,
    dz_style: str = "",
    final_zip: str = "",
) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    full = build_full_report(reports_dir, dz_style=dz_style, final_zip=final_zip)

    txt = _format_txt(
        dz_style=full["dz_style"],
        mod_reports=full["mod_reports"],
        totals=full["totals"],
        final_zip=full["final_zip"],
    )

    txt_path  = reports_dir / "deadzone_full_mod_report.txt"
    json_path = reports_dir / "deadzone_full_mod_report.json"

    txt_path.write_text(txt, encoding="utf-8")
    json_path.write_text(json.dumps(full, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[FULL_REPORT] TXT  → {txt_path}")
    print(f"[FULL_REPORT] JSON → {json_path}")
    t = full["totals"]
    print(f"[FULL_REPORT] Totals: changed={t['changed']}  "
          f"skipped={t['skipped']} (nf={t.get('skipped_not_found', 0)})  "
          f"failed={t['failed']} (opt={t.get('failed_optional', 0)})  "
          f"total={t['total']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="DeadZone Full Mod Report aggregator")
    ap.add_argument("--work-dir", default=None,
                    help="Project root. Defaults to repo root.")
    args = ap.parse_args()

    work_dir = Path(args.work_dir).resolve() if args.work_dir else PROJECT_ROOT
    rdir = work_dir / "bin" / "output" / "reports"
    style = os.environ.get("DZ_STYLE", "plus")

    final_zip_summary = rdir / "final_zip_summary.json"
    final_zip = ""
    if final_zip_summary.is_file():
        try:
            s = json.loads(final_zip_summary.read_text(encoding="utf-8"))
            final_zip = s.get("final_zip_name", "")
        except Exception:
            pass

    write_full_report(rdir, dz_style=style, final_zip=final_zip)
    sys.exit(0)
