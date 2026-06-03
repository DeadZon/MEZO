@echo off
chcp 65001 >nul
cd /d "%~dp0"
color 0B
title DeadZone MTK Installer

set "fastboot=bin\windows\fastboot.exe"
set "ROM_STYLE=DeadZone Stable"
set "ROM_DEVELOPER=MEZO"
set "ROM_VERSION=CN_VERSION_FROM_ROM"
set "ROM_DEVICE=DEVICE_FROM_ROM"
set "ROM_ANDROID=ANDROID_FROM_ROM"
set "ROM_REGION=REGION_FROM_ROM"

if not exist "%fastboot%" echo %fastboot% not found. & pause & exit /B 1

echo.
echo ================================================================
echo                    DeadZone MTK Installer
echo ================================================================
echo.
echo [ROM] Style      : %ROM_STYLE%
echo [ROM] Developer  : %ROM_DEVELOPER%
echo [ROM] Version    : %ROM_VERSION%
echo [ROM] Device     : %ROM_DEVICE%
echo [ROM] Android    : %ROM_ANDROID%
echo [ROM] Region     : %ROM_REGION%
echo.
echo ================================================================
echo.
echo [i] - Read this information before flashing
echo.
echo 1. DeadZone Stable ROM, like most other custom ROMS, requires an unlocked bootloader! If your device is NOT, please close this window.
echo 2. You have to choose carefully else you will LOST ALL DATA!
echo 3. THIS IS A DeadZone ROM!!! If you see someone sell Our ROM It Only For DeadZone, please CONTACT MEZO NOW.
echo 4. We will NOT take responsibility if you brick your phone or lose all data while installing this ROM.
echo 5. Make sure you have downloaded the exact build for your device, else you might get bricked.
echo.
echo [i] - If you have read and agreed to all of the above, press any key to start the installation.
echo [i] - Else, exit this window.
echo.
pause >nul

echo Waiting for device...
set "device=unknown"
for /f "tokens=2" %%D in ('"%fastboot%" getvar product 2^>^&1 ^| findstr /l /b /c:"product:"') do set "device=%%D"

echo.
echo Detected device: %device%
echo You are going to wipe your data and internal storage.
echo It will delete all your files and photos stored on internal storage.
set /p choice=Do you agree? (Y/N) 
if /i "%choice%" neq "y" exit /B 0

echo ##################################################################
echo Please wait. The device will reboot when installation is finished.
echo ##################################################################
%fastboot% set_active a

%fastboot% flash apusys_ab images\apusys.img

%fastboot% flash audio_dsp_ab images\audio_dsp.img

%fastboot% flash boot_ab images\boot.img

%fastboot% flash ccu_ab images\ccu.img

%fastboot% flash connsys_bt_ab images\connsys_bt.img

%fastboot% flash connsys_gnss_ab images\connsys_gnss.img

%fastboot% flash connsys_wifi_ab images\connsys_wifi.img

%fastboot% flash dpm_ab images\dpm.img

%fastboot% flash dtbo_ab images\dtbo.img

%fastboot% flash gpueb_ab images\gpueb.img

%fastboot% flash gz_ab images\gz.img

%fastboot% flash init_boot_ab images\init_boot.img

%fastboot% flash lk_ab images\lk.img

%fastboot% flash logo_ab images\logo.img

%fastboot% flash mcf_ota_ab images\mcf_ota.img

%fastboot% flash mcupm_ab images\mcupm.img

%fastboot% flash md1img_ab images\md1img.img

%fastboot% flash mvpu_algo_ab images\mvpu_algo.img

%fastboot% flash pi_img_ab images\pi_img.img

%fastboot% flash preloader_raw_ab images\preloader_raw.img

%fastboot% flash scp_ab images\scp.img

%fastboot% flash spmfw_ab images\spmfw.img

%fastboot% flash sspm_ab images\sspm.img

%fastboot% flash tee_ab images\tee.img

%fastboot% flash vbmeta_ab images\vbmeta.img

%fastboot% flash vbmeta_system_ab images\vbmeta_system.img

%fastboot% flash vbmeta_vendor_ab images\vbmeta_vendor.img

%fastboot% flash vcp_ab images\vcp.img

%fastboot% flash vendor_boot_ab images\vendor_boot.img



%fastboot% flash super images\super.img




%fastboot% erase metadata
%fastboot% erase userdata
%fastboot% reboot
