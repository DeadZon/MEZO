#!/usr/bin/env python3
"""Tests for SoC-specific final ZIP template selection and BAT generation.

Run from the repo root:
  python -m pytest tests/test_soc_template_packaging.py -v
  # or without pytest:
  python tests/test_soc_template_packaging.py
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "package_rom", REPO_ROOT / "scripts" / "package_rom.py"
)
_pkg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pkg)

_normalize_soc            = _pkg._normalize_soc
_select_template_dir      = _pkg._select_template_dir
_copy_template_to_staging = _pkg._copy_template_to_staging
_validate_template_bat    = _pkg._validate_template_bat
_validate_zip             = _pkg._validate_zip
_compute_flash_pairs      = _pkg._compute_flash_pairs
_ordered_mtk_imgs         = _pkg._ordered_mtk_imgs
_ordered_sd_imgs          = _pkg._ordered_sd_imgs
_gen_install_bat          = _pkg._gen_install_bat
FINAL_ZIP_TEMPLATES_DIR   = _pkg.FINAL_ZIP_TEMPLATES_DIR
FORBIDDEN_ENTRIES         = _pkg.FORBIDDEN_ENTRIES
_FORBIDDEN_ROOT_BATS      = _pkg._FORBIDDEN_ROOT_BATS
_GEN_WIN_SCRIPTS          = _pkg._GEN_WIN_SCRIPTS
MTK_DANGEROUS_PRELOADERS  = _pkg.MTK_DANGEROUS_PRELOADERS
SD_NONSLOT_IMGS           = _pkg.SD_NONSLOT_IMGS
MTK_FLASH_MAP             = _pkg.MTK_FLASH_MAP


# ── SoC normalization ─────────────────────────────────────────────────────────

class TestNormalizeSoc(unittest.TestCase):

    def test_mtk_exact(self):
        self.assertEqual(_normalize_soc("mtk"), "mtk")

    def test_mtk_mediatek(self):
        self.assertEqual(_normalize_soc("mediatek"), "mtk")

    def test_mtk_mixed_case(self):
        self.assertEqual(_normalize_soc("MediaTek"), "mtk")

    def test_snapdragon_exact(self):
        self.assertEqual(_normalize_soc("snapdragon"), "snapdragon")

    def test_snapdragon_qcom(self):
        self.assertEqual(_normalize_soc("qcom"), "snapdragon")

    def test_snapdragon_qualcomm(self):
        self.assertEqual(_normalize_soc("qualcomm"), "snapdragon")

    def test_snapdragon_mixed_case(self):
        self.assertEqual(_normalize_soc("Snapdragon"), "snapdragon")

    def test_unknown_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _normalize_soc("exynos")
        self.assertIn("Unsupported SoC", str(ctx.exception))

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            _normalize_soc("")


# ── Template directory selection ──────────────────────────────────────────────

class TestSelectTemplateDir(unittest.TestCase):

    def test_mtk_selects_mtk_template(self):
        tpl = _select_template_dir("mtk")
        self.assertEqual(tpl.name, "mtk")

    def test_snapdragon_selects_snapdragon_template(self):
        tpl = _select_template_dir("snapdragon")
        self.assertEqual(tpl.name, "snapdragon")

    def test_mtk_has_fastboot_exe(self):
        tpl = _select_template_dir("mtk")
        self.assertTrue((tpl / "bin" / "windows" / "fastboot.exe").is_file())

    def test_snapdragon_has_fastboot_exe(self):
        tpl = _select_template_dir("snapdragon")
        self.assertTrue((tpl / "bin" / "windows" / "fastboot.exe").is_file())

    def test_mtk_has_install_bat(self):
        tpl = _select_template_dir("mtk")
        self.assertTrue((tpl / "windows_install_and_format_data.bat").is_file())

    def test_snapdragon_has_install_bat(self):
        tpl = _select_template_dir("snapdragon")
        self.assertTrue((tpl / "windows_install_and_format_data.bat").is_file())

    def test_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            _select_template_dir("nonexistent_soc_xyz")

    def test_templates_have_no_forbidden_bats(self):
        for soc in ("mtk", "snapdragon"):
            tpl = _select_template_dir(soc)
            for fname in _FORBIDDEN_ROOT_BATS:
                self.assertFalse(
                    (tpl / fname).is_file(),
                    f"{soc} template must not contain {fname}"
                )


# ── Flash pair computation ────────────────────────────────────────────────────

class TestComputeFlashPairs(unittest.TestCase):

    def _flash_cmds(self, available, soc):
        pairs, _ = _compute_flash_pairs(available, soc)
        return [(p, img) for p, img in pairs]

    def _partitions(self, available, soc):
        return [p for p, _ in self._flash_cmds(available, soc)]

    # ── MTK rules ────────────────────────────────────────────────────────────

    def test_mtk_boot_uses_ab_suffix(self):
        pairs = self._flash_cmds({"boot.img", "super.img", "vbmeta.img"}, "mtk")
        boot_pair = next((p for p in pairs if p[1] == "boot.img"), None)
        self.assertIsNotNone(boot_pair)
        self.assertEqual(boot_pair[0], "boot_ab")

    def test_mtk_vbmeta_uses_ab_suffix(self):
        pairs = self._flash_cmds({"super.img", "vbmeta.img"}, "mtk")
        vbmeta_pair = next((p for p in pairs if p[1] == "vbmeta.img"), None)
        self.assertIsNotNone(vbmeta_pair)
        self.assertEqual(vbmeta_pair[0], "vbmeta_ab")

    def test_mtk_super_uses_no_suffix(self):
        pairs = self._flash_cmds({"super.img", "vbmeta.img"}, "mtk")
        super_pair = next((p for p in pairs if p[1] == "super.img"), None)
        self.assertIsNotNone(super_pair)
        self.assertEqual(super_pair[0], "super")

    def test_mtk_super_is_last(self):
        available = {"boot.img", "super.img", "vbmeta.img", "init_boot.img"}
        order = [img for _, img in self._flash_cmds(available, "mtk")]
        self.assertEqual(order[-1], "super.img")

    def test_mtk_dangerous_preloader_is_skipped(self):
        for dangerous in MTK_DANGEROUS_PRELOADERS:
            available = {"super.img", "vbmeta.img", dangerous}
            pairs, skipped = _compute_flash_pairs(available, "mtk")
            flashed_imgs = [img for _, img in pairs]
            self.assertNotIn(dangerous, flashed_imgs,
                             f"{dangerous} must not appear in MTK flash commands")
            skipped_imgs = [img for img, _ in skipped]
            self.assertIn(dangerous, skipped_imgs,
                          f"{dangerous} must appear in skipped list")

    def test_mtk_preloader_raw_uses_ab(self):
        pairs = self._flash_cmds({"super.img", "vbmeta.img", "preloader_raw.img"}, "mtk")
        raw_pair = next((p for p in pairs if p[1] == "preloader_raw.img"), None)
        self.assertIsNotNone(raw_pair)
        self.assertEqual(raw_pair[0], "preloader_raw_ab")

    def test_mtk_unknown_image_gets_ab_suffix(self):
        """Image not in MTK_FLASH_MAP gets stem_ab derived from filename."""
        pairs = self._flash_cmds({"super.img", "vbmeta.img", "new_chip_fw.img"}, "mtk")
        new_pair = next((p for p in pairs if p[1] == "new_chip_fw.img"), None)
        self.assertIsNotNone(new_pair)
        self.assertEqual(new_pair[0], "new_chip_fw_ab")

    def test_mtk_no_ab_warning_for_unknown_images(self):
        """No 'Unknown images' warning should be emitted for MTK."""
        _, skipped = _compute_flash_pairs({"super.img", "vbmeta.img", "new_chip_fw.img"}, "mtk")
        # skipped should only contain dangerous preloaders, not regular unknown images
        for img, reason in skipped:
            self.assertIn("preloader", img.lower(),
                          f"Only dangerous preloaders should be skipped, got: {img}")

    # ── Snapdragon rules ──────────────────────────────────────────────────────

    def test_sd_boot_uses_both_slots(self):
        pairs = self._flash_cmds({"boot.img", "super.img", "vbmeta.img"}, "snapdragon")
        boot_pairs = [(p, img) for p, img in pairs if img == "boot.img"]
        self.assertEqual(len(boot_pairs), 2)
        partitions = {p for p, _ in boot_pairs}
        self.assertIn("boot_a", partitions)
        self.assertIn("boot_b", partitions)

    def test_sd_super_uses_no_suffix(self):
        pairs = self._flash_cmds({"super.img", "vbmeta.img"}, "snapdragon")
        super_pair = next((p for p in pairs if p[1] == "super.img"), None)
        self.assertIsNotNone(super_pair)
        self.assertEqual(super_pair[0], "super")

    def test_sd_super_has_only_one_command(self):
        pairs = self._flash_cmds({"super.img", "vbmeta.img"}, "snapdragon")
        super_pairs = [(p, img) for p, img in pairs if img == "super.img"]
        self.assertEqual(len(super_pairs), 1)

    def test_sd_cust_uses_no_suffix(self):
        pairs = self._flash_cmds({"super.img", "vbmeta.img", "cust.img"}, "snapdragon")
        cust_pair = next((p for p in pairs if p[1] == "cust.img"), None)
        self.assertIsNotNone(cust_pair)
        self.assertEqual(cust_pair[0], "cust")

    def test_sd_super_is_last(self):
        available = {"boot.img", "super.img", "vbmeta.img", "init_boot.img"}
        # Get last unique img in flash order
        pairs = self._flash_cmds(available, "snapdragon")
        last_img = pairs[-1][1]
        self.assertEqual(last_img, "super.img")

    def test_sd_abl_uses_both_slots(self):
        pairs = self._flash_cmds({"super.img", "vbmeta.img", "abl.img"}, "snapdragon")
        abl_pairs = [(p, img) for p, img in pairs if img == "abl.img"]
        self.assertEqual(len(abl_pairs), 2)
        partitions = {p for p, _ in abl_pairs}
        self.assertIn("abl_a", partitions)
        self.assertIn("abl_b", partitions)

    def test_sd_xbl_config_parsed_correctly(self):
        """xbl_config.img must become xbl_config_a and xbl_config_b, not x or xbl."""
        pairs = self._flash_cmds({"super.img", "vbmeta.img", "xbl_config.img"}, "snapdragon")
        xbl_pairs = [(p, img) for p, img in pairs if img == "xbl_config.img"]
        self.assertEqual(len(xbl_pairs), 2)
        partitions = {p for p, _ in xbl_pairs}
        self.assertIn("xbl_config_a", partitions)
        self.assertIn("xbl_config_b", partitions)
        # Must NOT produce single-letter partition names
        for p, _ in xbl_pairs:
            self.assertGreater(len(p), 2, f"Partition name too short: {p}")

    def test_sd_vbmeta_system_parsed_correctly(self):
        pairs = self._flash_cmds({"super.img", "vbmeta.img", "vbmeta_system.img"}, "snapdragon")
        vs_pairs = [(p, img) for p, img in pairs if img == "vbmeta_system.img"]
        self.assertEqual(len(vs_pairs), 2)
        partitions = {p for p, _ in vs_pairs}
        self.assertIn("vbmeta_system_a", partitions)
        self.assertIn("vbmeta_system_b", partitions)

    def test_sd_no_ab_suffix_used(self):
        """Snapdragon must never emit _ab partition names."""
        available = {"super.img", "vbmeta.img", "boot.img", "abl.img", "xbl.img"}
        pairs = self._flash_cmds(available, "snapdragon")
        for partition, img in pairs:
            self.assertFalse(
                partition.endswith("_ab"),
                f"Snapdragon partition must not use _ab suffix: {partition} (for {img})"
            )

    def test_sd_no_unknown_warning(self):
        """No images should be 'unknown' or skipped for Snapdragon."""
        available = {"super.img", "vbmeta.img", "abl.img", "xbl.img", "modem.img"}
        _, skipped = _compute_flash_pairs(available, "snapdragon")
        self.assertEqual(skipped, [],
                         "Snapdragon should not skip any regular firmware images")


# ── BAT generation ────────────────────────────────────────────────────────────

class TestGenInstallBat(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _gen(self, available_imgs, soc, **kwargs):
        defaults = dict(
            codename="testdevice",
            rom_version="OS1.0",
            android_ver="14",
            region="Global",
        )
        defaults.update(kwargs)
        return _gen_install_bat(
            staging=self.tmp,
            available_imgs=available_imgs,
            norm_soc=soc,
            **defaults,
        )

    def _read_bat(self):
        return (self.tmp / "windows_install_and_format_data.bat").read_text(
            encoding="utf-8", errors="replace"
        )

    # ── MTK tests ────────────────────────────────────────────────────────────

    def test_mtk_bat_created(self):
        self._gen({"super.img", "vbmeta.img"}, "mtk")
        self.assertTrue((self.tmp / "windows_install_and_format_data.bat").is_file())

    def test_mtk_bat_has_color_header(self):
        self._gen({"super.img", "vbmeta.img"}, "mtk")
        content = self._read_bat()
        self.assertIn("color 0B", content)
        self.assertIn("chcp 65001", content)
        self.assertIn("title DeadZone MTK Installer", content)
        self.assertIn("cls", content)

    def test_mtk_bat_has_rom_info(self):
        self._gen({"super.img", "vbmeta.img"}, "mtk", rom_version="OS1.0.100", codename="zircon")
        content = self._read_bat()
        self.assertIn("OS1.0.100", content)
        self.assertIn("zircon", content)
        self.assertIn("ROM_STYLE", content)
        self.assertIn("ROM_DEVELOPER", content)

    def test_mtk_bat_has_warning_text(self):
        self._gen({"super.img", "vbmeta.img"}, "mtk")
        content = self._read_bat()
        self.assertIn("UNLOCKED", content.upper())

    def test_mtk_bat_uses_ab_for_boot(self):
        self._gen({"super.img", "vbmeta.img", "boot.img"}, "mtk")
        content = self._read_bat()
        self.assertIn("flash boot_ab", content)

    def test_mtk_bat_flashes_only_present_images(self):
        self._gen({"super.img", "vbmeta.img"}, "mtk")
        content = self._read_bat()
        self.assertNotIn("boot.img", content)   # boot.img not present
        self.assertIn("super.img", content)
        self.assertIn("vbmeta.img", content)

    def test_mtk_bat_no_snapdragon_slot_pattern(self):
        self._gen({"super.img", "vbmeta.img", "boot.img", "init_boot.img"}, "mtk")
        content = self._read_bat()
        self.assertFalse(
            bool(re.search(r'flash\s+\w+_[ab]\s+', content, re.IGNORECASE)),
            "MTK BAT must not contain Snapdragon _a/_b slot pattern"
        )

    def test_mtk_bat_dangerous_preloader_absent(self):
        for dangerous in list(MTK_DANGEROUS_PRELOADERS)[:3]:
            with self.subTest(img=dangerous):
                self._gen({"super.img", "vbmeta.img", dangerous}, "mtk")
                content = self._read_bat()
                self.assertNotIn(f'images\\{dangerous}', content,
                                 f"Dangerous preloader {dangerous} must not be in flash commands")

    def test_mtk_bat_super_last(self):
        self._gen({"super.img", "vbmeta.img", "boot.img"}, "mtk")
        content = self._read_bat()
        # super.img reference should come after vbmeta.img reference
        self.assertGreater(
            content.rfind("super.img"),
            content.rfind("vbmeta.img"),
        )

    def test_mtk_bat_ends_with_wipe(self):
        self._gen({"super.img", "vbmeta.img"}, "mtk")
        content = self._read_bat()
        self.assertIn("erase metadata", content)
        self.assertIn("erase userdata", content)
        self.assertIn("reboot", content)
        # wipe must appear after flash commands
        flash_pos  = content.rfind("flash super")
        erase_pos  = content.find("erase metadata")
        self.assertGreater(erase_pos, flash_pos)

    def test_mtk_bat_unknown_image_gets_ab(self):
        self._gen({"super.img", "vbmeta.img", "mystery_fw.img"}, "mtk")
        content = self._read_bat()
        self.assertIn("flash mystery_fw_ab", content)

    def test_mtk_returns_flash_cmds_summary(self):
        flash_cmds, _ = self._gen({"super.img", "vbmeta.img", "boot.img"}, "mtk")
        self.assertTrue(len(flash_cmds) > 0)
        cmd = next((c for c in flash_cmds if "boot" in c), None)
        self.assertIsNotNone(cmd)
        self.assertIn("boot_ab", cmd)

    # ── Snapdragon tests ──────────────────────────────────────────────────────

    def test_sd_bat_created(self):
        self._gen({"super.img", "vbmeta.img"}, "snapdragon")
        self.assertTrue((self.tmp / "windows_install_and_format_data.bat").is_file())

    def test_sd_bat_has_color_header(self):
        self._gen({"super.img", "vbmeta.img"}, "snapdragon")
        content = self._read_bat()
        self.assertIn("color 0B", content)
        self.assertIn("chcp 65001", content)
        self.assertIn("title DeadZone Snapdragon Installer", content)

    def test_sd_bat_flashes_boot_twice(self):
        self._gen({"super.img", "vbmeta.img", "boot.img"}, "snapdragon")
        content = self._read_bat()
        self.assertIn("flash boot_a", content)
        self.assertIn("flash boot_b", content)

    def test_sd_bat_no_ab_partition(self):
        self._gen({"super.img", "vbmeta.img", "boot.img", "abl.img"}, "snapdragon")
        content = self._read_bat()
        self.assertFalse(
            bool(re.search(r'flash\s+\w+_ab\s+', content, re.IGNORECASE)),
            "Snapdragon BAT must not use MTK _ab partition names"
        )

    def test_sd_bat_super_once_no_slots(self):
        self._gen({"super.img", "vbmeta.img"}, "snapdragon")
        content = self._read_bat()
        # "flash super " should appear exactly once
        self.assertEqual(content.count("flash super "), 1)

    def test_sd_bat_xbl_config_correct_parse(self):
        self._gen({"super.img", "vbmeta.img", "xbl_config.img"}, "snapdragon")
        content = self._read_bat()
        self.assertIn("flash xbl_config_a", content)
        self.assertIn("flash xbl_config_b", content)
        # Must not produce a garbage short partition name
        self.assertNotIn("flash x ", content)
        self.assertNotIn("flash xbl ", content)

    def test_sd_bat_flashes_only_present_images(self):
        self._gen({"super.img", "vbmeta.img"}, "snapdragon")
        content = self._read_bat()
        self.assertNotIn("boot.img", content)   # boot.img not present
        self.assertIn("vbmeta.img", content)

    def test_sd_bat_ends_with_wipe(self):
        self._gen({"super.img", "vbmeta.img"}, "snapdragon")
        content = self._read_bat()
        self.assertIn("erase metadata", content)
        self.assertIn("erase userdata", content)
        self.assertIn("reboot", content)

    def test_sd_bat_super_last(self):
        self._gen({"super.img", "vbmeta.img", "boot.img"}, "snapdragon")
        content = self._read_bat()
        self.assertGreater(
            content.rfind("super.img"),
            content.rfind("vbmeta.img"),
        )

    def test_sd_returns_flash_cmds_for_each_slot(self):
        flash_cmds, _ = self._gen({"super.img", "vbmeta.img", "boot.img"}, "snapdragon")
        # Match commands that reference images\boot.img specifically
        boot_cmds = [c for c in flash_cmds if "images\\boot.img" in c or "images/boot.img" in c]
        self.assertEqual(len(boot_cmds), 2, "boot.img must produce 2 flash commands for SD")


# ── BAT validation ────────────────────────────────────────────────────────────

class TestValidateTemplateBat(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_bat(self, content):
        (self.tmp / "windows_install_and_format_data.bat").write_text(content, encoding="utf-8")

    def test_generated_mtk_bat_passes(self):
        _gen_install_bat(self.tmp, {"super.img", "vbmeta.img", "boot.img"}, "mtk",
                         "dev", "v1", "14", "CN")
        errors = _validate_template_bat(self.tmp, "mtk")
        self.assertEqual(errors, [])

    def test_generated_sd_bat_passes(self):
        _gen_install_bat(self.tmp, {"super.img", "vbmeta.img", "boot.img"}, "snapdragon",
                         "garnet", "v1", "14", "Global")
        errors = _validate_template_bat(self.tmp, "snapdragon")
        self.assertEqual(errors, [])

    def test_mtk_bat_with_snapdragon_pattern_fails(self):
        self._write_bat(
            '@echo off\n%fastboot% flash boot_a images\\boot.img\n'
        )
        errors = _validate_template_bat(self.tmp, "mtk")
        self.assertTrue(len(errors) > 0)

    def test_sd_bat_with_ab_pattern_fails(self):
        self._write_bat(
            '@echo off\n%fastboot% flash boot_ab images\\boot.img\n'
        )
        errors = _validate_template_bat(self.tmp, "snapdragon")
        self.assertTrue(len(errors) > 0)

    def test_missing_bat_fails(self):
        errors = _validate_template_bat(self.tmp, "mtk")
        self.assertTrue(len(errors) > 0)

    def test_empty_bat_fails(self):
        (self.tmp / "windows_install_and_format_data.bat").write_text("", encoding="utf-8")
        errors = _validate_template_bat(self.tmp, "mtk")
        self.assertTrue(len(errors) > 0)


# ── ZIP validation ────────────────────────────────────────────────────────────

class TestZipValidation(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _build_zip(self, entries):
        zp = self.tmp / "test.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            for name, content in entries.items():
                zf.writestr(name, content)
        return zp

    def _minimal_valid_entries(self):
        return {
            "images/super.img":                    "fake",
            "images/vbmeta.img":                   "fake",
            "windows_install_and_format_data.bat": "@echo off\n",
        }

    def test_mtk_zip_has_only_one_root_bat(self):
        zp = self._build_zip(self._minimal_valid_entries())
        with zipfile.ZipFile(zp) as zf:
            root_bats = [n for n in zf.namelist() if "/" not in n and n.lower().endswith(".bat")]
        self.assertEqual(len(root_bats), 1)
        self.assertEqual(root_bats[0], "windows_install_and_format_data.bat")

    def test_snapdragon_zip_has_only_one_root_bat(self):
        zp = self._build_zip(self._minimal_valid_entries())
        with zipfile.ZipFile(zp) as zf:
            root_bats = [n for n in zf.namelist() if "/" not in n and n.lower().endswith(".bat")]
        self.assertEqual(len(root_bats), 1)

    def test_zip_with_upgrade_bat_fails(self):
        entries = self._minimal_valid_entries()
        entries["windows_install_upgrade.bat"] = "@echo off\n"
        zp = self._build_zip(entries)
        errors = _validate_zip(zp, {"super.img", "vbmeta.img"})
        self.assertTrue(any("windows_install_upgrade.bat" in e for e in errors))

    def test_zip_with_format_bat_fails(self):
        entries = self._minimal_valid_entries()
        entries["windows_format_data_only.bat"] = "@echo off\n"
        zp = self._build_zip(entries)
        errors = _validate_zip(zp, {"super.img", "vbmeta.img"})
        self.assertTrue(any("windows_format_data_only.bat" in e for e in errors))

    def test_final_zip_templates_forbidden(self):
        entries = self._minimal_valid_entries()
        entries["bin/final_zip_templates/mtk/dummy.bat"] = "@echo off\n"
        zp = self._build_zip(entries)
        errors = _validate_zip(zp, {"super.img", "vbmeta.img"})
        self.assertTrue(any("final_zip_templates" in e for e in errors))

    def test_super_img_missing_fails(self):
        entries = {"images/vbmeta.img": "fake", "windows_install_and_format_data.bat": "@echo off\n"}
        zp = self._build_zip(entries)
        errors = _validate_zip(zp, {"vbmeta.img"})
        self.assertTrue(any("super.img" in e for e in errors))

    def test_gen_win_scripts_is_empty(self):
        self.assertEqual(_GEN_WIN_SCRIPTS, [])

    def test_forbidden_root_bats_correct(self):
        self.assertIn("windows_install_upgrade.bat", _FORBIDDEN_ROOT_BATS)
        self.assertIn("windows_format_data_only.bat", _FORBIDDEN_ROOT_BATS)

    def test_staging_after_copy_has_no_forbidden_bats(self):
        for soc in ("mtk", "snapdragon"):
            with self.subTest(soc=soc):
                tpl = _select_template_dir(soc)
                staging = self.tmp / f"staging_{soc}"
                staging.mkdir(exist_ok=True)
                _copy_template_to_staging(tpl, staging)
                for fname in _FORBIDDEN_ROOT_BATS:
                    self.assertFalse((staging / fname).is_file())


# ── Full round-trip: generate BAT → validate ─────────────────────────────────

class TestRoundTrip(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _do_roundtrip(self, available_imgs, soc):
        staging = self.tmp / soc
        staging.mkdir()
        # Copy template binaries
        tpl = _select_template_dir(soc)
        _copy_template_to_staging(tpl, staging)
        # Copy fake images
        img_dir = staging / "images"
        img_dir.mkdir(exist_ok=True)
        for img in available_imgs:
            (img_dir / img).write_bytes(b"FAKE")
        # Generate BAT
        flash_cmds, skipped = _gen_install_bat(
            staging, available_imgs, soc, "testdev", "v1", "14", "Global"
        )
        return staging, flash_cmds, skipped

    def test_mtk_roundtrip_bat_validates(self):
        _, flash_cmds, _ = self._do_roundtrip(
            {"super.img", "vbmeta.img", "boot.img"}, "mtk"
        )
        staging = self.tmp / "mtk"
        errors = _validate_template_bat(staging, "mtk")
        self.assertEqual(errors, [])

    def test_sd_roundtrip_bat_validates(self):
        _, flash_cmds, _ = self._do_roundtrip(
            {"super.img", "vbmeta.img", "boot.img"}, "snapdragon"
        )
        staging = self.tmp / "snapdragon"
        errors = _validate_template_bat(staging, "snapdragon")
        self.assertEqual(errors, [])

    def test_mtk_roundtrip_images_referenced_exist(self):
        available = {"super.img", "vbmeta.img", "boot.img"}
        staging, _, _ = self._do_roundtrip(available, "mtk")
        bat = (staging / "windows_install_and_format_data.bat").read_text(encoding="utf-8")
        for m in re.finditer(r'images\\([^\s"\']+\.img)', bat, re.IGNORECASE):
            img_ref = m.group(1)
            self.assertIn(img_ref, available,
                          f"BAT references {img_ref} which was not in available images")

    def test_sd_roundtrip_images_referenced_exist(self):
        available = {"super.img", "vbmeta.img", "boot.img", "abl.img"}
        staging, _, _ = self._do_roundtrip(available, "snapdragon")
        bat = (staging / "windows_install_and_format_data.bat").read_text(encoding="utf-8")
        for m in re.finditer(r'images\\([^\s"\']+\.img)', bat, re.IGNORECASE):
            img_ref = m.group(1)
            self.assertIn(img_ref, available,
                          f"BAT references {img_ref} which was not in available images")

    def test_both_socs_produce_different_bats(self):
        available = {"super.img", "vbmeta.img", "boot.img"}
        for soc in ("mtk", "snapdragon"):
            staging = self.tmp / soc
            staging.mkdir(exist_ok=True)
        _gen_install_bat(self.tmp / "mtk", available, "mtk", "dev", "v1", "14", "CN")
        _gen_install_bat(self.tmp / "snapdragon", available, "snapdragon", "dev", "v1", "14", "CN")

        mtk_bat = (self.tmp / "mtk" / "windows_install_and_format_data.bat").read_text()
        sd_bat  = (self.tmp / "snapdragon" / "windows_install_and_format_data.bat").read_text()

        self.assertNotEqual(mtk_bat, sd_bat)
        self.assertIn("_ab", mtk_bat)
        self.assertNotIn("_ab", sd_bat)
        self.assertIn("_a", sd_bat)
        self.assertIn("_b", sd_bat)


if __name__ == "__main__":
    unittest.main(verbosity=2)
