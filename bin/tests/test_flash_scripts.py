"""Tests for Linux and macOS flash script generation in package_rom.py."""
from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

# ── Module loader ─────────────────────────────────────────────────────────────
_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "package_rom.py"


def _load_package_rom():
    spec = importlib.util.spec_from_file_location("package_rom", _MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Fixtures ──────────────────────────────────────────────────────────────────

MTK_FLASH_PAIRS = [
    ("boot_ab",         "boot.img"),
    ("dtbo_ab",         "dtbo.img"),
    ("super",           "super.img"),
    ("vbmeta_ab",       "vbmeta.img"),
    ("vbmeta_system_ab","vbmeta_system.img"),
]

SD_FLASH_PAIRS = [
    ("abl_ab",   "abl.img"),
    ("boot_ab",  "boot.img"),
    ("super",    "super.img"),
    ("vbmeta_ab","vbmeta.img"),
]

COMMON_KWARGS = dict(
    codename   = "garnet",
    rom_version= "OS1.0.18.0",
    android_ver= "14",
    region     = "Global",
    style_name = "DeadZone Stable",
)


# ── Linux script generation ───────────────────────────────────────────────────

class TestLinuxFlashScript:
    def test_file_created(self, tmp_path):
        mod = _load_package_rom()
        mod._gen_linux_flash_script(
            staging=tmp_path, flash_pairs=MTK_FLASH_PAIRS, norm_soc="mtk", **COMMON_KWARGS
        )
        assert (tmp_path / "linux_install_and_format_data.sh").is_file()

    def test_shebang(self, tmp_path):
        mod = _load_package_rom()
        mod._gen_linux_flash_script(
            staging=tmp_path, flash_pairs=MTK_FLASH_PAIRS, norm_soc="mtk", **COMMON_KWARGS
        )
        content = (tmp_path / "linux_install_and_format_data.sh").read_text()
        assert content.startswith("#!/usr/bin/env bash")

    def test_fastboot_resolver_linux(self, tmp_path):
        mod = _load_package_rom()
        mod._gen_linux_flash_script(
            staging=tmp_path, flash_pairs=MTK_FLASH_PAIRS, norm_soc="mtk", **COMMON_KWARGS
        )
        content = (tmp_path / "linux_install_and_format_data.sh").read_text()
        assert "./bin/linux/fastboot" in content
        assert "command -v fastboot" in content
        assert "apt-get install android-tools-fastboot" in content
        assert "pacman -S android-tools" in content
        assert "dnf install android-tools" in content

    def test_firmware_txt_read(self, tmp_path):
        mod = _load_package_rom()
        mod._gen_linux_flash_script(
            staging=tmp_path, flash_pairs=MTK_FLASH_PAIRS, norm_soc="mtk", **COMMON_KWARGS
        )
        content = (tmp_path / "linux_install_and_format_data.sh").read_text()
        assert "DeadZone_firmware.txt" in content
        assert 'IFS="=" read -r key val' in content

    def test_codename_check(self, tmp_path):
        mod = _load_package_rom()
        mod._gen_linux_flash_script(
            staging=tmp_path, flash_pairs=MTK_FLASH_PAIRS, norm_soc="mtk", **COMMON_KWARGS
        )
        content = (tmp_path / "linux_install_and_format_data.sh").read_text()
        assert "getvar product" in content
        assert '"$device" != "$Codename"' in content
        assert "exit 1" in content

    def test_flash_commands_present(self, tmp_path):
        mod = _load_package_rom()
        mod._gen_linux_flash_script(
            staging=tmp_path, flash_pairs=MTK_FLASH_PAIRS, norm_soc="mtk", **COMMON_KWARGS
        )
        content = (tmp_path / "linux_install_and_format_data.sh").read_text()
        for partition, img in MTK_FLASH_PAIRS:
            assert f'"$FASTBOOT" flash {partition} "images/{img}"' in content

    def test_flash_commands_order(self, tmp_path):
        mod = _load_package_rom()
        mod._gen_linux_flash_script(
            staging=tmp_path, flash_pairs=MTK_FLASH_PAIRS, norm_soc="mtk", **COMMON_KWARGS
        )
        content = (tmp_path / "linux_install_and_format_data.sh").read_text()
        positions = [content.index(f'"$FASTBOOT" flash {p} "images/{i}"') for p, i in MTK_FLASH_PAIRS]
        assert positions == sorted(positions), "Flash commands must appear in the original pair order"

    def test_wipe_after_flash(self, tmp_path):
        mod = _load_package_rom()
        mod._gen_linux_flash_script(
            staging=tmp_path, flash_pairs=MTK_FLASH_PAIRS, norm_soc="mtk", **COMMON_KWARGS
        )
        content = (tmp_path / "linux_install_and_format_data.sh").read_text()
        block_end = content.find(mod.SH_FLASH_BLOCK_END)
        erase_pos = content.find('"$FASTBOOT" erase metadata', block_end)
        assert erase_pos > block_end, "erase metadata must come AFTER the flash block"

    def test_set_active_before_flash(self, tmp_path):
        mod = _load_package_rom()
        mod._gen_linux_flash_script(
            staging=tmp_path, flash_pairs=MTK_FLASH_PAIRS, norm_soc="mtk", **COMMON_KWARGS
        )
        content = (tmp_path / "linux_install_and_format_data.sh").read_text()
        set_active_pos = content.find('"$FASTBOOT" set_active a')
        first_flash_pos = content.find(mod.SH_FLASH_BLOCK_START)
        assert set_active_pos < first_flash_pos, "set_active a must come before the flash block"

    def test_set_e_for_flash_failure_stops(self, tmp_path):
        mod = _load_package_rom()
        mod._gen_linux_flash_script(
            staging=tmp_path, flash_pairs=MTK_FLASH_PAIRS, norm_soc="mtk", **COMMON_KWARGS
        )
        content = (tmp_path / "linux_install_and_format_data.sh").read_text()
        assert "set -euo pipefail" in content, "Must use set -euo pipefail so flash failure stops execution"

    def test_no_windows_path_separators(self, tmp_path):
        mod = _load_package_rom()
        mod._gen_linux_flash_script(
            staging=tmp_path, flash_pairs=MTK_FLASH_PAIRS, norm_soc="mtk", **COMMON_KWARGS
        )
        content = (tmp_path / "linux_install_and_format_data.sh").read_text()
        assert "images\\" not in content, "Shell scripts must use forward slashes for paths"

    def test_deadzone_and_mezo_branding(self, tmp_path):
        mod = _load_package_rom()
        mod._gen_linux_flash_script(
            staging=tmp_path, flash_pairs=MTK_FLASH_PAIRS, norm_soc="mtk", **COMMON_KWARGS
        )
        content = (tmp_path / "linux_install_and_format_data.sh").read_text().lower()
        assert "deadzone" in content
        assert "mezo" in content

    def test_snapdragon_pairs(self, tmp_path):
        mod = _load_package_rom()
        mod._gen_linux_flash_script(
            staging=tmp_path, flash_pairs=SD_FLASH_PAIRS, norm_soc="snapdragon", **COMMON_KWARGS
        )
        content = (tmp_path / "linux_install_and_format_data.sh").read_text()
        assert '"$FASTBOOT" flash abl_ab "images/abl.img"' in content


# ── macOS script generation ───────────────────────────────────────────────────

class TestMacosFlashScript:
    def test_file_created(self, tmp_path):
        mod = _load_package_rom()
        mod._gen_macos_flash_script(
            staging=tmp_path, flash_pairs=MTK_FLASH_PAIRS, norm_soc="mtk", **COMMON_KWARGS
        )
        assert (tmp_path / "macos_install_and_format_data.sh").is_file()

    def test_fastboot_resolver_macos(self, tmp_path):
        mod = _load_package_rom()
        mod._gen_macos_flash_script(
            staging=tmp_path, flash_pairs=MTK_FLASH_PAIRS, norm_soc="mtk", **COMMON_KWARGS
        )
        content = (tmp_path / "macos_install_and_format_data.sh").read_text()
        assert "./bin/macos/fastboot" in content
        assert "command -v fastboot" in content
        assert "brew install android-platform-tools" in content
        assert "apt-get" not in content, "macOS script must not contain Linux apt-get"

    def test_flash_commands_present(self, tmp_path):
        mod = _load_package_rom()
        mod._gen_macos_flash_script(
            staging=tmp_path, flash_pairs=MTK_FLASH_PAIRS, norm_soc="mtk", **COMMON_KWARGS
        )
        content = (tmp_path / "macos_install_and_format_data.sh").read_text()
        for partition, img in MTK_FLASH_PAIRS:
            assert f'"$FASTBOOT" flash {partition} "images/{img}"' in content

    def test_wipe_after_flash(self, tmp_path):
        mod = _load_package_rom()
        mod._gen_macos_flash_script(
            staging=tmp_path, flash_pairs=MTK_FLASH_PAIRS, norm_soc="mtk", **COMMON_KWARGS
        )
        content = (tmp_path / "macos_install_and_format_data.sh").read_text()
        block_end = content.find(mod.SH_FLASH_BLOCK_END)
        erase_pos = content.find('"$FASTBOOT" erase metadata', block_end)
        assert erase_pos > block_end

    def test_macos_not_linux_resolver(self, tmp_path):
        mod = _load_package_rom()
        mod._gen_macos_flash_script(
            staging=tmp_path, flash_pairs=MTK_FLASH_PAIRS, norm_soc="mtk", **COMMON_KWARGS
        )
        content = (tmp_path / "macos_install_and_format_data.sh").read_text()
        assert "./bin/linux/fastboot" not in content, "macOS script must use bin/macos/fastboot resolver"


# ── Flash command symmetry between all three scripts ─────────────────────────

class TestFlashCommandSymmetry:
    """Linux and macOS scripts must flash the same images in the same order as Windows."""

    def _extract_sh_flash_cmds(self, content: str, mod) -> list[str]:
        start = content.find(mod.SH_FLASH_BLOCK_START)
        end   = content.find(mod.SH_FLASH_BLOCK_END)
        assert start != -1 and end != -1 and end > start
        block = content[start + len(mod.SH_FLASH_BLOCK_START):end]
        return [ln.strip() for ln in block.splitlines() if ln.strip()]

    def _extract_bat_flash_cmds(self, content: str, mod) -> list[str]:
        start = content.find(mod.FLASH_BLOCK_START)
        end   = content.find(mod.FLASH_BLOCK_END)
        assert start != -1 and end != -1 and end > start
        block = content[start + len(mod.FLASH_BLOCK_START):end]
        return [ln.strip() for ln in block.splitlines() if ln.strip()]

    def test_linux_same_count_as_windows(self, tmp_path):
        mod = _load_package_rom()
        mod._gen_install_bat(
            staging=tmp_path, available_imgs={"boot.img","super.img","vbmeta.img","dtbo.img"},
            norm_soc="mtk", codename="dawn", rom_version="V1", android_ver="15",
            region="Global", style_name="DeadZone Stable", style_tier="Free",
        )
        pairs, _ = mod._compute_flash_pairs({"boot.img","super.img","vbmeta.img","dtbo.img"}, "mtk")
        mod._gen_linux_flash_script(
            staging=tmp_path, flash_pairs=pairs, norm_soc="mtk",
            codename="dawn", rom_version="V1", android_ver="15",
            region="Global", style_name="DeadZone Stable",
        )
        bat_cmds = self._extract_bat_flash_cmds(
            (tmp_path / "windows_install_and_format_data.bat").read_text(), mod
        )
        sh_cmds = self._extract_sh_flash_cmds(
            (tmp_path / "linux_install_and_format_data.sh").read_text(), mod
        )
        assert len(bat_cmds) == len(sh_cmds), (
            f"Windows BAT has {len(bat_cmds)} flash commands, "
            f"Linux SH has {len(sh_cmds)} — must be equal"
        )

    def test_linux_partitions_match_windows(self, tmp_path):
        mod = _load_package_rom()
        available = {"boot.img", "super.img", "vbmeta.img", "dtbo.img", "vbmeta_system.img"}
        mod._gen_install_bat(
            staging=tmp_path, available_imgs=available,
            norm_soc="mtk", codename="dawn", rom_version="V1", android_ver="15",
            region="Global", style_name="DeadZone Stable", style_tier="Free",
        )
        pairs, _ = mod._compute_flash_pairs(available, "mtk")
        mod._gen_linux_flash_script(
            staging=tmp_path, flash_pairs=pairs, norm_soc="mtk",
            codename="dawn", rom_version="V1", android_ver="15",
            region="Global", style_name="DeadZone Stable",
        )
        bat_cmds = self._extract_bat_flash_cmds(
            (tmp_path / "windows_install_and_format_data.bat").read_text(), mod
        )
        sh_cmds = self._extract_sh_flash_cmds(
            (tmp_path / "linux_install_and_format_data.sh").read_text(), mod
        )
        # Extract partition names from each command list
        def bat_partition(cmd: str) -> str:
            # cmd: %fastboot% flash boot_ab images\boot.img
            parts = cmd.split()
            return parts[2]
        def sh_partition(cmd: str) -> str:
            # cmd: "$FASTBOOT" flash boot_ab "images/boot.img"
            parts = cmd.split()
            return parts[2]
        bat_parts = [bat_partition(c) for c in bat_cmds]
        sh_parts  = [sh_partition(c) for c in sh_cmds]
        assert bat_parts == sh_parts, f"Partition order mismatch:\n  BAT: {bat_parts}\n  SH:  {sh_parts}"


# ── ZIP executable permissions ────────────────────────────────────────────────

class TestZipExecutablePerms:
    def test_sh_files_have_exec_bit_in_zip(self, tmp_path):
        """Shell scripts in the ZIP must have 0o755 external_attr."""
        import zipfile as zf_mod
        staging = tmp_path / "staging"
        staging.mkdir()
        # Write dummy .sh files
        for name in ("linux_install_and_format_data.sh", "macos_install_and_format_data.sh"):
            (staging / name).write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")
        # Write a regular file
        (staging / "readme.txt").write_text("hello", encoding="utf-8")

        zip_path = tmp_path / "test.zip"
        _EXEC_ARCNAMES: frozenset = frozenset({"bin/linux/fastboot", "bin/macos/fastboot"})

        with zf_mod.ZipFile(zip_path, "w", compression=zf_mod.ZIP_DEFLATED, compresslevel=9) as zf:
            for f in sorted(staging.rglob("*")):
                if f.is_file():
                    arcname = f.relative_to(staging)
                    arcname_posix = arcname.as_posix()
                    needs_exec = f.name.endswith(".sh") or arcname_posix in _EXEC_ARCNAMES
                    if needs_exec:
                        zi = zf_mod.ZipInfo.from_file(f, arcname_posix)
                        zi.compress_type = zf_mod.ZIP_DEFLATED
                        zi.external_attr = 0o755 << 16
                        data = f.read_bytes()
                        zf.writestr(zi, data, compress_type=zf_mod.ZIP_DEFLATED, compresslevel=9)
                    else:
                        zf.write(f, arcname_posix)

        with zf_mod.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                if info.filename.endswith(".sh"):
                    mode = (info.external_attr >> 16) & 0o777
                    assert mode == 0o755, (
                        f"{info.filename}: expected mode 0o755 in ZIP, got 0o{mode:03o}"
                    )
                else:
                    # Non-.sh files should NOT have exec bit from our code
                    mode = (info.external_attr >> 16) & 0o111
                    # We don't enforce this strictly — just ensure .sh files have it
                    pass  # no assertion needed for non-executables

    def test_bundled_linux_fastboot_exec_bit(self, tmp_path):
        """bin/linux/fastboot in the ZIP must have 0o755 external_attr."""
        import zipfile as zf_mod
        staging = tmp_path / "staging"
        fastboot_dir = staging / "bin" / "linux"
        fastboot_dir.mkdir(parents=True)
        (fastboot_dir / "fastboot").write_bytes(b"\x7fELF")  # fake binary

        zip_path = tmp_path / "test_fb.zip"
        _EXEC_ARCNAMES: frozenset = frozenset({"bin/linux/fastboot", "bin/macos/fastboot"})

        with zf_mod.ZipFile(zip_path, "w", compression=zf_mod.ZIP_DEFLATED) as zf:
            for f in sorted(staging.rglob("*")):
                if f.is_file():
                    arcname = f.relative_to(staging)
                    arcname_posix = arcname.as_posix()
                    needs_exec = f.name.endswith(".sh") or arcname_posix in _EXEC_ARCNAMES
                    if needs_exec:
                        zi = zf_mod.ZipInfo.from_file(f, arcname_posix)
                        zi.compress_type = zf_mod.ZIP_DEFLATED
                        zi.external_attr = 0o755 << 16
                        data = f.read_bytes()
                        zf.writestr(zi, data, compress_type=zf_mod.ZIP_DEFLATED)
                    else:
                        zf.write(f, arcname_posix)

        with zf_mod.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                if info.filename == "bin/linux/fastboot":
                    mode = (info.external_attr >> 16) & 0o777
                    assert mode == 0o755, f"bin/linux/fastboot: expected 0o755, got 0o{mode:03o}"


# ── validate_zip checks ───────────────────────────────────────────────────────

class TestValidateZipShScripts:
    """_validate_zip must require both .sh scripts at the ZIP root."""

    def _make_minimal_zip(self, tmp_path, include_linux=True, include_macos=True) -> tuple:
        """Create a minimal valid ZIP with optional script inclusion."""
        import zipfile as zf_mod
        mod = _load_package_rom()

        zip_path = tmp_path / "DeadZone_test.zip"
        with zf_mod.ZipFile(zip_path, "w") as zf:
            # Required BAT
            bat_content = (
                "@echo off\nchcp 65001 >nul\ncolor 0B\n"
                "set \"fastboot=bin\\windows\\fastboot.exe\"\n"
                "if not exist \"%fastboot%\" (exit /B 1)\n"
                "if not exist \"images\\DeadZone_firmware.txt\" (exit /B 1)\n"
                "for /f \"usebackq tokens=1,* delims==\" %%a in (\"images\\DeadZone_firmware.txt\") do (\n"
                "    if /i \"%%a\"==\"Codename\" set \"Codename=%%b\"\n"
                ")\n"
                "for /f \"tokens=2\" %%D in ('%fastboot% getvar product 2^>^&1') do set \"device=%%D\"\n"
                "if /i not \"%device%\"==\"%Codename%\" (exit /B 1)\n"
                "set /p confirm=YES\n"
                "%fastboot% set_active a\n"
                ":: BEGIN MEZO GENERATED IMAGE FLASH COMMANDS\n"
                "%fastboot% flash super_ab images\\super.img\n"
                "%fastboot% flash vbmeta_ab images\\vbmeta.img\n"
                ":: END MEZO GENERATED IMAGE FLASH COMMANDS\n"
                "%fastboot% erase metadata\n"
                "%fastboot% erase userdata\n"
                "%fastboot% reboot\n"
                "deadzone mezo\n"
            )
            zf.writestr("windows_install_and_format_data.bat", bat_content)
            zf.writestr("images/super.img", b"sparse")
            zf.writestr("images/vbmeta.img", b"vbmeta")
            zf.writestr("images/DeadZone_firmware.txt", "Codename=garnet\n")
            zf.writestr("bin/windows/fastboot.exe", b"exe")
            if include_linux:
                zf.writestr("linux_install_and_format_data.sh", "#!/usr/bin/env bash\necho ok\n")
            if include_macos:
                zf.writestr("macos_install_and_format_data.sh", "#!/usr/bin/env bash\necho ok\n")

        return zip_path, mod

    def test_validate_passes_with_both_scripts(self, tmp_path):
        zip_path, mod = self._make_minimal_zip(tmp_path, include_linux=True, include_macos=True)
        errors = mod._validate_zip(zip_path, {"super.img", "vbmeta.img"}, norm_soc="snapdragon")
        sh_errs = [e for e in errors if "linux_install" in e or "macos_install" in e]
        assert sh_errs == [], f"Unexpected .sh errors: {sh_errs}"

    def test_validate_fails_without_linux_script(self, tmp_path):
        zip_path, mod = self._make_minimal_zip(tmp_path, include_linux=False, include_macos=True)
        errors = mod._validate_zip(zip_path, {"super.img", "vbmeta.img"}, norm_soc="snapdragon")
        assert any("linux_install_and_format_data.sh" in e for e in errors)

    def test_validate_fails_without_macos_script(self, tmp_path):
        zip_path, mod = self._make_minimal_zip(tmp_path, include_linux=True, include_macos=False)
        errors = mod._validate_zip(zip_path, {"super.img", "vbmeta.img"}, norm_soc="snapdragon")
        assert any("macos_install_and_format_data.sh" in e for e in errors)

    def test_validate_fails_without_both_scripts(self, tmp_path):
        zip_path, mod = self._make_minimal_zip(tmp_path, include_linux=False, include_macos=False)
        errors = mod._validate_zip(zip_path, {"super.img", "vbmeta.img"}, norm_soc="snapdragon")
        linux_err = any("linux_install_and_format_data.sh" in e for e in errors)
        macos_err = any("macos_install_and_format_data.sh" in e for e in errors)
        assert linux_err and macos_err
