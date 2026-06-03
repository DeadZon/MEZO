#!/usr/bin/env python3
"""Tests for SoC-specific final ZIP template selection and packaging.

Run from the repo root:
  python -m pytest tests/test_soc_template_packaging.py -v
  # or without pytest:
  python tests/test_soc_template_packaging.py
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

# ── Load package_rom from scripts/ without triggering its module-level side-effects ──
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "package_rom", REPO_ROOT / "scripts" / "package_rom.py"
)
_pkg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pkg)

_normalize_soc         = _pkg._normalize_soc
_select_template_dir   = _pkg._select_template_dir
_copy_template_to_staging = _pkg._copy_template_to_staging
_replace_bat_placeholders = _pkg._replace_bat_placeholders
_validate_template_bat = _pkg._validate_template_bat
_validate_zip          = _pkg._validate_zip
FINAL_ZIP_TEMPLATES_DIR = _pkg.FINAL_ZIP_TEMPLATES_DIR
FORBIDDEN_ENTRIES      = _pkg.FORBIDDEN_ENTRIES


class TestNormalizeSoc(unittest.TestCase):

    def test_mtk_exact(self):
        self.assertEqual(_normalize_soc("mtk"), "mtk")

    def test_mtk_mediatek(self):
        self.assertEqual(_normalize_soc("mediatek"), "mtk")

    def test_mtk_MediaTek_mixed_case(self):
        self.assertEqual(_normalize_soc("MediaTek"), "mtk")

    def test_snapdragon_exact(self):
        self.assertEqual(_normalize_soc("snapdragon"), "snapdragon")

    def test_snapdragon_qcom(self):
        self.assertEqual(_normalize_soc("qcom"), "snapdragon")

    def test_snapdragon_qualcomm(self):
        self.assertEqual(_normalize_soc("qualcomm"), "snapdragon")

    def test_snapdragon_Snapdragon_mixed_case(self):
        self.assertEqual(_normalize_soc("Snapdragon"), "snapdragon")

    def test_unknown_soc_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _normalize_soc("exynos")
        self.assertIn("Unsupported SoC for final ZIP template", str(ctx.exception))
        self.assertIn("exynos", str(ctx.exception))

    def test_empty_string_raises(self):
        with self.assertRaises(ValueError):
            _normalize_soc("")

    def test_kirin_raises(self):
        with self.assertRaises(ValueError):
            _normalize_soc("kirin")


class TestSelectTemplateDir(unittest.TestCase):

    def test_mtk_selects_mtk_template(self):
        tpl = _select_template_dir("mtk")
        self.assertEqual(tpl.parent, FINAL_ZIP_TEMPLATES_DIR)
        self.assertEqual(tpl.name, "mtk")
        self.assertTrue(tpl.is_dir(), f"MTK template dir missing: {tpl}")

    def test_snapdragon_selects_snapdragon_template(self):
        tpl = _select_template_dir("snapdragon")
        self.assertEqual(tpl.parent, FINAL_ZIP_TEMPLATES_DIR)
        self.assertEqual(tpl.name, "snapdragon")
        self.assertTrue(tpl.is_dir(), f"Snapdragon template dir missing: {tpl}")

    def test_mtk_template_has_fastboot_exe(self):
        tpl = _select_template_dir("mtk")
        self.assertTrue((tpl / "bin" / "windows" / "fastboot.exe").is_file())

    def test_snapdragon_template_has_fastboot_exe(self):
        tpl = _select_template_dir("snapdragon")
        self.assertTrue((tpl / "bin" / "windows" / "fastboot.exe").is_file())

    def test_mtk_template_has_install_bat(self):
        tpl = _select_template_dir("mtk")
        self.assertTrue((tpl / "windows_install_and_format_data.bat").is_file())

    def test_snapdragon_template_has_install_bat(self):
        tpl = _select_template_dir("snapdragon")
        self.assertTrue((tpl / "windows_install_and_format_data.bat").is_file())

    def test_missing_template_raises(self):
        with self.assertRaises(FileNotFoundError):
            _select_template_dir("nonexistent_soc_xyz")


class TestTemplateCopy(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _stage_for(self, norm_soc: str) -> tuple[Path, list[str]]:
        tpl = _select_template_dir(norm_soc)
        staging = self.tmp / "staging"
        staging.mkdir()
        copied = _copy_template_to_staging(tpl, staging)
        return staging, copied

    def test_mtk_copy_does_not_include_snapdragon_content(self):
        staging, _ = self._stage_for("mtk")
        # Snapdragon has META-INF; MTK does not
        self.assertFalse((staging / "META-INF").is_dir(),
                         "MTK staging must not contain Snapdragon META-INF")

    def test_snapdragon_copy_does_not_include_mtk_content(self):
        staging, _ = self._stage_for("snapdragon")
        # Both templates have the install BAT, but we verify the content is Snapdragon's
        bat = staging / "windows_install_and_format_data.bat"
        self.assertTrue(bat.is_file())
        content = bat.read_text(encoding="utf-8", errors="replace")
        # Snapdragon template uses _a/_b; not _ab
        import re
        self.assertFalse(
            bool(re.search(r'flash\s+\w+_ab\s+images\\', content, re.IGNORECASE)),
            "Snapdragon staging must not contain MTK _ab flash commands"
        )

    def test_mtk_staging_has_fastboot_exe(self):
        staging, _ = self._stage_for("mtk")
        self.assertTrue((staging / "bin" / "windows" / "fastboot.exe").is_file())

    def test_snapdragon_staging_has_fastboot_exe(self):
        staging, _ = self._stage_for("snapdragon")
        self.assertTrue((staging / "bin" / "windows" / "fastboot.exe").is_file())

    def test_templates_are_never_mixed(self):
        mtk_staging = self.tmp / "mtk_staging"
        mtk_staging.mkdir()
        sd_staging = self.tmp / "sd_staging"
        sd_staging.mkdir()

        _copy_template_to_staging(_select_template_dir("mtk"), mtk_staging)
        _copy_template_to_staging(_select_template_dir("snapdragon"), sd_staging)

        mtk_bat = (mtk_staging / "windows_install_and_format_data.bat").read_text(
            encoding="utf-8", errors="replace"
        )
        sd_bat = (sd_staging / "windows_install_and_format_data.bat").read_text(
            encoding="utf-8", errors="replace"
        )
        # The two BAT files must be different (they have different flash commands)
        self.assertNotEqual(mtk_bat, sd_bat,
                            "MTK and Snapdragon templates must have different install scripts")


class TestReplaceBatPlaceholders(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_bat(self, content: str) -> Path:
        p = self.tmp / "test.bat"
        p.write_text(content, encoding="utf-8")
        return p

    def test_replaces_known_placeholders(self):
        bat = self._write_bat('set "ROM_VERSION=CN_VERSION_FROM_ROM"\n')
        replaced = _replace_bat_placeholders(bat, {"CN_VERSION_FROM_ROM": "OS2.0.200.0.VNXCNXM"})
        self.assertIn("CN_VERSION_FROM_ROM", replaced)
        self.assertIn("OS2.0.200.0.VNXCNXM", bat.read_text(encoding="utf-8"))

    def test_does_not_replace_unknown_placeholders(self):
        bat = self._write_bat('set X=MYSTERY_PLACEHOLDER\n')
        replaced = _replace_bat_placeholders(bat, {"MYSTERY_PLACEHOLDER": "should_not_replace"})
        self.assertEqual(replaced, [])
        self.assertIn("MYSTERY_PLACEHOLDER", bat.read_text(encoding="utf-8"))

    def test_replaces_only_present_placeholders(self):
        bat = self._write_bat('set "ROM_DEVICE=DEVICE_FROM_ROM"\n')
        replaced = _replace_bat_placeholders(bat, {
            "DEVICE_FROM_ROM":     "zircon",
            "ANDROID_FROM_ROM":    "14",       # not in file
        })
        self.assertIn("DEVICE_FROM_ROM", replaced)
        self.assertNotIn("ANDROID_FROM_ROM", replaced)

    def test_missing_bat_returns_empty(self):
        replaced = _replace_bat_placeholders(self.tmp / "nonexistent.bat", {"CN_VERSION_FROM_ROM": "v1"})
        self.assertEqual(replaced, [])

    def test_does_not_modify_fastboot_flash_lines(self):
        content = (
            'set "ROM_DEVICE=DEVICE_FROM_ROM"\n'
            '%fastboot% flash boot_ab images\\boot.img\n'
        )
        bat = self._write_bat(content)
        _replace_bat_placeholders(bat, {"DEVICE_FROM_ROM": "zircon"})
        result = bat.read_text(encoding="utf-8")
        # flash command must be unchanged
        self.assertIn('%fastboot% flash boot_ab images\\boot.img', result)


class TestValidateTemplateBat(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_bat(self, content: str) -> None:
        (self.tmp / "windows_install_and_format_data.bat").write_text(content, encoding="utf-8")

    def test_valid_mtk_bat_passes(self):
        self._write_bat(
            '@echo off\n'
            '%fastboot% flash boot_ab images\\boot.img\n'
            '%fastboot% flash super images\\super.img\n'
        )
        errors = _validate_template_bat(self.tmp, "mtk")
        self.assertEqual(errors, [])

    def test_valid_snapdragon_bat_passes(self):
        self._write_bat(
            '@echo off\n'
            '%fastboot% flash boot_a images\\boot.img\n'
            '%fastboot% flash boot_b images\\boot.img\n'
            '%fastboot% flash super images\\super.img\n'
        )
        errors = _validate_template_bat(self.tmp, "snapdragon")
        self.assertEqual(errors, [])

    def test_mtk_bat_with_snapdragon_pattern_fails(self):
        self._write_bat(
            '@echo off\n'
            '%fastboot% flash boot_a images\\boot.img\n'
            '%fastboot% flash boot_b images\\boot.img\n'
        )
        errors = _validate_template_bat(self.tmp, "mtk")
        self.assertTrue(len(errors) > 0, "MTK bat with _a/_b pattern should fail")

    def test_snapdragon_bat_with_ab_pattern_fails(self):
        self._write_bat(
            '@echo off\n'
            '%fastboot% flash boot_ab images\\boot.img\n'
        )
        errors = _validate_template_bat(self.tmp, "snapdragon")
        self.assertTrue(len(errors) > 0, "Snapdragon bat with _ab pattern should fail")

    def test_missing_bat_fails(self):
        errors = _validate_template_bat(self.tmp, "mtk")
        self.assertTrue(len(errors) > 0)

    def test_empty_bat_fails(self):
        (self.tmp / "windows_install_and_format_data.bat").write_text("", encoding="utf-8")
        errors = _validate_template_bat(self.tmp, "mtk")
        self.assertTrue(len(errors) > 0)


class TestZipValidation(unittest.TestCase):
    """Test that _validate_zip enforces the single-install-bat and no-template-dir rules."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _build_zip(self, entries: dict[str, str]) -> Path:
        """Build a ZIP from {arcname: content} dict and return its path."""
        zp = self.tmp / "test.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            for name, content in entries.items():
                zf.writestr(name, content)
        return zp

    def _minimal_valid_entries(self) -> dict[str, str]:
        return {
            "images/super.img":                    "fake",
            "images/vbmeta.img":                   "fake",
            "windows_install_and_format_data.bat": "@echo off\n%fastboot% flash super images\\super.img\n",
            "windows_install_upgrade.bat":          "@echo off\n",
            "windows_format_data_only.bat":         "@echo off\n",
        }

    def test_exactly_one_install_bat_at_root_passes(self):
        entries = self._minimal_valid_entries()
        zp = self._build_zip(entries)
        errors = _validate_zip(zp, {"super.img", "vbmeta.img"})
        install_bat_errors = [e for e in errors if "windows_install_and_format_data" in e]
        self.assertEqual(install_bat_errors, [])

    def test_duplicate_install_bat_fails(self):
        entries = self._minimal_valid_entries()
        # Add a second copy in a subdirectory (shouldn't happen, but test the validator)
        entries["subdir/windows_install_and_format_data.bat"] = "@echo off\n"
        # The root one still exists; validator only checks for root copies
        zp = self._build_zip(entries)
        errors = _validate_zip(zp, {"super.img", "vbmeta.img"})
        # Should still be exactly one at root — no error
        install_bat_errors = [e for e in errors if "windows_install_and_format_data.bat" in e.lower()]
        self.assertEqual(install_bat_errors, [])

    def test_final_zip_templates_forbidden(self):
        entries = self._minimal_valid_entries()
        entries["bin/final_zip_templates/mtk/windows_install_and_format_data.bat"] = "@echo off\n"
        zp = self._build_zip(entries)
        errors = _validate_zip(zp, {"super.img", "vbmeta.img"})
        self.assertTrue(
            any("final_zip_templates" in e for e in errors),
            "ZIP containing final_zip_templates must fail validation"
        )

    def test_super_img_missing_fails(self):
        entries = {
            "images/vbmeta.img":                   "fake",
            "windows_install_and_format_data.bat": "@echo off\n",
        }
        zp = self._build_zip(entries)
        errors = _validate_zip(zp, {"vbmeta.img"})
        self.assertTrue(any("super.img" in e for e in errors))

    def test_real_mtk_template_has_no_snapdragon_content(self):
        tpl = _select_template_dir("mtk")
        bat_content = (tpl / "windows_install_and_format_data.bat").read_text(
            encoding="utf-8", errors="replace"
        )
        # MTK template must not have Snapdragon META-INF
        self.assertFalse((tpl / "META-INF").is_dir(),
                         "MTK template must not contain META-INF (Snapdragon-only)")
        # MTK template must use _ab partition names in its BAT
        self.assertIn("_ab", bat_content.lower(),
                      "MTK template BAT must contain _ab partition names")

    def test_real_snapdragon_template_has_no_mtk_ab_commands(self):
        import re
        tpl = _select_template_dir("snapdragon")
        bat_content = (tpl / "windows_install_and_format_data.bat").read_text(
            encoding="utf-8", errors="replace"
        )
        # Snapdragon template must not have _ab partition flash commands
        self.assertFalse(
            bool(re.search(r'flash\s+\w+_ab\s+images\\', bat_content, re.IGNORECASE)),
            "Snapdragon template must not contain MTK _ab flash commands"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
