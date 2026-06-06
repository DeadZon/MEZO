"""Tests for DeadZone Auto Stable Builder scripts.

Run from repo root:
  pytest tests/test_auto_stable_builder.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# Ensure bin/scripts/ is importable (bin/tests/../ = bin/, then /scripts = bin/scripts/)
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from _common import (
    detect_os3, detect_region, detect_stable,
    extract_version, extract_codename,
    extract_download_urls, detect_rom_type,
    extract_android_version,
    format_hyperos_version, format_os_tag,
    format_publish_date, make_queue_id, make_dedupe_key,
    load_queue, save_queue, load_state, save_state,
    is_duplicate, mark_built,
    QUEUE_FILE, STATE_FILE,
)
from publish_stable_release import render_post, validate_payload


# ── Helpers ────────────────────────────────────────────────────────────────────

class _TmpFiles:
    """Context manager that temporarily redirects QUEUE_FILE and STATE_FILE."""

    def __init__(self):
        self._tmpdir = None

    def __enter__(self):
        import _common as cm
        self._tmpdir = tempfile.TemporaryDirectory()
        td = Path(self._tmpdir.name)
        (td / "queue").mkdir()
        (td / "state").mkdir()
        self._orig_qf = cm.QUEUE_FILE
        self._orig_sf = cm.STATE_FILE
        cm.QUEUE_FILE = td / "queue" / "auto_build_queue.json"
        cm.STATE_FILE = td / "state" / "built_releases.json"
        return td

    def __exit__(self, *_):
        import _common as cm
        cm.QUEUE_FILE = self._orig_qf
        cm.STATE_FILE = self._orig_sf
        self._tmpdir.cleanup()


# ══════════════════════════════════════════════════════════════════════════════
#  detect_os3
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectOs3:
    def test_hyperos3_explicit(self):
        assert detect_os3("HyperOS 3.0 Stable China")

    def test_os3_tag(self):
        assert detect_os3("Xiaomi 14 #OS3 Stable")

    def test_version_string(self):
        assert detect_os3("Version OS3.0.303.0.WNOCNXM")

    def test_os3_mixed_case(self):
        assert detect_os3("Running os3.0 firmware")

    def test_hyperos3_hashtag_no_space(self):
        assert detect_os3("#HyperOS3 Update Released | #Degas #Taiwan")

    def test_hyperos3_hashtag_with_version(self):
        assert detect_os3("┌ HyperOS 3.1: OS3.0.301.0.WNETWXM")

    def test_hyperos1_rejected(self):
        assert not detect_os3("HyperOS 1.0 Stable China")

    def test_os2_rejected(self):
        assert not detect_os3("OS2.0.5.0.VHBCNXM")

    def test_miui14_rejected(self):
        assert not detect_os3("MIUI 14 Stable India")

    def test_empty(self):
        assert not detect_os3("")


# ══════════════════════════════════════════════════════════════════════════════
#  detect_region
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectRegion:
    def test_china_explicit(self):
        assert detect_region("HyperOS 3 China Stable") == "China"

    def test_cn_keyword(self):
        assert detect_region("CN ROM Stable OS3") == "China"

    def test_global_explicit(self):
        assert detect_region("HyperOS 3 Global Stable") == "Global"

    def test_china_from_version_cn_code(self):
        assert detect_region("ROM update", "OS3.0.5.0.VHBCNXM") == "China"

    def test_global_from_version_gl_code(self):
        assert detect_region("ROM update", "OS3.0.5.0.VHBGLXM") == "Global"

    def test_eu_rejected(self):
        assert detect_region("HyperOS 3 EU ROM") is None

    def test_eea_rejected(self):
        assert detect_region("EEA Stable OS3") is None

    def test_india_rejected(self):
        assert detect_region("India Stable OS3") is None

    def test_indonesia_rejected(self):
        assert detect_region("Indonesia HyperOS 3") is None

    def test_global_from_version_mixm_code(self):
        assert detect_region("ROM update", "OS3.0.304.0.WNRMIXM") == "Global"

    def test_taiwan_from_version_twxm_returns_none(self):
        assert detect_region("ROM update", "OS3.0.301.0.WNETWXM") is None

    def test_europe_from_version_euxm_returns_none(self):
        assert detect_region("ROM update", "OS3.0.6.0.WNPEUXM") is None

    def test_unknown_returns_none(self):
        assert detect_region("Some ROM no region") is None


# ══════════════════════════════════════════════════════════════════════════════
#  detect_stable
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectStable:
    def test_stable_text_accepted(self):
        assert detect_stable("HyperOS 3 China Stable ROM")

    def test_plain_text_accepted(self):
        assert detect_stable("HyperOS 3 China")

    def test_beta_rejected(self):
        assert not detect_stable("HyperOS 3 Beta China")

    def test_alpha_rejected(self):
        assert not detect_stable("Alpha build OS3")

    def test_developer_rejected(self):
        assert not detect_stable("Developer ROM OS3")

    def test_legend_rejected(self):
        assert not detect_stable("Legend style OS3")

    def test_epic_rejected(self):
        assert not detect_stable("EPiC ROM HyperOS 3")

    def test_paid_rejected(self):
        assert not detect_stable("Paid ROM OS3")


# ══════════════════════════════════════════════════════════════════════════════
#  extract_version
# ══════════════════════════════════════════════════════════════════════════════

class TestExtractVersion:
    def test_full_version(self):
        v = extract_version("Version: OS3.0.303.0.WNOCNXM")
        assert v == "OS3.0.303.0.WNOCNXM"

    def test_short_version(self):
        v = extract_version("OS3.0.5.0 ROM available")
        assert v == "OS3.0.5.0"

    def test_case_insensitive(self):
        v = extract_version("os3.0.1.0.ABCDEF")
        assert v and v.upper().startswith("OS3")

    def test_no_version_returns_none(self):
        assert extract_version("Random text") is None


# ══════════════════════════════════════════════════════════════════════════════
#  extract_codename
# ══════════════════════════════════════════════════════════════════════════════

class TestExtractCodename:
    SUPPORTED = {"garnet", "zircon", "marble", "houji", "cupid"}

    def test_bracket_codename(self):
        assert extract_codename("[garnet] ROM", [], self.SUPPORTED) == "garnet"

    def test_hashtag_codename(self):
        assert extract_codename("Update #garnet #OS3", [], self.SUPPORTED) == "garnet"

    def test_url_codename(self):
        links = ["https://bigota.d.miui.com/miui_garnet_OS3.0.tgz"]
        assert extract_codename("Download", links, self.SUPPORTED) == "garnet"

    def test_standalone_word(self):
        assert extract_codename("New ROM for zircon device", [], self.SUPPORTED) == "zircon"

    def test_unsupported_returns_none(self):
        assert extract_codename("Device alioth update", [], self.SUPPORTED) is None

    def test_empty_text_returns_none(self):
        assert extract_codename("", [], self.SUPPORTED) is None


# ══════════════════════════════════════════════════════════════════════════════
#  extract_download_urls
# ══════════════════════════════════════════════════════════════════════════════

class TestExtractDownloadUrls:
    def test_miui_cdn(self):
        links = ["https://bigota.d.miui.com/something.zip"]
        assert extract_download_urls(links) == links

    def test_aliyun(self):
        links = ["https://bkt.aliyuncs.com/rom.tgz"]
        assert extract_download_urls(links) == links

    def test_telegram_link_excluded(self):
        links = ["https://t.me/TECH_MUKUL/1234"]
        assert extract_download_urls(links) == []

    def test_zip_extension(self):
        links = ["https://example.com/rom.zip"]
        assert extract_download_urls(links) == links

    def test_mixed(self):
        links = [
            "https://t.me/TECH_MUKUL/5",
            "https://bigota.d.miui.com/rom.zip",
        ]
        result = extract_download_urls(links)
        assert len(result) == 1
        assert "miui.com" in result[0]


# ══════════════════════════════════════════════════════════════════════════════
#  format helpers
# ══════════════════════════════════════════════════════════════════════════════

class TestFormatHelpers:
    def test_hyperos_version(self):
        assert format_hyperos_version("OS3.0.303.0.WNOCNXM") == "HyperOS 3.0.303.0"

    def test_os_tag(self):
        assert format_os_tag("OS3.0.303.0.WNOCNXM") == "OS3.0"

    def test_android_from_text(self):
        assert extract_android_version("Android 16 support") == "A16"
        assert extract_android_version("Android 15") == "A15"

    def test_android_default_os3(self):
        assert extract_android_version("OS3.0 ROM", "OS3") == "A16"

    def test_publish_date_format(self):
        d = format_publish_date()
        # Must match dd/mm/yyyy
        import re
        assert re.match(r'^\d{2}/\d{2}/\d{4}$', d), f"Bad date format: {d}"

    def test_publish_date_cairo_timezone(self):
        """Date must be generated in Africa/Cairo timezone."""
        try:
            from zoneinfo import ZoneInfo
            from datetime import datetime
            tz = ZoneInfo("Africa/Cairo")
            expected = datetime.now(tz=tz).strftime("%d/%m/%Y")
        except Exception:
            from datetime import datetime, timezone, timedelta
            tz = timezone(timedelta(hours=2))
            expected = datetime.now(tz=tz).strftime("%d/%m/%Y")
        assert format_publish_date() == expected


# ══════════════════════════════════════════════════════════════════════════════
#  Queue dedupe
# ══════════════════════════════════════════════════════════════════════════════

class TestQueueDedupe:
    def test_new_item_not_duplicate(self):
        with _TmpFiles():
            assert not is_duplicate("garnet", "OS3.0.1.0.ABC", "China", "https://x.com/a.zip")

    def test_after_mark_built_is_duplicate(self):
        with _TmpFiles():
            item = {
                "codename": "garnet",
                "version":  "OS3.0.1.0.ABC",
                "region":   "China",
                "rom_url":  "https://x.com/a.zip",
                "id":       "garnet_OS3.0.1.0.ABC_China",
            }
            mark_built(item)
            assert is_duplicate("garnet", "OS3.0.1.0.ABC", "China", "https://x.com/a.zip")

    def test_different_version_not_duplicate(self):
        with _TmpFiles():
            item = {
                "codename": "garnet",
                "version":  "OS3.0.1.0.ABC",
                "region":   "China",
                "rom_url":  "https://x.com/a.zip",
                "id":       "garnet_OS3.0.1.0.ABC_China",
            }
            mark_built(item)
            assert not is_duplicate("garnet", "OS3.0.2.0.XYZ", "China", "https://x.com/b.zip")

    def test_queue_save_load_roundtrip(self):
        with _TmpFiles():
            items = [
                {"id": "a", "status": "queued", "codename": "garnet"},
                {"id": "b", "status": "built",  "codename": "marble"},
            ]
            save_queue(items)
            loaded = load_queue()
            assert len(loaded) == 2
            assert loaded[0]["id"] == "a"


# ══════════════════════════════════════════════════════════════════════════════
#  Publish template
# ══════════════════════════════════════════════════════════════════════════════

SAMPLE_PAYLOAD = {
    "publish":          True,
    "style":            "Stable",
    "source":           "TECH_MUKUL",
    "source_post_url":  "https://t.me/TECH_MUKUL/1234",
    "device_name":      "Redmi Note 13 Pro+ 5G",
    "codename":         "zircon",
    "version":          "OS3.0.303.0.WNOCNXM",
    "hyperos_version":  "HyperOS 3.0.303.0",
    "region":           "China",
    "android":          "A16",
    "android_tag":      "Android16",
    "os_tag":           "OS3.0",
    "publish_date":     "05/06/2026",
    "download_url":     "https://pixeldrain.com/u/xxxx",
    "changelog_url":    "https://t.me/xDeadZone/430",
    "screenshots_url":  "https://t.me/DeadZoneCloud/572",
    "discussion_url":   "https://t.me/DeadZoneDiscussion",
    "image":            "assets/telegram/stable_release.jpg",
    "zip_name":         "DeadZone_v1.1_zircon_OS3.0.303.0.zip",
    "zip_size":         "5.8 GB",
    "sha256":           "abc123",
}


class TestPublishTemplate:
    def test_template_renders(self):
        text = render_post(SAMPLE_PAYLOAD)
        assert "HyperOS 3.0.303.0" in text
        assert "China" in text
        assert "Redmi Note 13 Pro+ 5G" in text
        assert "#zircon" in text
        assert "https://pixeldrain.com/u/xxxx" in text
        assert "05/06/2026" in text
        assert "#OS3" in text
        assert "#HyperOS3" in text
        assert "#Android16" in text
        assert "#DeadZone" in text
        assert "#MEZO" in text
        assert "https://t.me/xDeadZone/430" in text
        assert "https://t.me/DeadZoneCloud/572" in text
        assert "https://t.me/DeadZoneDiscussion" in text

    def test_template_exact_title_line(self):
        text = render_post(SAMPLE_PAYLOAD)
        first_line = text.splitlines()[0]
        assert first_line == "DeadZone v1.1 HyperOS 3.0.303.0 China Stable A16 OS3.0"


# ══════════════════════════════════════════════════════════════════════════════
#  Publisher safety
# ══════════════════════════════════════════════════════════════════════════════

class TestPublisherSafety:
    def _image(self, tmp_path: Path) -> Path:
        p = tmp_path / "stable_release.jpg"
        p.write_bytes(b"\xff\xd8\xff")  # minimal JPEG magic
        return p

    def test_valid_payload_passes(self, tmp_path):
        img = self._image(tmp_path)
        payload = dict(SAMPLE_PAYLOAD, image=str(img))
        ok, reason = validate_payload(payload, img)
        assert ok
        assert reason == ""

    def test_rejects_non_stable(self, tmp_path):
        img = self._image(tmp_path)
        payload = dict(SAMPLE_PAYLOAD, style="Legend", image=str(img))
        ok, reason = validate_payload(payload, img)
        assert not ok
        assert "stable" in reason.lower() or "not_stable" in reason

    def test_rejects_non_os3(self, tmp_path):
        img = self._image(tmp_path)
        payload = dict(SAMPLE_PAYLOAD, os_tag="OS2.0", image=str(img))
        ok, reason = validate_payload(payload, img)
        assert not ok
        assert "os3" in reason.lower() or "not_os3" in reason

    def test_rejects_missing_download_url(self, tmp_path):
        img = self._image(tmp_path)
        payload = dict(SAMPLE_PAYLOAD, download_url="", image=str(img))
        ok, reason = validate_payload(payload, img)
        assert not ok
        assert "download_url" in reason

    def test_rejects_unsupported_region(self, tmp_path):
        img = self._image(tmp_path)
        payload = dict(SAMPLE_PAYLOAD, region="India", image=str(img))
        ok, reason = validate_payload(payload, img)
        assert not ok
        assert "region" in reason.lower()

    def test_rejects_publish_false(self, tmp_path):
        img = self._image(tmp_path)
        payload = dict(SAMPLE_PAYLOAD, publish=False, image=str(img))
        ok, reason = validate_payload(payload, img)
        assert not ok

    def test_rejects_missing_image(self, tmp_path):
        missing = tmp_path / "no_such_file.jpg"
        payload = dict(SAMPLE_PAYLOAD, image=str(missing))
        ok, reason = validate_payload(payload, missing)
        assert not ok
        assert "image" in reason.lower()


# ══════════════════════════════════════════════════════════════════════════════
#  TECH_MUKUL post parser
# ══════════════════════════════════════════════════════════════════════════════

class TestPostParser:
    """Parse detection logic using realistic post text samples."""

    SAMPLE_POST_CN = """
    📱 Redmi Note 13 Pro+ 5G [zircon]

    HyperOS 3 Stable - China

    Version: OS3.0.303.0.WNOCNXM
    Android 16

    Fastboot ROM: https://bigota.d.miui.com/zircon_OS3.0.303.0.zip

    #zircon #OS3 #HyperOS3 #Stable
    """

    SAMPLE_POST_GLOBAL = """
    Xiaomi 14 (aurora) | HyperOS 3 Global Stable
    Version OS3.0.5.0.WNOMIXM
    Recovery ROM: https://bigota.d.miui.com/aurora_OS3.0.5.0.tgz
    #aurora #OS3 #HyperOS3 #Global
    """

    SAMPLE_POST_EU = """
    Redmi K70 Pro [manet] HyperOS 3 EU Stable
    OS3.0.5.0.VHBEAXI
    https://bigota.d.miui.com/eu_manet.zip
    #manet #OS3 #EU
    """

    SAMPLE_POST_BETA = """
    Mi 11 Ultra [cas] HyperOS 3 Beta China
    OS3.0.5.0.VCACNXM_BETA
    https://bigota.d.miui.com/cas_beta.zip
    """

    SAMPLE_POST_OS2 = """
    Redmi Note 12 Turbo [marble] HyperOS 2 China Stable
    OS2.0.5.0.VMACNXM
    https://bigota.d.miui.com/marble.zip
    #marble #OS2
    """

    SUPPORTED = {"garnet", "zircon", "marble", "aurora", "houji", "cupid", "manet"}

    def test_os3_cn_detected(self):
        text = self.SAMPLE_POST_CN
        assert detect_os3(text)
        assert detect_region(text) == "China"
        assert detect_stable(text)
        assert extract_version(text) == "OS3.0.303.0.WNOCNXM"
        assert extract_codename(text, [], self.SUPPORTED) == "zircon"

    def test_os3_global_detected(self):
        text = self.SAMPLE_POST_GLOBAL
        assert detect_os3(text)
        assert detect_region(text) == "Global"
        assert extract_codename(text, [], self.SUPPORTED) == "aurora"

    def test_eu_region_rejected(self):
        text = self.SAMPLE_POST_EU
        assert detect_region(text) is None

    def test_beta_rejected(self):
        text = self.SAMPLE_POST_BETA
        assert not detect_stable(text)

    def test_os2_rejected(self):
        text = self.SAMPLE_POST_OS2
        assert not detect_os3(text)

    def test_fastboot_url_preferred(self):
        links = [
            "https://bigota.d.miui.com/recovery_zircon.tgz",
            "https://bigota.d.miui.com/fastboot_zircon.zip",
        ]
        assert detect_rom_type("", links[1]) == "fastboot"
        assert detect_rom_type("", links[0]) == "recovery"


# ══════════════════════════════════════════════════════════════════════════════
#  TECH_MUKUL title parser (scan_tech_mukul.py helpers)
# ══════════════════════════════════════════════════════════════════════════════

class TestTechMukulTitleParser:
    """Tests for _extract_post_after_pipe and _get_raw_region."""

    def setup_method(self):
        from scan_tech_mukul import (
            _extract_post_after_pipe,
            _get_raw_region,
            _resolve_codename,
        )
        self._pipe   = _extract_post_after_pipe
        self._region = _get_raw_region
        self._codename = _resolve_codename

    SUPPORTED = {"degas", "garnet", "zircon", "marble", "aurora"}

    # ── _extract_post_after_pipe ──────────────────────────────────────────────

    def test_pipe_format_codename_and_region(self):
        title = "#Xiaomi14T #HyperOS3 Update Released | #Degas #Taiwan"
        codename, region = self._pipe(title)
        assert codename == "degas"
        assert region   == "taiwan"

    def test_pipe_format_china(self):
        title = "#Xiaomi14T #HyperOS3 Update Released | #Degas #China"
        codename, region = self._pipe(title)
        assert codename == "degas"
        assert region   == "china"

    def test_pipe_format_no_region(self):
        title = "Some post | #garnet"
        codename, region = self._pipe(title)
        assert codename == "garnet"
        assert region is None

    def test_no_pipe_returns_none(self):
        codename, region = self._pipe("No pipe here #degas")
        assert codename is None
        assert region   is None

    # ── _get_raw_region ───────────────────────────────────────────────────────

    def test_raw_region_taiwan_from_version(self):
        assert self._region("some text", "OS3.0.301.0.WNETWXM") == "Taiwan"

    def test_raw_region_china_from_version(self):
        assert self._region("some text", "OS3.0.303.0.WNOCNXM") == "China"

    def test_raw_region_global_from_mixm(self):
        assert self._region("some text", "OS3.0.304.0.WNRMIXM") == "Global"

    def test_raw_region_europe_from_euxm(self):
        assert self._region("some text", "OS3.0.6.0.WNPEUXM") == "Europe"

    def test_raw_region_taiwan_from_hashtag(self):
        title = "#Xiaomi14T #HyperOS3 Update Released | #Degas #Taiwan"
        assert self._region(title) == "Taiwan"

    def test_raw_region_china_from_hashtag(self):
        title = "#Xiaomi14T #HyperOS3 Update Released | #Degas #China"
        assert self._region(title) == "China"

    # ── _resolve_codename ─────────────────────────────────────────────────────

    def test_resolve_codename_from_pipe(self):
        title = "#Xiaomi14T #HyperOS3 Update Released | #Degas #Taiwan"
        assert self._codename(title, [], self.SUPPORTED) == "degas"

    def test_resolve_codename_fallback_to_hashtag(self):
        text = "#garnet HyperOS 3 China Stable OS3.0.303.0.WNOCNXM"
        assert self._codename(text, [], self.SUPPORTED) == "garnet"

    def test_resolve_codename_not_supported_returns_none(self):
        title = "#Xiaomi14T #HyperOS3 Update Released | #UnknownDevice #China"
        assert self._codename(title, [], self.SUPPORTED) is None


# ══════════════════════════════════════════════════════════════════════════════
#  TECH_MUKUL post parsing integration (detect_os3 + detect_region + classify)
# ══════════════════════════════════════════════════════════════════════════════

class TestTechMukulPostParsing:
    """Integration tests using realistic TECH_MUKUL post text."""

    SAMPLE_TITLE_ONLY = (
        "#Xiaomi14T #HyperOS3 Update Released | #Degas #Taiwan"
    )

    SAMPLE_FULL_TAIWAN = (
        "#Xiaomi14T #HyperOS3 Update Released | #Degas #Taiwan\n"
        "┌ HyperOS 3.1: OS3.0.301.0.WNETWXM\n"
        "➤ Recovery ROM https://bigota.d.miui.com/degas_OS3.0.301.0.zip"
    )

    SAMPLE_FULL_CHINA = (
        "#Xiaomi14T #HyperOS3 Update Released | #Degas #China\n"
        "┌ HyperOS 3: OS3.0.303.0.WNOCNXM\n"
        "➤ Fastboot ROM https://bigota.d.miui.com/fastboot_degas_OS3.0.303.0.zip"
    )

    SAMPLE_ROLLOUT = (
        "#Xiaomi14T #HyperOS3 Update Released | #Degas #China\n"
        "★ OS3.0.303.0.WNOCNXM Rollout Started\n"
        "➤ Fastboot ROM https://bigota.d.miui.com/fastboot_degas.zip"
    )

    def test_detect_os3_hashtag_format(self):
        """#HyperOS3 (no space) must be detected as OS3."""
        assert detect_os3(self.SAMPLE_TITLE_ONLY)

    def test_detect_os3_version_line(self):
        assert detect_os3(self.SAMPLE_FULL_TAIWAN)

    def test_extract_version_hyperos_prefix(self):
        v = extract_version(self.SAMPLE_FULL_TAIWAN)
        assert v == "OS3.0.301.0.WNETWXM"

    def test_extract_version_star_format(self):
        v = extract_version(self.SAMPLE_ROLLOUT)
        assert v == "OS3.0.303.0.WNOCNXM"

    def test_region_taiwan_from_version_rejected(self):
        """Taiwan region must not be accepted (returns None from detect_region)."""
        v = extract_version(self.SAMPLE_FULL_TAIWAN) or ""
        assert detect_region(self.SAMPLE_FULL_TAIWAN, v) is None

    def test_region_china_from_wnocnxm(self):
        v = extract_version(self.SAMPLE_FULL_CHINA) or ""
        assert detect_region(self.SAMPLE_FULL_CHINA, v) == "China"

    def test_codename_from_pipe(self):
        supported = {"degas", "garnet"}
        from scan_tech_mukul import _resolve_codename
        assert _resolve_codename(self.SAMPLE_FULL_CHINA, [], supported) == "degas"

    def test_taiwan_raw_region_for_logging(self):
        from scan_tech_mukul import _get_raw_region
        v = extract_version(self.SAMPLE_FULL_TAIWAN) or ""
        assert _get_raw_region(self.SAMPLE_FULL_TAIWAN, v) == "Taiwan"

    def test_china_raw_region_for_logging(self):
        from scan_tech_mukul import _get_raw_region
        v = extract_version(self.SAMPLE_FULL_CHINA) or ""
        assert _get_raw_region(self.SAMPLE_FULL_CHINA, v) == "China"


# ══════════════════════════════════════════════════════════════════════════════
#  Region suffix codes  (CNXM / MIXM / TWXM)
# ══════════════════════════════════════════════════════════════════════════════

class TestRegionSuffixCodes:
    """Requirements 4 + 5 + 13: version suffix → region accept/reject."""

    def test_cnxm_accepted_as_china(self):
        assert detect_region("", "OS3.0.303.0.WNOCNXM") == "China"

    def test_mixm_accepted_as_global(self):
        assert detect_region("", "OS3.0.304.0.WNRMIXM") == "Global"

    def test_glxm_accepted_as_global(self):
        assert detect_region("", "OS3.0.5.0.VHBGLXM") == "Global"

    def test_twxm_rejected(self):
        assert detect_region("", "OS3.0.301.0.WNETWXM") is None

    def test_euxm_rejected(self):
        assert detect_region("", "OS3.0.6.0.WNPEUXM") is None

    def test_inxm_rejected(self):
        assert detect_region("", "OS3.0.5.0.VNAINXM") is None

    def test_idxm_rejected(self):
        assert detect_region("", "OS3.0.5.0.VNAIDXM") is None

    def test_ruxm_rejected(self):
        assert detect_region("", "OS3.0.5.0.VNARUXM") is None

    def test_trxm_rejected(self):
        assert detect_region("", "OS3.0.5.0.VNATRXM") is None

    # Req 13 acceptance / skip scenarios
    def test_req13_cnxm_accepted(self):
        """OS3.0.303.0.WNOCNXM → China → accepted."""
        assert detect_region("", "OS3.0.303.0.WNOCNXM") == "China"

    def test_req13_mixm_accepted(self):
        """OS3.0.304.0.WNRMIXM → Global → accepted."""
        assert detect_region("", "OS3.0.304.0.WNRMIXM") == "Global"

    def test_req13_twxm_skipped(self):
        """OS3.0.301.0.WNETWXM → Taiwan → skipped (None)."""
        assert detect_region("", "OS3.0.301.0.WNETWXM") is None

    def test_req13_twxm_raw_region_logged_as_taiwan(self):
        from scan_tech_mukul import _get_raw_region
        assert _get_raw_region("", "OS3.0.301.0.WNETWXM") == "Taiwan"


# ══════════════════════════════════════════════════════════════════════════════
#  classify_post: no_download_links (req 7)
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifyPostNoLinks:
    """Short alert posts (no download links) must return no_download_links."""

    SUPPORTED = {"degas", "garnet", "zircon"}

    def _make_post(self, text: str, links: list[str] | None = None) -> dict:
        return {
            "post_num": 1,
            "post_url": "https://t.me/TECH_MUKUL/1",
            "text": text,
            "text_raw": text,
            "links": links or [],
            "datetime": "",
        }

    def test_title_only_post_no_links(self):
        from scan_tech_mukul import classify_post
        post = self._make_post(
            "#Xiaomi14T #HyperOS3 Update Released | #Degas #China"
        )
        reason, _ = classify_post(post, self.SUPPORTED)
        assert reason == "no_download_links"

    def test_title_only_not_missing_version(self):
        from scan_tech_mukul import classify_post
        post = self._make_post(
            "#Xiaomi14T #HyperOS3 Update Released | #Degas #China"
        )
        reason, _ = classify_post(post, self.SUPPORTED)
        assert reason != "missing_version"
        assert reason != "missing_codename"

    def test_post_with_links_not_no_download(self):
        from scan_tech_mukul import classify_post
        post = self._make_post(
            "#garnet #HyperOS3 Update Released | #garnet #China\n"
            "┌ HyperOS 3: OS3.0.303.0.WNOCNXM\n"
            "➤ Fastboot ROM https://bigota.d.miui.com/fastboot_garnet.zip",
            links=["https://bigota.d.miui.com/fastboot_garnet.zip"],
        )
        reason, _ = classify_post(post, self.SUPPORTED)
        assert reason != "no_download_links"


# ══════════════════════════════════════════════════════════════════════════════
#  Version suffix priority (the core fix for TWXM/RUXM/EUXM/TRXM queued Global)
# ══════════════════════════════════════════════════════════════════════════════

class TestVersionSuffixPriority:
    """Version suffix must override title/hashtag region claims."""

    def test_global_title_with_twxm_suffix_is_rejected(self):
        """#Global in title + TWXM suffix → rejected (Taiwan)."""
        assert detect_region("#Global HyperOS3 Update", "OS3.0.302.0.WOZTWXM") is None

    def test_global_title_with_ruxm_suffix_is_rejected(self):
        assert detect_region("#Global HyperOS3 Update", "OS3.0.302.0.WOZRUXM") is None

    def test_global_title_with_euxm_suffix_is_rejected(self):
        assert detect_region("#Global HyperOS3 Update", "OS3.0.301.0.WMCEUXM") is None

    def test_global_title_with_trxm_suffix_is_rejected(self):
        assert detect_region("#Global HyperOS3 Update", "OS3.0.303.0.WOYTRXM") is None

    def test_china_title_with_mixm_suffix_returns_global(self):
        """Version suffix MIXM overrides 'China' text."""
        assert detect_region("China text", "OS3.0.304.0.WNRMIXM") == "Global"

    def test_known_suffix_never_falls_back_to_text(self):
        """When suffix is known, text keywords are completely ignored."""
        # TWXM suffix → None even though text says "Global China"
        assert detect_region("Global China Stable", "OS3.0.302.0.WOZTWXM") is None

    def test_no_version_falls_back_to_text_global(self):
        """When no version string at all, text 'Global' still works."""
        assert detect_region("HyperOS 3 Global Stable") == "Global"

    def test_no_version_falls_back_to_text_china(self):
        assert detect_region("HyperOS 3 China Stable") == "China"

    def test_unknown_xm_suffix_rejected(self):
        """Unknown XM suffix (e.g. EA) must be rejected — never falls to text."""
        assert detect_region("Global Stable", "OS3.0.5.0.WNOEAXM") is None

    def test_jpxm_rejected(self):
        assert detect_region("", "OS3.0.5.0.VNAJPXM") is None


# ══════════════════════════════════════════════════════════════════════════════
#  extract_version_suffix
# ══════════════════════════════════════════════════════════════════════════════

class TestExtractVersionSuffix:
    from _common import extract_version_suffix as _evs

    def test_cnxm(self):
        from _common import extract_version_suffix
        assert extract_version_suffix("OS3.0.303.0.WNOCNXM") == "CN"

    def test_mixm(self):
        from _common import extract_version_suffix
        assert extract_version_suffix("OS3.0.304.0.WNRMIXM") == "MI"

    def test_twxm(self):
        from _common import extract_version_suffix
        assert extract_version_suffix("OS3.0.302.0.WOZTWXM") == "TW"

    def test_ruxm(self):
        from _common import extract_version_suffix
        assert extract_version_suffix("OS3.0.302.0.WOZRUXM") == "RU"

    def test_euxm(self):
        from _common import extract_version_suffix
        assert extract_version_suffix("OS3.0.301.0.WMCEUXM") == "EU"

    def test_trxm(self):
        from _common import extract_version_suffix
        assert extract_version_suffix("OS3.0.303.0.WOYTRXM") == "TR"

    def test_no_xm_suffix_returns_none(self):
        from _common import extract_version_suffix
        assert extract_version_suffix("OS3.0.5.0") is None

    def test_empty_returns_none(self):
        from _common import extract_version_suffix
        assert extract_version_suffix("") is None


# ══════════════════════════════════════════════════════════════════════════════
#  Req 8: acceptance / rejection matrix
# ══════════════════════════════════════════════════════════════════════════════

class TestReq8AcceptanceMatrix:
    """Verify every acceptance/rejection case from requirement 8."""

    def test_wpbcnxm_accepted_china(self):
        assert detect_region("", "OS3.0.313.0.WPBCNXM") == "China"

    def test_wpamixm_accepted_global(self):
        assert detect_region("", "OS3.0.303.0.WPAMIXM") == "Global"

    def test_wmceuxm_rejected_europe(self):
        assert detect_region("", "OS3.0.301.0.WMCEUXM") is None

    def test_woztwxm_rejected_taiwan(self):
        assert detect_region("", "OS3.0.302.0.WOZTWXM") is None

    def test_wozruxm_rejected_russia(self):
        assert detect_region("", "OS3.0.302.0.WOZRUXM") is None

    def test_woytrxm_rejected_turkey(self):
        assert detect_region("", "OS3.0.303.0.WOYTRXM") is None

    def test_global_title_twxm_suffix_still_rejected(self):
        """Title #Global + TWXM → region must still be rejected."""
        text = "#Xiaomi14T #HyperOS3 Update Released | #Degas #Global"
        assert detect_region(text, "OS3.0.302.0.WOZTWXM") is None


# ══════════════════════════════════════════════════════════════════════════════
#  _classify_region_detail fields  (req 6)
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifyRegionDetail:
    """scan_report fields: source_region, version_region, version_suffix, etc."""

    def setup_method(self):
        from scan_tech_mukul import _classify_region_detail
        self._crd = _classify_region_detail

    def test_twxm_detail(self):
        rd = self._crd(
            "#Xiaomi14T #HyperOS3 Update Released | #Degas #Global",
            "OS3.0.302.0.WOZTWXM",
        )
        assert rd["source_region"]        == "Global"
        assert rd["version_region"]       == "Taiwan"
        assert rd["version_suffix"]       == "TWXM"
        assert rd["final_region"]         is None
        assert rd["region_decision_source"] == "version_suffix"

    def test_cnxm_detail(self):
        rd = self._crd(
            "#Xiaomi14T #HyperOS3 Update Released | #Degas #China",
            "OS3.0.303.0.WNOCNXM",
        )
        assert rd["source_region"]        == "China"
        assert rd["version_region"]       == "China"
        assert rd["version_suffix"]       == "CNXM"
        assert rd["final_region"]         == "China"
        assert rd["region_decision_source"] == "version_suffix"

    def test_mixm_detail(self):
        rd = self._crd(
            "#Xiaomi14T #HyperOS3 Update Released | #Degas #Global",
            "OS3.0.304.0.WNRMIXM",
        )
        assert rd["version_region"]  == "Global"
        assert rd["version_suffix"]  == "MIXM"
        assert rd["final_region"]    == "Global"

    def test_ruxm_source_global_version_russia(self):
        """source_region=Global but version=Russia → final_region rejected."""
        rd = self._crd(
            "Update Released #Global",
            "OS3.0.302.0.WOZRUXM",
        )
        assert rd["source_region"]  == "Global"
        assert rd["version_region"] == "Russia"
        assert rd["version_suffix"] == "RUXM"
        assert rd["final_region"]   is None

    def test_no_version_fallback(self):
        rd = self._crd("HyperOS 3 China Stable", "")
        assert rd["version_suffix"]       is None
        assert rd["region_decision_source"] == "source_text"
        assert rd["final_region"]         == "China"


# ══════════════════════════════════════════════════════════════════════════════
#  build_next_stable.py: validate_item version-suffix guard  (req 9 + 10)
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildValidateVersionSuffix:
    """Queued items with unsupported version suffix must be rejected by builder."""

    SUPPORTED = {"degas", "garnet", "zircon"}

    def _item(self, version: str, region: str, codename: str = "garnet") -> dict:
        return {
            "id":       f"{codename}_{version}_{region}",
            "style":    "Stable",
            "os_tag":   "OS3.0",
            "version":  version,
            "region":   region,
            "codename": codename,
            "rom_url":  "https://bigota.d.miui.com/test.zip",
            "rom_type": "fastboot",
            "status":   "queued",
        }

    def test_cnxm_passes(self):
        from build_next_stable import validate_item
        ok, reason = validate_item(self._item("OS3.0.313.0.WPBCNXM", "China"), self.SUPPORTED)
        assert ok, reason

    def test_mixm_passes(self):
        from build_next_stable import validate_item
        ok, reason = validate_item(self._item("OS3.0.303.0.WPAMIXM", "Global"), self.SUPPORTED)
        assert ok, reason

    def test_twxm_queued_as_global_is_rejected(self):
        """Simulates item queued before fix: region=Global but TWXM suffix."""
        from build_next_stable import validate_item
        ok, reason = validate_item(self._item("OS3.0.302.0.WOZTWXM", "Global"), self.SUPPORTED)
        assert not ok
        assert "unsupported_version_suffix" in reason or "region_suffix_mismatch" in reason

    def test_ruxm_queued_as_global_is_rejected(self):
        from build_next_stable import validate_item
        ok, reason = validate_item(self._item("OS3.0.302.0.WOZRUXM", "Global"), self.SUPPORTED)
        assert not ok

    def test_euxm_queued_as_global_is_rejected(self):
        from build_next_stable import validate_item
        ok, reason = validate_item(self._item("OS3.0.301.0.WMCEUXM", "Global"), self.SUPPORTED)
        assert not ok

    def test_trxm_queued_as_global_is_rejected(self):
        from build_next_stable import validate_item
        ok, reason = validate_item(self._item("OS3.0.303.0.WOYTRXM", "Global"), self.SUPPORTED)
        assert not ok

    def test_cnxm_queued_as_global_mismatch_rejected(self):
        """CNXM (China) queued as Global → mismatch → rejected."""
        from build_next_stable import validate_item
        ok, reason = validate_item(self._item("OS3.0.313.0.WPBCNXM", "Global"), self.SUPPORTED)
        assert not ok
        assert "mismatch" in reason

    def test_mixm_queued_as_china_mismatch_rejected(self):
        """MIXM (Global) queued as China → mismatch → rejected."""
        from build_next_stable import validate_item
        ok, reason = validate_item(self._item("OS3.0.303.0.WPAMIXM", "China"), self.SUPPORTED)
        assert not ok
        assert "mismatch" in reason


# ══════════════════════════════════════════════════════════════════════════════
#  Queue pruning  (prune_queue.py)
# ══════════════════════════════════════════════════════════════════════════════

class TestQueuePruning:
    """prune_queue() removes invalid items; valid ones survive."""

    SUPPORTED = {"garnet", "zircon", "degas", "marble"}

    def _item(
        self,
        version: str,
        region: str,
        codename: str = "garnet",
        status: str = "queued",
    ) -> dict:
        return {
            "id":       f"{codename}_{version}_{region}",
            "style":    "Stable",
            "os_tag":   "OS3.0",
            "version":  version,
            "region":   region,
            "codename": codename,
            "rom_url":  "https://bigota.d.miui.com/test.zip",
            "rom_type": "fastboot",
            "status":   status,
        }

    # ── validate_for_prune unit tests ─────────────────────────────────────────

    def test_cnxm_china_valid(self):
        from prune_queue import validate_for_prune
        ok, reason = validate_for_prune(
            self._item("OS3.0.313.0.WPBCNXM", "China"), self.SUPPORTED
        )
        assert ok, reason

    def test_mixm_global_valid(self):
        from prune_queue import validate_for_prune
        ok, reason = validate_for_prune(
            self._item("OS3.0.303.0.WPAMIXM", "Global"), self.SUPPORTED
        )
        assert ok, reason

    def test_twxm_global_invalid(self):
        from prune_queue import validate_for_prune
        ok, reason = validate_for_prune(
            self._item("OS3.0.302.0.WOZTWXM", "Global"), self.SUPPORTED
        )
        assert not ok
        assert reason in ("unsupported_version_suffix", "region_suffix_mismatch")

    def test_ruxm_global_invalid(self):
        from prune_queue import validate_for_prune
        ok, reason = validate_for_prune(
            self._item("OS3.0.302.0.WOZRUXM", "Global"), self.SUPPORTED
        )
        assert not ok

    def test_euxm_global_invalid(self):
        from prune_queue import validate_for_prune
        ok, reason = validate_for_prune(
            self._item("OS3.0.301.0.WMCEUXM", "Global"), self.SUPPORTED
        )
        assert not ok

    def test_trxm_global_invalid(self):
        from prune_queue import validate_for_prune
        ok, reason = validate_for_prune(
            self._item("OS3.0.303.0.WOYTRXM", "Global"), self.SUPPORTED
        )
        assert not ok

    def test_unsupported_device_invalid(self):
        from prune_queue import validate_for_prune
        ok, reason = validate_for_prune(
            self._item("OS3.0.313.0.WPBCNXM", "China", codename="unknowndevice"),
            self.SUPPORTED,
        )
        assert not ok
        assert reason == "unsupported_device"

    # ── prune_queue integration tests ─────────────────────────────────────────

    def test_prune_removes_invalid_keeps_valid(self):
        from prune_queue import prune_queue

        mixed_queue = [
            self._item("OS3.0.313.0.WPBCNXM", "China"),          # valid — keep
            self._item("OS3.0.303.0.WPAMIXM", "Global"),          # valid — keep
            self._item("OS3.0.302.0.WOZTWXM", "Global"),          # TWXM → remove
            self._item("OS3.0.302.0.WOZRUXM", "Global"),          # RUXM → remove
            self._item("OS3.0.301.0.WMCEUXM", "Global"),          # EUXM → remove
            self._item("OS3.0.303.0.WOYTRXM", "Global"),          # TRXM → remove
            self._item("OS3.0.313.0.WPBCNXM", "China", codename="unknown"),  # bad device → remove
        ]

        with _TmpFiles() as td:
            import _common as cm
            cm.QUEUE_FILE.write_text(
                __import__("json").dumps(mixed_queue, indent=2), encoding="utf-8"
            )
            result = prune_queue(supported=self.SUPPORTED)

        assert result["before"] == 7
        assert result["after"]  == 2
        assert result["removed"] == 5

    def test_prune_count_matches(self):
        from prune_queue import prune_queue

        items = [
            self._item("OS3.0.313.0.WPBCNXM", "China"),   # keep
            self._item("OS3.0.302.0.WOZTWXM", "Global"),  # remove
            self._item("OS3.0.302.0.WOZRUXM", "Global"),  # remove
        ]

        with _TmpFiles() as td:
            import _common as cm
            cm.QUEUE_FILE.write_text(
                __import__("json").dumps(items, indent=2), encoding="utf-8"
            )
            result = prune_queue(supported=self.SUPPORTED)

        assert result["before"] == 3
        assert result["after"]  == 1
        assert result["removed"] == 2

    def test_prune_preserves_built_items(self):
        """Items with status='built' must never be removed regardless of suffix."""
        from prune_queue import prune_queue

        items = [
            self._item("OS3.0.302.0.WOZTWXM", "Global", status="built"),   # keep — already built
            self._item("OS3.0.302.0.WOZRUXM", "Global", status="queued"),  # remove — stale
        ]

        with _TmpFiles() as td:
            import _common as cm
            cm.QUEUE_FILE.write_text(
                __import__("json").dumps(items, indent=2), encoding="utf-8"
            )
            result = prune_queue(supported=self.SUPPORTED)

        assert result["before"]  == 2
        assert result["after"]   == 1
        assert result["removed"] == 1

    def test_prune_preserves_building_items(self):
        """Items with status='building' must never be removed."""
        from prune_queue import prune_queue

        items = [
            self._item("OS3.0.302.0.WOZTWXM", "Global", status="building"),
        ]

        with _TmpFiles() as td:
            import _common as cm
            cm.QUEUE_FILE.write_text(
                __import__("json").dumps(items, indent=2), encoding="utf-8"
            )
            result = prune_queue(supported=self.SUPPORTED)

        assert result["removed"] == 0
        assert result["after"]   == 1

    def test_prune_dry_run_does_not_modify_file(self):
        """dry_run=True must not change the queue file."""
        from prune_queue import prune_queue

        items = [self._item("OS3.0.302.0.WOZTWXM", "Global")]

        with _TmpFiles() as td:
            import _common as cm
            import json
            cm.QUEUE_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")

            result = prune_queue(dry_run=True, supported=self.SUPPORTED)

            # File must still contain the original invalid item
            on_disk = json.loads(cm.QUEUE_FILE.read_text(encoding="utf-8"))

        assert result["removed"] == 1
        assert len(on_disk) == 1   # unchanged on disk

    def test_all_valid_queue_unchanged(self):
        """When every item is valid, removed=0 and queue size is unchanged."""
        from prune_queue import prune_queue

        items = [
            self._item("OS3.0.313.0.WPBCNXM", "China"),
            self._item("OS3.0.303.0.WPAMIXM", "Global"),
        ]

        with _TmpFiles() as td:
            import _common as cm
            cm.QUEUE_FILE.write_text(
                __import__("json").dumps(items, indent=2), encoding="utf-8"
            )
            result = prune_queue(supported=self.SUPPORTED)

        assert result["removed"] == 0
        assert result["before"]  == result["after"] == 2

    def test_empty_queue_no_error(self):
        from prune_queue import prune_queue

        with _TmpFiles():
            import _common as cm
            cm.QUEUE_FILE.write_text("[]", encoding="utf-8")
            result = prune_queue(supported=self.SUPPORTED)

        assert result == {"before": 0, "after": 0, "removed": 0}
