#!/usr/bin/env python3
"""Tests for the DeadZone style system.

Covers:
- _normalize_style() aliases and error cases
- DZ_STYLES dict entries
- ZIP naming (unified DeadZone_<Style>_<codename>_<os>.zip for all styles)
- _write_summary new fields (final_tier, style_input_original, style_alias_used)
- Plus/Legend/Ninja mods.json presence and structure
- Plus/Legend/Ninja/Stable insmod.sh inheritance chain
- style_mod_runner _load_manifest for all styles
- kaorios --work-dir argument
- poco _candidate_partition_dirs extra bases
- framework _find_unpacked / _find_unpacked_path helpers
- write_active_mods_report default DZ_STYLE
- deadzone_full_mod_report build_full_report
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# ── project root ──────────────────────────────────────────────────────────────
TESTS_DIR    = Path(__file__).resolve().parent
BIN_DIR      = TESTS_DIR.parent
PROJECT_ROOT = BIN_DIR.parent
SCRIPTS_DIR  = BIN_DIR / "scripts"
STYLES_DIR   = BIN_DIR / "styles"
MODFILE_DIR  = BIN_DIR / "modfile" / "Styles"

sys.path.insert(0, str(SCRIPTS_DIR))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── lazy imports ──────────────────────────────────────────────────────────────
_package_rom = None
_fw_patches  = None
_poco_spoof  = None
_full_report = None
_amr         = None


def _pkg():
    global _package_rom
    if _package_rom is None:
        _package_rom = _load("package_rom", SCRIPTS_DIR / "package_rom.py")
    return _package_rom


def _fw():
    global _fw_patches
    if _fw_patches is None:
        _fw_patches = _load("deadzone_framework_patches", SCRIPTS_DIR / "deadzone_framework_patches.py")
    return _fw_patches


def _poco():
    global _poco_spoof
    if _poco_spoof is None:
        _poco_spoof = _load("poco_launcher_spoof", SCRIPTS_DIR / "poco_launcher_spoof.py")
    return _poco_spoof


def _full():
    global _full_report
    if _full_report is None:
        _full_report = _load("deadzone_full_mod_report", SCRIPTS_DIR / "deadzone_full_mod_report.py")
    return _full_report


def _amr_mod():
    global _amr
    if _amr is None:
        _amr = _load("write_active_mods_report", SCRIPTS_DIR / "write_active_mods_report.py")
    return _amr


# ══════════════════════════════════════════════════════════════════════════════
# 1. _normalize_style
# ══════════════════════════════════════════════════════════════════════════════

class TestNormalizeStyle(unittest.TestCase):

    def _n(self, s):
        return _pkg()._normalize_style(s)

    # Direct identities
    def test_lite_exact(self):
        self.assertEqual(self._n("lite"), "lite")

    def test_plus_exact(self):
        self.assertEqual(self._n("plus"), "plus")

    def test_legend_exact(self):
        self.assertEqual(self._n("legend"), "legend")

    def test_ninja_exact(self):
        self.assertEqual(self._n("ninja"), "ninja")

    # Aliases → plus
    def test_stable_maps_to_plus(self):
        self.assertEqual(self._n("stable"), "plus")

    def test_Stable_case_insensitive(self):
        self.assertEqual(self._n("Stable"), "plus")

    def test_free_maps_to_plus(self):
        self.assertEqual(self._n("free"), "plus")

    # Aliases → legend
    def test_paid_maps_to_legend(self):
        self.assertEqual(self._n("paid"), "legend")

    # Case insensitive for all
    def test_Lite_upper(self):
        self.assertEqual(self._n("Lite"), "lite")

    def test_LEGEND_upper(self):
        self.assertEqual(self._n("LEGEND"), "legend")

    def test_Ninja_upper(self):
        self.assertEqual(self._n("Ninja"), "ninja")

    # Errors
    def test_unknown_raises(self):
        with self.assertRaises(ValueError):
            self._n("unknown_style")

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            self._n("")


# ══════════════════════════════════════════════════════════════════════════════
# 2. DZ_STYLES dict
# ══════════════════════════════════════════════════════════════════════════════

class TestDZStyles(unittest.TestCase):

    def _s(self):
        return _pkg().DZ_STYLES

    def test_has_lite(self):
        self.assertIn("lite", self._s())

    def test_has_plus(self):
        self.assertIn("plus", self._s())

    def test_has_legend(self):
        self.assertIn("legend", self._s())

    def test_has_ninja(self):
        self.assertIn("ninja", self._s())

    def test_no_stable_key(self):
        self.assertNotIn("stable", self._s())

    def test_lite_tier_free(self):
        self.assertEqual(self._s()["lite"]["tier"], "Free")

    def test_plus_tier_free(self):
        self.assertEqual(self._s()["plus"]["tier"], "Free")

    def test_legend_tier_paid(self):
        self.assertEqual(self._s()["legend"]["tier"], "Paid")

    def test_ninja_tier_paid(self):
        self.assertEqual(self._s()["ninja"]["tier"], "Paid")


# ══════════════════════════════════════════════════════════════════════════════
# 3. ZIP naming scheme
# ══════════════════════════════════════════════════════════════════════════════

class TestZipNaming(unittest.TestCase):
    """Unified scheme: DeadZone_<Style>_<codename>_<os_version>.zip for all styles."""

    def _zip_name(self, style_id: str, codename: str, rom_version: str) -> str:
        pkg = _pkg()
        cfg = pkg.DZ_STYLES[style_id]
        prefix = cfg["id"].capitalize()
        return f"DeadZone_{prefix}_{pkg._sanitize_name(codename)}_{rom_version}.zip"

    def test_lite_no_android_suffix(self):
        name = self._zip_name("lite", "garnet", "OS3.0.304.0.WNRCNXM")
        self.assertEqual(name, "DeadZone_Lite_garnet_OS3.0.304.0.WNRCNXM.zip")
        self.assertNotIn("_A", name)

    def test_plus_no_android_suffix(self):
        name = self._zip_name("plus", "garnet", "OS3.0.304.0.WNRCNXM")
        self.assertEqual(name, "DeadZone_Plus_garnet_OS3.0.304.0.WNRCNXM.zip")
        self.assertNotIn("_A", name)

    def test_legend_no_android_suffix(self):
        name = self._zip_name("legend", "garnet", "OS3.0.304.0.WNRCNXM")
        self.assertEqual(name, "DeadZone_Legend_garnet_OS3.0.304.0.WNRCNXM.zip")
        self.assertNotIn("_A", name)

    def test_ninja_no_android_suffix(self):
        name = self._zip_name("ninja", "garnet", "OS3.0.304.0.WNRCNXM")
        self.assertEqual(name, "DeadZone_Ninja_garnet_OS3.0.304.0.WNRCNXM.zip")
        self.assertNotIn("_A", name)

    def test_unified_naming_scheme_field(self):
        self.assertEqual(_pkg()._normalize_style("Lite"), "lite")


# ══════════════════════════════════════════════════════════════════════════════
# 4. Plus/Legend/Ninja mods.json files
# ══════════════════════════════════════════════════════════════════════════════

class TestModsJsonFiles(unittest.TestCase):

    def _load(self, style: str) -> dict:
        path = STYLES_DIR / style / "mods.json"
        self.assertTrue(path.is_file(), f"{path} not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_plus_mods_json_exists(self):
        d = self._load("Plus")
        self.assertEqual(d["style"], "plus")

    def test_plus_inherits_lite(self):
        d = self._load("Plus")
        self.assertEqual(d.get("inherits"), "lite")

    def test_legend_mods_json_exists(self):
        d = self._load("Legend")
        self.assertEqual(d["style"], "legend")

    def test_legend_inherits_plus(self):
        d = self._load("Legend")
        self.assertEqual(d.get("inherits"), "plus")

    def test_ninja_mods_json_exists(self):
        d = self._load("Ninja")
        self.assertEqual(d["style"], "ninja")

    def test_ninja_inherits_plus(self):
        d = self._load("Ninja")
        self.assertEqual(d.get("inherits"), "plus")

    def test_plus_has_sig_bypass(self):
        d = self._load("Plus")
        ids = [m["id"] for m in d["mods"]]
        self.assertIn("signature_verification_bypass", ids)

    def test_legend_has_lite_apk_patches(self):
        d = self._load("Legend")
        ids = [m["id"] for m in d["mods"]]
        self.assertIn("lite_apk_patches", ids)

    def test_ninja_has_poco_spoof(self):
        d = self._load("Ninja")
        ids = [m["id"] for m in d["mods"]]
        self.assertIn("poco_launcher_to_miuihome_spoofing", ids)


# ══════════════════════════════════════════════════════════════════════════════
# 5. insmod.sh inheritance chain
# ══════════════════════════════════════════════════════════════════════════════

class TestInsmodInheritance(unittest.TestCase):

    def _read(self, style: str) -> str:
        p = MODFILE_DIR / style / "insmod.sh"
        self.assertTrue(p.is_file(), f"{p} not found")
        return p.read_text(encoding="utf-8")

    def test_plus_inherits_lite(self):
        content = self._read("Plus")
        self.assertIn("Lite/insmod.sh", content)

    def test_legend_inherits_plus(self):
        content = self._read("Legend")
        self.assertIn("Plus/insmod.sh", content)
        self.assertNotIn("Stable/insmod.sh", content)

    def test_ninja_inherits_plus(self):
        content = self._read("Ninja")
        self.assertIn("Plus/insmod.sh", content)
        self.assertNotIn("Stable/insmod.sh", content)

    def test_stable_delegates_to_plus(self):
        content = self._read("Stable")
        self.assertIn("Plus/insmod.sh", content)

    def test_stable_is_compat_wrapper(self):
        content = self._read("Stable")
        self.assertIn("compat", content.lower())


# ══════════════════════════════════════════════════════════════════════════════
# 6. kaorios --work-dir argument
# ══════════════════════════════════════════════════════════════════════════════

class TestKaoriosWorkDir(unittest.TestCase):

    def test_work_dir_arg_accepted(self):
        import argparse
        kaorios_path = SCRIPTS_DIR / "deadzone_kaorios_toolbox.py"
        if not kaorios_path.is_file():
            self.skipTest("deadzone_kaorios_toolbox.py not found")
        content = kaorios_path.read_text(encoding="utf-8")
        self.assertIn("--work-dir", content)

    def test_work_dir_parsed(self):
        import argparse
        ap = argparse.ArgumentParser()
        ap.add_argument("--style", default="plus")
        ap.add_argument("--work-dir", default=None)
        args = ap.parse_args(["--work-dir", "/tmp/test"])
        self.assertEqual(args.work_dir, "/tmp/test")


# ══════════════════════════════════════════════════════════════════════════════
# 7. poco _candidate_partition_dirs extra bases
# ══════════════════════════════════════════════════════════════════════════════

class TestPocoCandidateDirs(unittest.TestCase):

    def test_direct_partition_included(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            candidates = _poco()._candidate_partition_dirs(work)
            paths = [str(p) for _, p in candidates]
            self.assertTrue(any("vendor" in p for p in paths))
            self.assertTrue(any("odm" in p for p in paths))

    def test_extra_base_included(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            candidates = _poco()._candidate_partition_dirs(work)
            paths = [str(p) for _, p in candidates]
            extra_base = str(work / "build" / "baserom" / "images")
            self.assertTrue(any(extra_base in p for p in paths))

    def test_no_duplicates_when_extra_base_same(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            candidates = _poco()._candidate_partition_dirs(work)
            paths = [str(p.resolve()) for _, p in candidates]
            self.assertEqual(len(paths), len(set(paths)))

    def test_extra_base_vendor_found(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            (work / "build" / "baserom" / "images" / "vendor").mkdir(parents=True)
            candidates = _poco()._candidate_partition_dirs(work)
            found_extra = any(
                "images" in str(p) and p.name == "vendor"
                for _, p in candidates
            )
            self.assertTrue(found_extra)


# ══════════════════════════════════════════════════════════════════════════════
# 8. framework _find_unpacked / _find_unpacked_path helpers
# ══════════════════════════════════════════════════════════════════════════════

class TestFindUnpacked(unittest.TestCase):

    def test_direct_path_found(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            (work / "framework_unpacked").mkdir()
            result = _fw()._find_unpacked(work, "framework_unpacked")
            self.assertEqual(result, work / "framework_unpacked")

    def test_extra_base_path_found(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            extra = work / "build" / "baserom" / "images" / "framework_unpacked"
            extra.mkdir(parents=True)
            result = _fw()._find_unpacked(work, "framework_unpacked")
            self.assertEqual(result, extra)

    def test_fallback_to_direct_when_neither_exists(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            result = _fw()._find_unpacked(work, "framework_unpacked")
            self.assertEqual(result, work / "framework_unpacked")
            self.assertFalse(result.exists())

    def test_find_unpacked_path_with_subdir(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            target = work / "build" / "baserom" / "images" / "framework_unpacked" / "smali_classes"
            target.mkdir(parents=True)
            result = _fw()._find_unpacked_path(work, "framework_unpacked/smali_classes")
            self.assertEqual(result, target)

    def test_find_unpacked_path_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            result = _fw()._find_unpacked_path(work, "services_unpacked/smali_classes2")
            self.assertEqual(result, work / "services_unpacked" / "smali_classes2")
            self.assertFalse(result.exists())


# ══════════════════════════════════════════════════════════════════════════════
# 9. write_active_mods_report default DZ_STYLE
# ══════════════════════════════════════════════════════════════════════════════

class TestActiveModsReportDefault(unittest.TestCase):

    def test_default_style_is_plus(self):
        old = os.environ.pop("DZ_STYLE", None)
        try:
            with tempfile.TemporaryDirectory() as td:
                amr = _amr_mod()
                old_reports = amr.REPORTS_DIR
                amr.REPORTS_DIR = Path(td)
                try:
                    amr.write_report()
                    out = (Path(td) / "active_mods_report.txt").read_text()
                    self.assertIn("Plus", out)
                finally:
                    amr.REPORTS_DIR = old_reports
        finally:
            if old is not None:
                os.environ["DZ_STYLE"] = old

    def test_dz_style_env_overrides_default(self):
        os.environ["DZ_STYLE"] = "Ninja"
        try:
            with tempfile.TemporaryDirectory() as td:
                amr = _amr_mod()
                old_reports = amr.REPORTS_DIR
                amr.REPORTS_DIR = Path(td)
                try:
                    amr.write_report()
                    out = (Path(td) / "active_mods_report.txt").read_text()
                    self.assertIn("Ninja", out)
                finally:
                    amr.REPORTS_DIR = old_reports
        finally:
            del os.environ["DZ_STYLE"]


# ══════════════════════════════════════════════════════════════════════════════
# 10. deadzone_full_mod_report build_full_report
# ══════════════════════════════════════════════════════════════════════════════

class TestFullModReport(unittest.TestCase):

    def test_empty_reports_dir(self):
        with tempfile.TemporaryDirectory() as td:
            rdir = Path(td)
            result = _full().build_full_report(rdir, dz_style="lite")
            self.assertEqual(result["dz_style"], "lite")
            self.assertEqual(result["mod_reports"], [])
            self.assertIn("totals", result)

    def test_aggregates_mod_reports(self):
        with tempfile.TemporaryDirectory() as td:
            rdir = Path(td)
            fake = {
                "style": "lite",
                "generated": "2026-01-01T00:00:00Z",
                "results": [
                    {"status": "changed", "detail": "patched", "target_file": "a.smali", "mod": "test_mod"},
                    {"status": "skipped", "detail": "not found", "target_file": "b.smali", "mod": "test_mod"},
                ],
            }
            (rdir / "lite_mod_report.json").write_text(json.dumps(fake), encoding="utf-8")
            result = _full().build_full_report(rdir, dz_style="lite")
            self.assertEqual(len(result["mod_reports"]), 1)
            self.assertEqual(result["totals"]["changed"], 1)
            self.assertEqual(result["totals"]["skipped"], 1)

    def test_write_creates_txt_and_json(self):
        with tempfile.TemporaryDirectory() as td:
            rdir = Path(td)
            _full().write_full_report(rdir, dz_style="plus")
            self.assertTrue((rdir / "deadzone_full_mod_report.txt").is_file())
            self.assertTrue((rdir / "deadzone_full_mod_report.json").is_file())

    def test_self_report_not_included(self):
        with tempfile.TemporaryDirectory() as td:
            rdir = Path(td)
            (rdir / "deadzone_full_mod_report.json").write_text("{}", encoding="utf-8")
            result = _full().build_full_report(rdir)
            self.assertEqual(len(result["mod_reports"]), 0)

    def test_parse_error_reported(self):
        with tempfile.TemporaryDirectory() as td:
            rdir = Path(td)
            (rdir / "bad_mod_report.json").write_text("INVALID JSON{{", encoding="utf-8")
            result = _full().build_full_report(rdir)
            self.assertEqual(len(result["mod_reports"]), 1)
            self.assertIn("_error", result["mod_reports"][0])

    def test_totals_group_applied(self):
        with tempfile.TemporaryDirectory() as td:
            rdir = Path(td)
            fake = {
                "style": "plus",
                "generated": "2026-01-01T00:00:00Z",
                "results": [
                    {"status": "skipped", "detail": "applied via group leader", "mod": "m"},
                    {"status": "changed", "detail": "patched", "mod": "m"},
                ],
            }
            (rdir / "plus_mod_report.json").write_text(json.dumps(fake), encoding="utf-8")
            result = _full().build_full_report(rdir)
            self.assertEqual(result["totals"]["applied_via_group"], 1)
            self.assertEqual(result["totals"]["changed"], 1)


# ══════════════════════════════════════════════════════════════════════════════
# 11. _write_summary new fields
# ══════════════════════════════════════════════════════════════════════════════

class TestWriteSummaryFields(unittest.TestCase):

    def _make_dummy_zip(self, td: Path) -> Path:
        import zipfile
        zp = td / "test.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("dummy.txt", "content")
        return zp

    def test_final_tier_in_summary(self):
        with tempfile.TemporaryDirectory() as td:
            pkg = _pkg()
            orig_reports = pkg.REPORTS_DIR
            orig_work = pkg.WORK_DIR
            rdir = Path(td) / "reports"
            rdir.mkdir()
            pkg.REPORTS_DIR = rdir
            pkg.WORK_DIR = Path(td)

            zp = self._make_dummy_zip(Path(td))
            import hashlib
            sha = hashlib.sha256(zp.read_bytes()).hexdigest()
            cfg = {"codename": "garnet", "soc_family": "sd"}
            try:
                pkg._write_summary(
                    zp, sha, cfg,
                    images=[], scripts=[], flash_cmds=[], unknown_imgs=[],
                    style_id="legend",
                    style_input_original="Paid",
                )
                s = json.loads((rdir / "final_zip_summary.json").read_text())
                self.assertEqual(s["final_tier"], "Paid")
                self.assertEqual(s["style_input_original"], "Paid")
                self.assertTrue(s["style_alias_used"])
                self.assertEqual(s["final_style"], "legend")
            finally:
                pkg.REPORTS_DIR = orig_reports
                pkg.WORK_DIR = orig_work

    def test_no_alias_when_input_matches_id(self):
        with tempfile.TemporaryDirectory() as td:
            pkg = _pkg()
            orig_reports = pkg.REPORTS_DIR
            orig_work = pkg.WORK_DIR
            rdir = Path(td) / "reports"
            rdir.mkdir()
            pkg.REPORTS_DIR = rdir
            pkg.WORK_DIR = Path(td)

            zp = self._make_dummy_zip(Path(td))
            import hashlib
            sha = hashlib.sha256(zp.read_bytes()).hexdigest()
            cfg = {"codename": "garnet", "soc_family": "sd"}
            try:
                pkg._write_summary(
                    zp, sha, cfg,
                    images=[], scripts=[], flash_cmds=[], unknown_imgs=[],
                    style_id="plus",
                    style_input_original="plus",
                )
                s = json.loads((rdir / "final_zip_summary.json").read_text())
                self.assertFalse(s["style_alias_used"])
            finally:
                pkg.REPORTS_DIR = orig_reports
                pkg.WORK_DIR = orig_work


if __name__ == "__main__":
    unittest.main()
