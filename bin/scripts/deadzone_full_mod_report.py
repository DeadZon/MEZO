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


def _summarize_results(mod_reports: list[dict]) -> dict[str, Any]:
    """Count across all mod result entries."""
    totals = {"changed": 0, "skipped": 0, "failed": 0, "applied_via_group": 0, "total": 0}
    for report in mod_reports:
        results = report.get("results", [])
        for r in results:
            status = r.get("status", "")
            detail = r.get("detail", "")
            totals["total"] += 1
            if "applied via group" in detail.lower():
                totals["applied_via_group"] += 1
            elif status == "changed":
                totals["changed"] += 1
            elif status == "failed":
                totals["failed"] += 1
            else:
                totals["skipped"] += 1
    return totals


def _format_txt(
    dz_style: str,
    mod_reports: list[dict],
    totals: dict[str, Any],
    final_zip: str,
) -> str:
    lines = [
        "DeadZone Full Mod Report",
        "=" * 50,
        f"Generated : {_ts()}",
        f"DZ_STYLE  : {dz_style}",
        f"Final ZIP : {final_zip or '(not built yet)'}",
        "",
        f"Totals — changed: {totals['changed']}  skipped: {totals['skipped']}  "
        f"failed: {totals['failed']}  via-group: {totals['applied_via_group']}  "
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
        results = report.get("results", [])

        lines += [
            f"── {source} (style={style}, {ts}) ──",
        ]

        for r in results:
            status   = r.get("status", "?")
            detail   = r.get("detail", "")
            target   = r.get("target_file", r.get("patch", "?"))
            mod_id   = r.get("mod", r.get("id", ""))
            err      = r.get("error", "")

            if "applied via group" in detail.lower():
                mark = "  [GROUP]"
            elif status == "changed":
                mark = "  [OK]   "
            elif status == "failed":
                mark = "  [FAIL] "
            else:
                mark = "  [SKIP] "

            summary = detail or err or target
            if len(summary) > 120:
                summary = summary[:117] + "..."

            lines.append(f"{mark} {mod_id or target} — {summary}")

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
    print(f"[FULL_REPORT] Totals: changed={full['totals']['changed']}  "
          f"skipped={full['totals']['skipped']}  failed={full['totals']['failed']}")


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
