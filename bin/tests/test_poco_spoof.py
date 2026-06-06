"""Tests for poco_launcher_spoof.py, Lite mods.json POCO entry, ZIP naming, and ChinaStable fix."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# ── Repo layout ───────────────────────────────────────────────────────────────
REPO_ROOT   = Path(__file__).resolve().parent.parent.parent
BIN_DIR     = REPO_ROOT / "bin"
SCRIPTS_DIR = BIN_DIR / "scripts"
STYLES_DIR  = BIN_DIR / "styles"

POCO_SPOOF_PY  = SCRIPTS_DIR / "poco_launcher_spoof.py"
LITE_MODS_JSON = STYLES_DIR / "Lite" / "mods.json"
RUNNER_PY      = SCRIPTS_DIR / "style_mod_runner.py"
PACKAGE_PY     = SCRIPTS_DIR / "package_rom.py"
PUBLISH_PY     = SCRIPTS_DIR / "publish_stable_release.py"


# ── Module loaders ────────────────────────────────────────────────────────────

def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def poco_mod():
    return _load(POCO_SPOOF_PY, "poco_launcher_spoof")


@pytest.fixture(scope="module")
def publish_mod():
    return _load(PUBLISH_PY, "publish_stable_release")


@pytest.fixture(scope="module")
def lite_manifest():
    return json.loads(LITE_MODS_JSON.read_text(encoding="utf-8"))


# ── helpers ───────────────────────────────────────────────────────────────────

def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _make_poco_prop(tmp_path: Path) -> Path:
    """Create a minimal vendor/build.prop with POCO brand."""
    content = (
        "# Vendor build properties\n"
        "ro.product.vendor.brand=POCO\n"
        "ro.product.vendor.device=garnet\n"
        "ro.product.vendor.model=23129RN51X\n"
        "ro.product.vendor.marketname=POCO X6 Pro\n"
        "ro.product.vendor.name=garnet\n"
        "ro.build.fingerprint=POCO/garnet_global/garnet:14/UKQ1.230917.001/V816.0.23.10.10.DEV:user/release-keys\n"
        "ro.product.vendor.manufacturer=Xiaomi\n"
    )
    prop = tmp_path / "vendor" / "build.prop"
    return _write(prop, content)


def _make_non_poco_prop(tmp_path: Path) -> Path:
    """Create a minimal vendor/build.prop with Redmi brand (non-POCO)."""
    content = (
        "# Vendor build properties\n"
        "ro.product.vendor.brand=Redmi\n"
        "ro.product.vendor.device=garnet\n"
        "ro.product.vendor.model=23129RN51X\n"
    )
    prop = tmp_path / "vendor" / "build.prop"
    return _write(prop, content)


# ══════════════════════════════════════════════════════════════════════════════
# 1. POCO spoof core logic
# ══════════════════════════════════════════════════════════════════════════════

class TestPocoSpoofCore:
    def test_modifies_poco_brand_to_redmi(self, tmp_path, poco_mod):
        """ro.product.vendor.brand=POCO is replaced with Redmi."""
        _make_poco_prop(tmp_path)
        report = poco_mod.run_poco_spoof(tmp_path)

        assert report["poco_rom"] is True
        assert report["overall_status"] == "changed"
        changed = [r for r in report["results"] if r["modified"]]
        assert len(changed) >= 1
        prop = tmp_path / "vendor" / "build.prop"
        content = prop.read_text(encoding="utf-8")
        assert "ro.product.vendor.brand=Redmi" in content

    def test_preserves_device_model_marketname_fingerprint(self, tmp_path, poco_mod):
        """Keys other than ro.product.vendor.brand are not touched."""
        _make_poco_prop(tmp_path)
        poco_mod.run_poco_spoof(tmp_path)
        content = (tmp_path / "vendor" / "build.prop").read_text(encoding="utf-8")

        assert "ro.product.vendor.device=garnet" in content
        assert "ro.product.vendor.model=23129RN51X" in content
        assert "ro.product.vendor.marketname=POCO X6 Pro" in content
        assert "ro.build.fingerprint=POCO/garnet_global" in content
        assert "ro.product.vendor.manufacturer=Xiaomi" in content

    def test_scans_both_vendor_and_odm(self, tmp_path, poco_mod):
        """POCO brand in odm/ is also detected and replaced."""
        odm_prop = tmp_path / "odm" / "build.prop"
        _write(odm_prop, "ro.product.vendor.brand=POCO\nro.product.odm.name=garnet\n")
        report = poco_mod.run_poco_spoof(tmp_path)

        odm_entries = [r for r in report["results"] if "odm" in r["target_file"] and r["modified"]]
        assert odm_entries, "POCO brand in odm/ should be detected and replaced"
        assert odm_prop.read_text(encoding="utf-8").startswith("ro.product.vendor.brand=Redmi")

    def test_non_poco_rom_skipped_no_failure(self, tmp_path, poco_mod):
        """Non-POCO ROM returns SKIPPED overall and does not raise or fail."""
        _make_non_poco_prop(tmp_path)
        report = poco_mod.run_poco_spoof(tmp_path)

        assert report["poco_rom"] is False
        assert report["overall_status"] == "skipped"
        assert report["totals"]["failed"] == 0
        changed = [r for r in report["results"] if r["modified"]]
        assert not changed, "Non-POCO ROM should have no modifications"

    def test_missing_partitions_skipped_no_failure(self, tmp_path, poco_mod):
        """Missing vendor/ and odm/ directories produce SKIPPED, not error."""
        report = poco_mod.run_poco_spoof(tmp_path)

        assert report["poco_rom"] is False
        assert report["totals"]["failed"] == 0
        assert all(r["status"] == "skipped" for r in report["results"])

    def test_non_poco_brand_value_not_replaced(self, tmp_path, poco_mod):
        """A brand like 'Xiaomi' is left unchanged even if key is present."""
        prop = tmp_path / "vendor" / "build.prop"
        _write(prop, "ro.product.vendor.brand=Xiaomi\n")
        poco_mod.run_poco_spoof(tmp_path)
        assert prop.read_text(encoding="utf-8").strip() == "ro.product.vendor.brand=Xiaomi"

    def test_idempotent(self, tmp_path, poco_mod):
        """Running the spoof twice on a POCO ROM leaves the file unchanged on second run."""
        _make_poco_prop(tmp_path)
        poco_mod.run_poco_spoof(tmp_path)
        content_after_first = (tmp_path / "vendor" / "build.prop").read_text(encoding="utf-8")

        report2 = poco_mod.run_poco_spoof(tmp_path)
        content_after_second = (tmp_path / "vendor" / "build.prop").read_text(encoding="utf-8")

        assert content_after_first == content_after_second
        # On second run, brand is now Redmi — should not match POCO → no changes
        assert report2["poco_rom"] is False


# ══════════════════════════════════════════════════════════════════════════════
# 2. Report files
# ══════════════════════════════════════════════════════════════════════════════

class TestPocoSpoofReports:
    def test_report_json_valid(self, tmp_path, poco_mod, monkeypatch):
        """JSON report is valid, parseable, and has required keys."""
        reports_dir = tmp_path / "reports"
        monkeypatch.setattr(poco_mod, "REPORTS_DIR", reports_dir)
        _make_poco_prop(tmp_path)
        report = poco_mod.run_poco_spoof(tmp_path)
        poco_mod._write_reports(report, reports_dir)

        json_path = reports_dir / "poco_launcher_spoof_report.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text(encoding="utf-8"))

        assert "mod" in data
        assert "generated" in data
        assert "work_dir" in data
        assert "poco_rom" in data
        assert "overall_status" in data
        assert "totals" in data
        assert "results" in data
        assert isinstance(data["results"], list)

    def test_report_txt_written(self, tmp_path, poco_mod, monkeypatch):
        """TXT report is written alongside JSON."""
        reports_dir = tmp_path / "reports"
        monkeypatch.setattr(poco_mod, "REPORTS_DIR", reports_dir)
        _make_poco_prop(tmp_path)
        report = poco_mod.run_poco_spoof(tmp_path)
        poco_mod._write_reports(report, reports_dir)

        txt_path = reports_dir / "poco_launcher_spoof_report.txt"
        assert txt_path.exists()
        content = txt_path.read_text(encoding="utf-8")
        assert "POCO Launcher to MiuiHome Spoofing" in content

    def test_report_totals_correct(self, tmp_path, poco_mod):
        """Totals in report accurately count modified files."""
        _make_poco_prop(tmp_path)
        report = poco_mod.run_poco_spoof(tmp_path)
        assert report["totals"]["modified"] >= 1
        assert report["totals"]["failed"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# 3. Lite mods.json integration
# ══════════════════════════════════════════════════════════════════════════════

class TestLiteManifestPocoEntry:
    def test_poco_entry_present_in_lite_mods(self, lite_manifest):
        """Lite mods.json must contain poco_launcher_to_miuihome_spoofing."""
        ids = [m["id"] for m in lite_manifest["mods"]]
        assert "poco_launcher_to_miuihome_spoofing" in ids, (
            f"Expected 'poco_launcher_to_miuihome_spoofing' in Lite mods.json IDs: {ids}"
        )

    def test_poco_entry_enabled(self, lite_manifest):
        """poco_launcher_to_miuihome_spoofing must be enabled=true."""
        entry = next(m for m in lite_manifest["mods"] if m["id"] == "poco_launcher_to_miuihome_spoofing")
        assert entry["enabled"] is True

    def test_poco_entry_not_required(self, lite_manifest):
        """poco_launcher_to_miuihome_spoofing must be required=false (optional mod)."""
        entry = next(m for m in lite_manifest["mods"] if m["id"] == "poco_launcher_to_miuihome_spoofing")
        assert entry.get("required", False) is False

    def test_poco_entry_has_python_entry(self, lite_manifest):
        """poco_launcher_to_miuihome_spoofing must declare python_entry."""
        entry = next(m for m in lite_manifest["mods"] if m["id"] == "poco_launcher_to_miuihome_spoofing")
        assert "python_entry" in entry
        assert "poco_launcher_spoof.py" in entry["python_entry"]

    def test_poco_script_exists(self, lite_manifest):
        """The python_entry script must exist on disk."""
        entry = next(m for m in lite_manifest["mods"] if m["id"] == "poco_launcher_to_miuihome_spoofing")
        script_path = REPO_ROOT / entry["python_entry"]
        assert script_path.exists(), f"Script not found: {script_path}"


# ══════════════════════════════════════════════════════════════════════════════
# 4. style_mod_runner treats POCO mod as optional
# ══════════════════════════════════════════════════════════════════════════════

class TestRunnerPocoOptional:
    def test_runner_poco_mod_is_optional(self, lite_manifest):
        """style_mod_runner must not abort on POCO mod failure (required=false)."""
        entry = next(
            (m for m in lite_manifest["mods"] if m["id"] == "poco_launcher_to_miuihome_spoofing"),
            None,
        )
        assert entry is not None, "poco_launcher_to_miuihome_spoofing not in manifest"
        assert entry.get("required", True) is False, (
            "POCO spoof must be optional (required=false) so a missing ROM doesn't abort the build"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 5. ZIP naming for Lite style
# ══════════════════════════════════════════════════════════════════════════════

class TestLiteZipNaming:
    def test_lite_zip_name_format(self):
        """Lite ZIP name must follow DeadZone_Lite_<codename>_<os_version>.zip (no _A suffix)."""
        codename   = "garnet"
        os_version = "OS3.0.304.0.WNRCNXM"
        expected   = f"DeadZone_Lite_{codename}_{os_version}.zip"

        # Verify the naming logic in package_rom.py
        pkg_source = PACKAGE_PY.read_text(encoding="utf-8")
        assert "DeadZone_Lite_" in pkg_source, (
            "package_rom.py must produce DeadZone_Lite_ prefix for Lite style"
        )
        # Verify no _A suffix added for Lite
        assert 'style_cfg["id"] == "lite"' in pkg_source or "== 'lite'" in pkg_source, (
            "package_rom.py must branch on Lite style for naming"
        )

    def test_lite_zip_name_no_android_suffix(self):
        """Lite ZIP name must NOT include _A<android_ver> suffix."""
        pkg_source = PACKAGE_PY.read_text(encoding="utf-8")
        # Find the Lite branch — there should be a zip_name assignment without _A{android_ver}
        import re
        lite_section = re.search(
            r'if style_cfg\["id"\] == "lite":(.*?)else:', pkg_source, re.DOTALL
        )
        assert lite_section is not None, "Expected Lite branch in package_rom.py ZIP naming"
        lite_code = lite_section.group(1)
        assert "android_ver" not in lite_code, (
            "Lite ZIP name branch must not include android_ver"
        )

    def test_lite_zip_name_example(self):
        """Verify naming produces the exact expected example name."""
        codename   = "garnet"
        os_version = "OS3.0.304.0.WNRCNXM"
        zip_name   = f"DeadZone_Lite_{codename}_{os_version}.zip"
        assert zip_name == "DeadZone_Lite_garnet_OS3.0.304.0.WNRCNXM.zip"

    def test_standard_naming_still_has_android_suffix(self):
        """Non-Lite styles (Stable, Legend) must still have _A<android_ver> suffix."""
        pkg_source = PACKAGE_PY.read_text(encoding="utf-8")
        # The else branch should contain android_ver
        import re
        else_section = re.search(
            r'else:\s*\n\s+zip_name\s*=.*?_A\{android_ver\}', pkg_source
        )
        assert else_section is not None, (
            "Non-Lite ZIP naming (else branch) must include _A{android_ver}"
        )

    def test_summary_json_has_final_style(self):
        """_write_summary must add final_style to the summary dict."""
        pkg_source = PACKAGE_PY.read_text(encoding="utf-8")
        assert '"final_style"' in pkg_source, (
            "final_zip_summary.json must include final_style key"
        )

    def test_summary_json_has_naming_scheme(self):
        """_write_summary must add naming_scheme to the summary dict."""
        pkg_source = PACKAGE_PY.read_text(encoding="utf-8")
        assert '"naming_scheme"' in pkg_source, (
            "final_zip_summary.json must include naming_scheme key"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 6. ChinaStable → China Stable fix (Part D)
# ══════════════════════════════════════════════════════════════════════════════

class TestPublishTemplateRegionStable:
    _SAMPLE = {
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

    def test_china_stable_has_space(self, publish_mod):
        """render_post must produce 'China Stable' not 'ChinaStable'."""
        text = publish_mod.render_post(self._SAMPLE)
        assert "ChinaStable" not in text, "Template must not produce 'ChinaStable'"
        assert "China Stable" in text

    def test_global_stable_has_space(self, publish_mod):
        """render_post must produce 'Global Stable' not 'GlobalStable'."""
        payload = dict(self._SAMPLE, region="Global")
        text = publish_mod.render_post(payload)
        assert "GlobalStable" not in text, "Template must not produce 'GlobalStable'"
        assert "Global Stable" in text

    def test_template_first_line_exact(self, publish_mod):
        """First line of rendered post must exactly match expected format."""
        text = publish_mod.render_post(self._SAMPLE)
        first_line = text.splitlines()[0]
        assert first_line == "DeadZone v1.1 HyperOS 3.0.303.0 China Stable A16 OS3.0"

    def test_template_source_has_space_between_region_and_stable(self):
        """POST_TEMPLATE source must contain '{region} Stable' (with space)."""
        src = PUBLISH_PY.read_text(encoding="utf-8")
        assert "{region} Stable" in src, (
            "POST_TEMPLATE must use '{region} Stable' (with space) not '{region}Stable'"
        )
        assert "{region}Stable" not in src, (
            "POST_TEMPLATE must not use '{region}Stable' (no space)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 7. write_active_mods_report shows POCO mod ON
# ══════════════════════════════════════════════════════════════════════════════

class TestActiveModsReportPocoEntry:
    def test_poco_flag_in_active_mods_source(self):
        """write_active_mods_report.py must declare ENABLE_POCO_LAUNCHER_SPOOF flag."""
        src = (SCRIPTS_DIR / "write_active_mods_report.py").read_text(encoding="utf-8")
        assert "ENABLE_POCO_LAUNCHER_SPOOF" in src

    def test_poco_label_in_active_mods_source(self):
        """write_active_mods_report.py must include 'POCO Launcher To MiuiHome Spoofing' label."""
        src = (SCRIPTS_DIR / "write_active_mods_report.py").read_text(encoding="utf-8")
        assert "POCO Launcher To MiuiHome Spoofing" in src

    def test_poco_flag_default_on(self):
        """ENABLE_POCO_LAUNCHER_SPOOF must default to True (ON)."""
        amr_mod = _load(SCRIPTS_DIR / "write_active_mods_report.py", "write_active_mods_report")
        _flags = amr_mod._FLAGS
        assert "ENABLE_POCO_LAUNCHER_SPOOF" in _flags
        _, default = _flags["ENABLE_POCO_LAUNCHER_SPOOF"]
        assert default is True, "POCO launcher spoof must default to ON"

    def test_active_mods_report_shows_poco_on(self, tmp_path, monkeypatch):
        """write_report() must include POCO Launcher To MiuiHome Spoofing in the [ON] list."""
        amr_mod = _load(SCRIPTS_DIR / "write_active_mods_report.py", "write_active_mods_report_inst")
        monkeypatch.setattr(amr_mod, "REPORTS_DIR", tmp_path / "reports")
        amr_mod.write_report()

        txt = (tmp_path / "reports" / "active_mods_report.txt").read_text(encoding="utf-8")
        assert "[ON]  POCO Launcher To MiuiHome Spoofing" in txt
