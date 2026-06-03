@echo off
chcp 65001 >nul
cd /d "%~dp0"
color 0B
title DeadZone Snapdragon Installer
cls

set "fastboot=bin\windows\fastboot.exe"
set "ROM_STYLE=DeadZone Stable"
set "ROM_DEVELOPER=MEZO"
set "ROM_VERSION=CN_VERSION_FROM_ROM"
set "ROM_DEVICE=DEVICE_FROM_ROM"
set "ROM_ANDROID=ANDROID_FROM_ROM"
set "ROM_REGION=REGION_FROM_ROM"
set "COMPATIBLE_DEVICES=DEVICE_LIST_FROM_ROM"

if not exist "%fastboot%" (
    echo [ERROR] fastboot not found: %fastboot%
    pause
    exit /B 1
)

echo.
echo ================================================================
echo        DeadZone Snapdragon Installer  ^|  by MEZO
echo ================================================================
echo.
echo  [ROM] Style      : %ROM_STYLE%
echo  [ROM] Developer  : %ROM_DEVELOPER%
echo  [ROM] Version    : %ROM_VERSION%
echo  [ROM] Device     : %ROM_DEVICE%
echo  [ROM] Android    : Android %ROM_ANDROID%
echo  [ROM] Region     : %ROM_REGION%
echo.
echo ================================================================
echo.
echo  [i] Read this information before flashing:
echo.
echo  1. DeadZone ROM requires an UNLOCKED bootloader.
echo     Close this window if your bootloader is NOT unlocked.
echo  2. This will ERASE ALL your data. Proceed carefully.
echo  3. DeadZone ROM is FREE. If anyone charges you for it,
echo     contact MEZO immediately.
echo  4. MEZO Team is NOT responsible for bricks or data loss.
echo  5. Make sure this ROM build is for YOUR specific device.
echo.
echo  [i] If you agree to all of the above, press any key to continue.
echo  [i] Otherwise, close this window now.
echo.
pause >nul

echo Waiting for device...
set "device="
for /f "tokens=2" %%A in ('"%fastboot%" getvar product 2^>^&1 ^| findstr "\<product:"') do set "device=%%A"
if "%device%" equ "" echo Your device could not be detected. & pause & exit /B 1

echo Your device: %device%
echo Compatible devices: %COMPATIBLE_DEVICES%

echo Your device will be flashed and the data partition will be formatted.
echo You will lose your apps, settings and files on internal storage.
echo Continue if you are flashing DeadZone ROM for the first time or downgrading.
set /p choice=Do you want to continue? [y/N]
if /i "%choice%" neq "y" exit /B 0

echo ##############################################################
echo Please wait. The device will reboot once flashing is complete.
echo ##############################################################
%fastboot% set_active a
%fastboot% flash abl_a images\abl.img
%fastboot% flash abl_b images\abl.img
%fastboot% flash bluetooth_a images\bluetooth.img
%fastboot% flash bluetooth_b images\bluetooth.img
%fastboot% flash devcfg_a images\devcfg.img
%fastboot% flash devcfg_b images\devcfg.img
%fastboot% flash dsp_a images\dsp.img
%fastboot% flash dsp_b images\dsp.img
%fastboot% flash dtbo_a images\dtbo.img
%fastboot% flash dtbo_b images\dtbo.img
%fastboot% flash featenabler_a images\featenabler.img
%fastboot% flash featenabler_b images\featenabler.img
%fastboot% flash hyp_a images\hyp.img
%fastboot% flash hyp_b images\hyp.img
%fastboot% flash imagefv_a images\imagefv.img
%fastboot% flash imagefv_b images\imagefv.img
%fastboot% flash keymaster_a images\keymaster.img
%fastboot% flash keymaster_b images\keymaster.img
%fastboot% flash modem_a images\modem.img
%fastboot% flash modem_b images\modem.img
%fastboot% flash qupfw_a images\qupfw.img
%fastboot% flash qupfw_b images\qupfw.img
%fastboot% flash rpm_a images\rpm.img
%fastboot% flash rpm_b images\rpm.img
%fastboot% flash tz_a images\tz.img
%fastboot% flash tz_b images\tz.img
%fastboot% flash uefisecapp_a images\uefisecapp.img
%fastboot% flash uefisecapp_b images\uefisecapp.img
%fastboot% flash vbmeta_a images\vbmeta.img
%fastboot% flash vbmeta_b images\vbmeta.img
%fastboot% flash vbmeta_system_a images\vbmeta_system.img
%fastboot% flash vbmeta_system_b images\vbmeta_system.img
%fastboot% flash xbl_a images\xbl.img
%fastboot% flash xbl_b images\xbl.img
%fastboot% flash xbl_config_a images\xbl_config.img
%fastboot% flash xbl_config_b images\xbl_config.img
%fastboot% flash boot_a images\boot.img
%fastboot% flash boot_b images\boot.img
%fastboot% flash init_boot_a images\init_boot.img
%fastboot% flash init_boot_b images\init_boot.img
%fastboot% flash vendor_boot_a images\vendor_boot.img
%fastboot% flash vendor_boot_b images\vendor_boot.img
%fastboot% flash cust images\cust.img
%fastboot% flash super images\super.img
%fastboot% erase metadata
%fastboot% erase userdata
%fastboot% reboot
