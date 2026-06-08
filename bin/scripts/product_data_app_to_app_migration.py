#!/usr/bin/env python3
"""DeadZone MEZO — Move product/data-app apps into product/app.

Some OEM ROMs ship apps under product/data-app/ (data-app is meant for
user-installed storage, not system partition apps).  Moving them to
product/app/ ensures they are treated as preinstalled system apps,
which avoids permission and signature check issues on clean flash.

Usage:
  python3 bin/scripts/product_data_app_to_app_migration.py \
      --work-dir <root> [--style lite]

Env override:
  ENABLE_PRODUCT_DATA_APP_MIGRATION=false  — skip entirely (default: true)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

WORK_DIR    = Path(__file__).resolve().parent.parent.parent
REPORTS_DIR = WORK_DIR / "bin" / "output" / "reports"

_PRODUCT_BASES = (
    "build/baserom/images/product",
    "product",
)
_SRC_SUBDIR = "data-app"
_DST_SUBDIR = "app"


def _find_product_dir(work_dir: Path) -> Path | None:
    for rel in _PRODUCT_BASES:
        candidate = work_dir / rel
        if candidate.is_dir():
            return candidate
    return None


def run_migration(work_dir: Path) -> dict:
    """Move all items from product/data-app/ into product/app/."""
    results: list[dict] = []

    enabled = os.environ.get("ENABLE_PRODUCT_DATA_APP_MIGRATION", "true").lower()
    if enabled not in ("1", "true", "yes"):
        return {
            "mod":            "product_data_app_to_app_migration",
            "generated":      time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "work_dir":       str(work_dir),
            "overall_status": "disabled",
            "totals":         {"moved": 0, "skipped": 0, "failed": 0},
            "results":        [],
        }

    product_dir = _find_product_dir(work_dir)
    if product_dir is None:
        return {
            "mod":            "product_data_app_to_app_migration",
            "generated":      time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "work_dir":       str(work_dir),
            "overall_status": "skipped",
            "totals":         {"moved": 0, "skipped": 0, "failed": 0},
            "results":        [{"item": "product/", "status": "skipped", "detail": "product/ partition not found"}],
        }

    src_dir = product_dir / _SRC_SUBDIR
    dst_dir = product_dir / _DST_SUBDIR

    if not src_dir.is_dir():
        return {
            "mod":            "product_data_app_to_app_migration",
            "generated":      time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "work_dir":       str(work_dir),
            "overall_status": "skipped",
            "totals":         {"moved": 0, "skipped": 0, "failed": 0},
            "results":        [{"item": str(src_dir), "status": "skipped", "detail": "product/data-app/ not present — nothing to migrate"}],
        }

    dst_dir.mkdir(parents=True, exist_ok=True)

    items = sorted(src_dir.iterdir())
    if not items:
        return {
            "mod":            "product_data_app_to_app_migration",
            "generated":      time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "work_dir":       str(work_dir),
            "overall_status": "skipped",
            "totals":         {"moved": 0, "skipped": 0, "failed": 0},
            "results":        [{"item": str(src_dir), "status": "skipped", "detail": "product/data-app/ is empty"}],
        }

    for item in items:
        dst_item = dst_dir / item.name
        entry: dict = {"item": item.name, "src": str(item), "dst": str(dst_item)}
        if dst_item.exists():
            entry["status"] = "skipped"
            entry["detail"] = f"{item.name} already exists in product/app/ — not overwriting"
            results.append(entry)
            continue
        try:
            shutil.move(str(item), str(dst_item))
            entry["status"] = "moved"
            entry["detail"] = f"product/data-app/{item.name} → product/app/{item.name}"
            results.append(entry)
        except Exception as exc:
            entry["status"] = "failed"
            entry["detail"] = str(exc)
            results.append(entry)

    # Remove src_dir if now empty
    try:
        if src_dir.is_dir() and not any(src_dir.iterdir()):
            src_dir.rmdir()
    except Exception:
        pass

    moved   = sum(1 for r in results if r["status"] == "moved")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    failed  = sum(1 for r in results if r["status"] == "failed")
    overall = "changed" if moved > 0 else ("failed" if failed > 0 else "skipped")

    return {
        "mod":            "product_data_app_to_app_migration",
        "generated":      time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "work_dir":       str(work_dir),
        "overall_status": overall,
        "totals":         {"moved": moved, "skipped": skipped, "failed": failed},
        "results":        results,
    }


def _write_reports(report: dict, reports_dir: Path) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)

    json_path = reports_dir / "product_data_app_migration_report.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    txt_lines = [
        "DeadZone MEZO — product/data-app → product/app Migration Report",
        "=" * 60,
        f"Generated : {report['generated']}",
        f"Work dir  : {report['work_dir']}",
        f"Status    : {report['overall_status'].upper()}",
        "",
        "Totals:",
        f"  Moved   : {report['totals']['moved']}",
        f"  Skipped : {report['totals']['skipped']}",
        f"  Failed  : {report['totals']['failed']}",
        "",
        "Results:",
    ]
    for r in report["results"]:
        tag = {"moved": "[MOVED  ]", "skipped": "[SKIP   ]", "failed": "[FAILED ]"}.get(r["status"], "[???    ]")
        txt_lines.append(f"  {tag} {r['item']} — {r['detail']}")

    (reports_dir / "product_data_app_migration_report.txt").write_text(
        "\n".join(txt_lines) + "\n", encoding="utf-8"
    )
    print(f"[DATA_APP_MIGRATE] Reports written → {json_path.parent}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="product/data-app → product/app migration")
    parser.add_argument("--work-dir", default=str(WORK_DIR), help="Project root directory")
    parser.add_argument("--style",    default="lite",         help="Active build style")
    args = parser.parse_args(argv)

    work_dir    = Path(args.work_dir).resolve()
    reports_dir = work_dir / "bin" / "output" / "reports"

    print(f"[DATA_APP_MIGRATE] Checking product/data-app/ in {work_dir} ...")
    report = run_migration(work_dir)

    status = report["overall_status"]
    moved  = report["totals"]["moved"]
    if status == "changed":
        print(f"[DATA_APP_MIGRATE] Migrated {moved} item(s) from product/data-app/ to product/app/")
    elif status == "disabled":
        print("[DATA_APP_MIGRATE] ENABLE_PRODUCT_DATA_APP_MIGRATION=false — skipped")
    else:
        print(f"[DATA_APP_MIGRATE] {status.upper()} — no items migrated")

    _write_reports(report, reports_dir)
    return 0 if report["totals"]["failed"] == 0 else 1


if __name__ == "__main__":
    # Self-test: dry-run with a temp directory
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prod = root / "build" / "baserom" / "images" / "product"
            (prod / "data-app" / "TestApp.apk").mkdir(parents=True)
            (prod / "app").mkdir(parents=True)
            report = run_migration(root)
            assert report["totals"]["moved"] == 1, f"expected 1 move, got {report['totals']}"
            assert (prod / "app" / "TestApp.apk").is_dir(), "TestApp.apk not in product/app/"
            assert not (prod / "data-app").exists(), "data-app/ should be removed when empty"
            print("[DATA_APP_MIGRATE] Self-test PASSED")
        sys.exit(0)

    sys.exit(main())
