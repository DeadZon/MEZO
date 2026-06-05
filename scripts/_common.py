#!/usr/bin/env python3
"""Shared utilities for DeadZone Auto Stable Builder.

Provides: device resolution, queue/state management, ROM detection helpers.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────

REPO_ROOT    = Path(__file__).resolve().parent.parent
DEVICES_MTK  = REPO_ROOT / "bin" / "devices" / "mtk"
DEVICES_SD   = REPO_ROOT / "bin" / "devices" / "snapdragon"
DDEVICE_DATA = REPO_ROOT / "bin" / "ddevice" / "data" / "devices.json"
QUEUE_FILE   = REPO_ROOT / "output" / "queue" / "auto_build_queue.json"
STATE_FILE   = REPO_ROOT / "output" / "state" / "built_releases.json"
REPORTS_DIR  = REPO_ROOT / "output" / "reports"
LOGS_DIR     = REPO_ROOT / "output" / "logs"

PUBLISH_PAYLOAD = REPORTS_DIR / "publish_payload.json"
PD_REPORT       = REPORTS_DIR / "pixeldrain_upload_report.json"

# ── OS / Region / Style constants ──────────────────────────────────────────────

ALLOWED_REGIONS  = {"China", "Global"}
ALLOWED_OS_TAGS  = {"OS3"}
ALLOWED_STYLE    = "Stable"

REJECT_REGION_KEYWORDS = [
    "eea", "european", " eu ", "eu rom", "eu stable",
    "india", "ind rom", " ind ", "hindi",
    "indonesia", "idn", "indo rom",
]
REJECT_STYLE_KEYWORDS = [
    "beta", "alpha", "developer", "dev build", "dev rom",
    "preview", "rc1", "experimental", "exp rom",
    "legend", "gaming", "epic", "paid",
]

# ── Device helpers ─────────────────────────────────────────────────────────────

def load_supported_codenames() -> set[str]:
    """Return all codenames with a config file in bin/devices/."""
    names: set[str] = set()
    for base in (DEVICES_MTK, DEVICES_SD):
        if base.is_dir():
            for f in base.glob("*.json"):
                names.add(f.stem.lower())
    return names


def get_soc_for_codename(codename: str) -> str:
    """Return 'mtk', 'snapdragon', or 'unknown'."""
    if (DEVICES_MTK / f"{codename}.json").is_file():
        return "mtk"
    if (DEVICES_SD / f"{codename}.json").is_file():
        return "snapdragon"
    return "unknown"


def get_device_display_name(codename: str) -> str:
    """Resolve display_name from device config, falling back to codename."""
    for base in (DEVICES_MTK, DEVICES_SD):
        p = base / f"{codename}.json"
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return data.get("display_name") or codename
            except Exception:
                pass
    # Fallback: check ddevice/data/devices.json
    if DDEVICE_DATA.is_file():
        try:
            mapping = json.loads(DDEVICE_DATA.read_text(encoding="utf-8"))
            if codename in mapping:
                name = mapping[codename]
                # devices.json can be "Name1|Name2" — take first
                return name.split("|")[0].strip()
        except Exception:
            pass
    return codename


# ── Queue / State ──────────────────────────────────────────────────────────────

def load_queue() -> list[dict]:
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not QUEUE_FILE.is_file():
        return []
    try:
        data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_queue(items: list[dict]) -> None:
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(
        json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_state() -> dict:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.is_file():
        return {"built": []}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"built": []}
    except Exception:
        return {"built": []}


def save_state(data: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def make_dedupe_key(codename: str, version: str, region: str, rom_url: str) -> str:
    url_hash = hashlib.sha256(rom_url.encode()).hexdigest()[:12]
    return f"{codename}_{version}_{region}_{url_hash}"


def is_duplicate(codename: str, version: str, region: str, rom_url: str) -> bool:
    state = load_state()
    key = make_dedupe_key(codename, version, region, rom_url)
    return key in state.get("built", [])


def mark_built(item: dict) -> None:
    state = load_state()
    key = make_dedupe_key(
        item["codename"], item["version"], item["region"], item.get("rom_url", "")
    )
    built = state.get("built", [])
    if key not in built:
        built.append(key)
    state["built"] = built

    # Also save full record for audit
    records = state.get("records", [])
    records.append({
        "id":        item.get("id"),
        "codename":  item.get("codename"),
        "version":   item.get("version"),
        "region":    item.get("region"),
        "rom_url":   item.get("rom_url"),
        "key":       key,
        "built_at":  _now_iso(),
    })
    state["records"] = records
    save_state(state)


# ── Detection helpers ──────────────────────────────────────────────────────────

def detect_os3(text: str) -> bool:
    """Return True if the post is about OS3 / HyperOS 3."""
    t = text.lower()
    if "hyperos 3" in t or "hyper os 3" in t or "hyperos3" in t:
        return True
    if re.search(r'#hyperos3\b', t):
        return True
    if re.search(r'\bos3\b', t):
        return True
    if re.search(r'os3\.\d', t):
        return True
    if re.search(r'\bos3\.\d+\.\d+', t):
        return True
    return False


def detect_region(text: str, version: str = "") -> str | None:
    """Return 'China', 'Global', or None (unsupported/unknown)."""
    combined = (text + " " + version).lower()

    # Hard reject first
    for kw in REJECT_REGION_KEYWORDS:
        if kw in combined:
            return None

    # Explicit keywords
    if "global" in combined:
        return "Global"
    if "china" in combined or " cn " in combined or "cn rom" in combined or "cn stable" in combined:
        return "China"

    # Version string region code analysis
    # Pattern: OS3.0.303.0.WNOCNXM — the last segment contains region
    # Format: [3-char model][2-char region]XM  e.g. WNO + CN + XM
    _SUFFIX_REGION: dict[str, str | None] = {
        "CN": "China",
        "MI": "Global",   # MIXM = Global
        "GL": "Global",   # GLXM = Global (legacy)
        "EU": None,       # Europe
        "IN": None,       # India
        "ID": None,       # Indonesia
        "TW": None,       # Taiwan
        "TR": None,       # Turkey
        "RU": None,       # Russia
    }
    v_match = re.search(
        r'os3\.\d+\.\d+\.\d+\.([A-Z0-9]{4,})',
        text + " " + version,
        re.IGNORECASE,
    )
    if v_match:
        code = v_match.group(1).upper()
        if code.endswith("XM") and len(code) >= 4:
            rc = code[-4:-2]
            if rc in _SUFFIX_REGION:
                return _SUFFIX_REGION[rc]
        # Legacy fallbacks for non-standard suffix lengths
        if "EEA" in code or code[3:5] == "EU":
            return None
        if "IND" in code:
            return None
        if "IDN" in code:
            return None
        if "GL" in code or "GLO" in code:
            return "Global"
        if "CN" in code:
            return "China"

    return None  # Unknown / not one of the allowed regions


def detect_stable(text: str) -> bool:
    """Return True only if the ROM appears to be Stable (not Beta/Alpha/etc.)."""
    t = text.lower()
    for kw in REJECT_STYLE_KEYWORDS:
        if kw in t:
            return False
    # Explicit "stable" is a positive signal but not required
    return True


def extract_version(text: str) -> str | None:
    """Extract the HyperOS version string from post text."""
    # Pattern: OS3.x.x.x.REGIONCODE (standard MIUI/HyperOS build number)
    m = re.search(r'(OS3\.\d+\.\d+\.\d+\.[A-Z0-9]+)', text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # Fallback: just OS3.x.x.x without region code
    m = re.search(r'(OS3\.\d+\.\d+\.\d+)', text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return None


def extract_codename(text: str, links: list[str], supported: set[str]) -> str | None:
    """Extract device codename from post text and links."""
    text_lower = text.lower()

    # 1. [codename] brackets (common in TECH_MUKUL posts)
    for m in re.finditer(r'\[([a-z][a-z0-9_]{2,})\]', text_lower):
        c = m.group(1)
        if c in supported:
            return c

    # 2. #codename hashtags
    for m in re.finditer(r'#([a-z][a-z0-9_]{2,})', text_lower):
        c = m.group(1)
        if c in supported:
            return c

    # 3. Codename in ROM download URL filename
    for link in links:
        link_lower = link.lower()
        # e.g., miui_garnet_OS3... or HyperOS_garnet_...
        for m in re.finditer(r'[/_-]([a-z][a-z0-9]{2,})[/_-]', link_lower):
            c = m.group(1)
            if c in supported:
                return c
        # Also scan all parts split by common separators
        for part in re.split(r'[/_\-\.]', link_lower):
            if part in supported:
                return part

    # 4. Standalone word in post text (riskier, check last)
    for m in re.finditer(r'\b([a-z][a-z0-9]{3,})\b', text_lower):
        c = m.group(1)
        if c in supported:
            return c

    return None


def extract_download_urls(links: list[str]) -> list[str]:
    """Filter links to keep only ROM download URLs."""
    rom_domains = [
        "bigota.d.miui.com", "cdnorg.d.miui.com", "aliyuncs.com",
        "bn.d.miui.com", "d.miui.com", "sourceforge.net",
        "huaweicloud.com", "xiaomi.com", "miui.com",
        "github.com", "drive.google.com",
    ]
    rom_exts = (".zip", ".tgz", ".tar.gz", ".img", ".7z")

    result = []
    for link in links:
        ll = link.lower()
        if any(d in ll for d in rom_domains):
            result.append(link)
        elif any(ll.endswith(e) for e in rom_exts):
            result.append(link)
    return result


def detect_rom_type(text: str, url: str = "") -> str:
    """Return 'fastboot' or 'recovery' based on post text and URL."""
    combined = (text + " " + url).lower()
    if "fastboot" in combined:
        return "fastboot"
    return "recovery"


def extract_android_version(text: str, os_tag: str = "OS3") -> str:
    """Return 'A15', 'A16', etc. based on text or OS version."""
    t = text.lower()
    # Explicit mentions
    for ver in [16, 15, 14, 13]:
        if f"android {ver}" in t or f"android{ver}" in t:
            return f"A{ver}"
    # OS3 → typically Android 16
    if "os3" in t or os_tag.startswith("OS3"):
        return "A16"
    # OS2 → typically Android 15
    if "os2" in t:
        return "A15"
    return "A16"  # safe default for OS3


def format_hyperos_version(version: str) -> str:
    """'OS3.0.303.0.WNOCNXM' → 'HyperOS 3.0.303.0'"""
    m = re.match(r'OS(\d+\.\d+\.\d+\.\d+)', version, re.IGNORECASE)
    if m:
        return f"HyperOS {m.group(1)}"
    return f"HyperOS {version}"


def format_os_tag(version: str) -> str:
    """'OS3.0.303.0.WNOCNXM' → 'OS3.0'"""
    m = re.match(r'(OS\d+\.\d+)', version, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return "OS3.0"


def format_publish_date() -> str:
    """Return current date in Africa/Cairo timezone as dd/mm/yyyy."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Africa/Cairo")
        now = datetime.now(tz=tz)
    except Exception:
        # Fallback to UTC+2 (Cairo standard time)
        from datetime import timezone, timedelta
        tz = timezone(timedelta(hours=2))
        now = datetime.now(tz=tz)
    return now.strftime("%d/%m/%Y")


def _now_iso() -> str:
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Africa/Cairo")
    except Exception:
        from datetime import timezone, timedelta
        tz = timezone(timedelta(hours=2))
    return datetime.now(tz=tz).isoformat()


def make_queue_id(codename: str, version: str, region: str) -> str:
    return f"{codename}_{version}_{region}"


def log(keyword: str, msg: str = "", **kwargs) -> None:
    """Emit a structured log line like: [SCAN_STARTED] source=TECH_MUKUL"""
    parts = [f"[{keyword}]"]
    if msg:
        parts.append(msg)
    for k, v in kwargs.items():
        parts.append(f"{k}={v}")
    print(" ".join(parts), flush=True)
