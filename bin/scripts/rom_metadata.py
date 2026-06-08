#!/usr/bin/env python3
"""Shared ROM metadata parser for DeadZone MEZO.

Extracts OS label, region code, and human-readable region display from:
  - ROM version strings (OS3.0.305.0.WFSCNXM → OS3, China/CN)
  - device_type.txt values (China, IDGlobal, etc.)

Public API:
  parse_rom_version(rom_version) -> dict with: os, region_code, region_display
  get_region_from_device_type(device_type) -> str display name
  get_region_display(raw_region) -> "China / CN", "Indonesia / IDGlobal", etc.
"""
from __future__ import annotations

import re

# ── Suffix → (code, display) ──────────────────────────────────────────────────
# Format: OS3.x.x.x.[3-char-model][2-char-code]XM
_SUFFIX_MAP: dict[str, tuple[str, str]] = {
    "CN": ("CN",  "China / CN"),
    "MI": ("MI",  "Global"),
    "GL": ("GL",  "Global"),
    "EU": ("EU",  "Europe / EEA"),
    "IN": ("IN",  "India"),
    "ID": ("ID",  "Indonesia / IDGlobal"),
    "TW": ("TW",  "Taiwan"),
    "TR": ("TR",  "Turkey"),
    "RU": ("RU",  "Russia"),
    "JP": ("JP",  "Japan"),
    "KR": ("KR",  "Korea"),
}

# ── device_type.txt values → display ─────────────────────────────────────────
_DEVICE_TYPE_MAP: dict[str, str] = {
    "china":      "China / CN",
    "global":     "Global",
    "eeaglobal":  "Europe / EEA",
    "inglobal":   "India",
    "idglobal":   "Indonesia / IDGlobal",
    "ruglobal":   "Russia",
    "jpglobal":   "Japan",
    "twglobal":   "Taiwan",
    "trglobal":   "Turkey",
    "krglobal":   "Korea",
}


def parse_rom_version(rom_version: str) -> dict:
    """Parse a ROM version string and return metadata dict.

    Examples:
      OS3.0.305.0.WFSCNXM  → {os: 'OS3', region_code: 'CN', region_display: 'China / CN'}
      OS3.0.301.0.WNRIDXM   → {os: 'OS3', region_code: 'ID', region_display: 'Indonesia / IDGlobal'}
      OS3.0.303.0.WNOCNXM   → {os: 'OS3', region_code: 'CN', region_display: 'China / CN'}
    """
    result: dict = {
        "os":             "",
        "region_code":    "",
        "region_display": "",
        "raw":            rom_version,
    }

    if not rom_version:
        return result

    # Extract OS prefix: OS3.*, OS2.*, OS1.*, V14.*, V13.*
    if rom_version.upper().startswith("OS3"):
        result["os"] = "OS3"
    elif rom_version.upper().startswith("OS2"):
        result["os"] = "OS2"
    elif rom_version.upper().startswith("OS1"):
        result["os"] = "OS1"
    elif re.match(r"^V\d+", rom_version, re.IGNORECASE):
        result["os"] = "MIUI"

    # Extract 2-char region code from XM suffix
    # Format: ....[model-chars][2-char-code]XM
    m = re.search(r"([A-Z]{2})XM$", rom_version.upper())
    if m:
        code = m.group(1)
        if code in _SUFFIX_MAP:
            result["region_code"], result["region_display"] = _SUFFIX_MAP[code]

    return result


def get_region_from_device_type(device_type: str) -> str:
    """Convert device_type.txt value to display string.

    Examples:
      'China'     → 'China / CN'
      'IDGlobal'  → 'Indonesia / IDGlobal'
      'Global'    → 'Global'
    """
    if not device_type:
        return "Global"
    key = device_type.strip().lower()
    return _DEVICE_TYPE_MAP.get(key, device_type)


def get_region_display(raw_region: str) -> str:
    """Get display name for a region, trying device_type map first.

    Never returns OS version strings (OS3/OS2/OS1) as region.
    """
    if not raw_region:
        return "Global"
    # Reject OS version strings
    upper = raw_region.upper()
    if upper in ("OS1", "OS2", "OS3", "MIUI"):
        return "Global"
    return get_region_from_device_type(raw_region)


if __name__ == "__main__":
    import sys
    tests = [
        ("OS3.0.305.0.WFSCNXM", "OS3", "China / CN"),
        ("OS3.0.301.0.WNRIDXM",  "OS3", "Indonesia / IDGlobal"),
        ("OS3.0.303.0.WNOCNXM",  "OS3", "China / CN"),
        ("OS3.0.304.0.WNRMIXM",  "OS3", "Global"),
    ]
    all_ok = True
    for ver, exp_os, exp_region in tests:
        r = parse_rom_version(ver)
        ok = r["os"] == exp_os and r["region_display"] == exp_region
        status = "OK  " if ok else "FAIL"
        print(f"[{status}] {ver!r:40s} -> os={r['os']!r:6} region={r['region_display']!r}")
        if not ok:
            all_ok = False
            print(f"       expected: os={exp_os!r} region={exp_region!r}")
    sys.exit(0 if all_ok else 1)
