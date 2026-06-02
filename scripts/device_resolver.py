#!/usr/bin/env python3
"""Device and SuperConfig resolver for MEZO ROM Builder.

Searches devices/ and third_party/mezo_core/SuperConfig/ for a codename,
merges the configs, and writes output/reports/device_resolve_report.txt.

Usage:
  device_resolver.py <codename>
  device_resolver.py --from-ddevice     # auto-read from bin/ddevice/
  device_resolver.py --test zircon garnet   # run self-test
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DEVICES_MTK     = Path("devices/mtk")
DEVICES_SD      = Path("devices/snapdragon")
SUPER_CFG_DIR   = Path("third_party/mezo_core/SuperConfig")
DDEVICE_DIR     = Path("bin/ddevice")
REPORTS_DIR     = Path("output/reports")

RESOLVE_REPORT  = REPORTS_DIR / "device_resolve_report.txt"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_file(path: Path) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8", errors="replace").strip()
    return ""


def _load_json(path: Path) -> dict:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[RESOLVER] Warning: could not parse {path}: {exc}", file=sys.stderr)
    return {}


def _find_device_config(codename: str) -> tuple[dict, Path | None]:
    """Search MTK then Snapdragon directories for a matching config file."""
    for base in (DEVICES_MTK, DEVICES_SD):
        candidate = base / f"{codename}.json"
        if candidate.is_file():
            return _load_json(candidate), candidate
        # Fuzzy: any file whose stem starts with codename
        for p in sorted(base.glob(f"{codename}*.json")):
            return _load_json(p), p
    return {}, None


def _load_super_config(codename: str) -> tuple[dict, Path | None]:
    candidate = SUPER_CFG_DIR / f"{codename}.json"
    if candidate.is_file():
        return _load_json(candidate), candidate
    # Fuzzy glob
    for p in sorted(SUPER_CFG_DIR.glob(f"{codename}*.json")):
        return _load_json(p), p
    return {}, None


def _sanitize_super_size(raw: str | int | None, fallback: int) -> int:
    """Parse super size from string/int, returning fallback if invalid."""
    if raw is None:
        return fallback
    try:
        val = int(str(raw).replace("_", "").strip())
        return val if val > 0 else fallback
    except (ValueError, TypeError):
        return fallback


# ── Public API ────────────────────────────────────────────────────────────────

def resolve(codename: str) -> dict:
    """Resolve a codename into a merged device+SuperConfig dict.

    Returned dict keys:
      codename, display_name, brand, soc_family, slot_mode,
      is_ab, partition_group, super_size, metadata_slots, partitions,
      required_images, optional_images,
      device_config_path, super_config_path,
      warnings: list[str]
    """
    warnings: list[str] = []

    # ── Device config ─────────────────────────────────────────────────────────
    dev, dev_path = _find_device_config(codename)
    if not dev:
        warnings.append(f"No device config found for '{codename}' in devices/mtk or devices/snapdragon")

    # ── SuperConfig ───────────────────────────────────────────────────────────
    sc, sc_path = _load_super_config(codename)
    if not sc:
        warnings.append(f"No SuperConfig found for '{codename}' in {SUPER_CFG_DIR}")

    # ── Merge ─────────────────────────────────────────────────────────────────
    soc_family = dev.get("soc_family") or ("mtk" if dev_path and "mtk" in str(dev_path) else "snapdragon")
    slot_mode  = dev.get("slot_mode", "VAB").upper()
    is_ab      = slot_mode == "VAB"

    # Super size: prefer SuperConfig, fall back to ddevice/superSize.txt
    raw_size     = sc.get("super_size") or _read_file(DDEVICE_DIR / "superSize.txt")
    # MTK default: 9126805504 (8.5 GiB); Snapdragon default: 9663676416 (9 GiB)
    default_size = 9126805504 if soc_family == "mtk" else 9663676416
    super_size   = _sanitize_super_size(raw_size, default_size)

    partition_group = sc.get("partition_group", "qti_dynamic_partitions")
    partitions      = sc.get("partitions") or []
    metadata_slots  = int(sc.get("metadata_slots", 3))

    return {
        "codename":         codename,
        "display_name":     dev.get("display_name", codename),
        "brand":            dev.get("brand", "Xiaomi"),
        "soc_family":       soc_family,
        "slot_mode":        slot_mode,
        "is_ab":            is_ab,
        "partition_group":  partition_group,
        "super_size":       super_size,
        "metadata_slots":   metadata_slots,
        "partitions":       partitions,
        "required_images":  dev.get("required_images", ["super.img", "boot.img", "vbmeta.img"]),
        "optional_images":  dev.get("optional_images", ["init_boot.img", "vendor_boot.img", "dtbo.img", "logo.img"]),
        "auto_detect":      sc.get("auto_detect", True),
        "device_config_path": str(dev_path) if dev_path else "(not found)",
        "super_config_path":  str(sc_path)  if sc_path  else "(not found)",
        "warnings":         warnings,
    }


def resolve_from_ddevice() -> dict:
    """Auto-resolve using codename detected by build.sh into bin/ddevice/."""
    codename = (
        _read_file(DDEVICE_DIR / "device_f.txt")
        or _read_file(DDEVICE_DIR / "device_code.txt")
        or ""
    ).strip()
    if not codename:
        raise SystemExit("[RESOLVER] Cannot find codename in bin/ddevice/ — has build.sh run?")
    return resolve(codename)


# ── Report writer ─────────────────────────────────────────────────────────────

def write_report(cfg: dict) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "MEZO Device Resolve Report",
        "=" * 40,
        f"codename:             {cfg['codename']}",
        f"display_name:         {cfg['display_name']}",
        f"brand:                {cfg['brand']}",
        f"soc_family:           {cfg['soc_family']}",
        f"slot_mode:            {cfg['slot_mode']}",
        f"is_ab:                {cfg['is_ab']}",
        f"partition_group:      {cfg['partition_group']}",
        f"super_size:           {cfg['super_size']:,} bytes ({cfg['super_size'] / 1024**3:.2f} GiB)",
        f"metadata_slots:       {cfg['metadata_slots']}",
        f"auto_detect:          {cfg['auto_detect']}",
        f"device_config_path:   {cfg['device_config_path']}",
        f"super_config_path:    {cfg['super_config_path']}",
        "",
        "partitions:",
    ]
    for p in cfg["partitions"]:
        lines.append(f"  {p}")
    lines += [
        "",
        "required_images:",
        *[f"  {i}" for i in cfg["required_images"]],
        "",
        "optional_images:",
        *[f"  {i}" for i in cfg["optional_images"]],
    ]
    if cfg["warnings"]:
        lines += ["", "WARNINGS:"] + [f"  ! {w}" for w in cfg["warnings"]]
    RESOLVE_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[RESOLVER] Report → {RESOLVE_REPORT}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        sys.exit(1)

    if argv[0] == "--from-ddevice":
        cfg = resolve_from_ddevice()
        write_report(cfg)
        if cfg["warnings"]:
            for w in cfg["warnings"]:
                print(f"[RESOLVER] WARNING: {w}", file=sys.stderr)
        print(json.dumps(cfg, indent=2))

    elif argv[0] == "--test":
        targets = argv[1:] or ["zircon", "garnet"]
        ok = True
        for code in targets:
            cfg = resolve(code)
            status = "OK" if not cfg["warnings"] else f"WARN({len(cfg['warnings'])})"
            print(f"  {code:20s}  {status}  super={cfg['super_size']:,}  ab={cfg['is_ab']}  parts={len(cfg['partitions'])}")
            for w in cfg["warnings"]:
                print(f"    ! {w}")
                ok = False
        sys.exit(0 if ok else 1)

    else:
        codename = argv[0]
        cfg = resolve(codename)
        write_report(cfg)
        if cfg["warnings"]:
            for w in cfg["warnings"]:
                print(f"[RESOLVER] WARNING: {w}", file=sys.stderr)
        print(json.dumps(cfg, indent=2))


if __name__ == "__main__":
    main()
