@echo off
chcp 65001 >nul
cd /d "%~dp0"
color 0B
title DeadZone Snapdragon Installer
cls

set "fastboot=bin\windows\fastboot.exe"
set "log_file=%~dp0installer_log.txt"

if not exist "%fastboot%" (
    echo [ERROR] fastboot not found: %fastboot%
    pause
    exit /B 1
)

:: Read ROM info from images\DeadZone_firmware.txt
set "Codename=unknown"
set "ROM_DEVICE=unknown"
set "ROM_VERSION=UNKNOWN"
set "ROM_ANDROID=UNKNOWN"
set "ROM_STYLE=DeadZone"
set "ROM_LICENSE=Free"
set "ROM_DEVELOPER=MEZO"
set "ROM_REGION=Unknown"
set "ROM_SOC=Unknown"
if exist "images\DeadZone_firmware.txt" (
    for /f "usebackq tokens=1,* delims==" %%a in ("images\DeadZone_firmware.txt") do (
        if /i "%%a"=="Codename"  set "Codename=%%b"
        if /i "%%a"=="Device"    set "ROM_DEVICE=%%b"
        if /i "%%a"=="version"   set "ROM_VERSION=%%b"
        if /i "%%a"=="Android"   set "ROM_ANDROID=%%b"
        if /i "%%a"=="Style"     set "ROM_STYLE=%%b"
        if /i "%%a"=="License"   set "ROM_LICENSE=%%b"
        if /i "%%a"=="Developer" set "ROM_DEVELOPER=%%b"
        if /i "%%a"=="Region"    set "ROM_REGION=%%b"
        if /i "%%a"=="SoC"       set "ROM_SOC=%%b"
    )
) else (
    echo [WARN] images\DeadZone_firmware.txt not found
)

echo.
echo ================================================================
echo            DeadZone Snapdragon Installer  ^|  by MEZO
echo ================================================================
echo.
echo  [ROM] Style      : %ROM_STYLE%
echo  [ROM] License    : %ROM_LICENSE%
echo  [ROM] Developer  : %ROM_DEVELOPER%
echo  [ROM] Version    : %ROM_VERSION%
echo  [ROM] Device     : %ROM_DEVICE%
echo  [ROM] Android    : Android %ROM_ANDROID%
echo  [ROM] Region     : %ROM_REGION%
echo  [ROM] SoC        : %ROM_SOC%
echo  [ROM] Codename   : %Codename%
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
set "device=unknown"
for /f "tokens=2" %%D in ('%fastboot% getvar product 2^>^&1 ^| findstr /l /b /c:"product:"') do set "device=%%D"

echo.
echo  Detected device : %device%
echo  Expected device : %Codename%
echo.

if /i not "%device%"=="%Codename%" (
    echo ============================================================
    echo  ERROR: WRONG DEVICE DETECTED
    echo  This ROM is built for : %Codename%
    echo  Your device reports   : %device%
    echo  DO NOT flash this ROM on the wrong device!
    echo  Exiting now.
    echo ============================================================
    pause
    exit /B 1
)

echo  Device verified: %device%
echo.
echo  You are going to WIPE YOUR DATA and flash the ROM.
echo  All apps, settings and files on internal storage will be erased.
echo.
set /p _final=Type YES to confirm and start flashing:
if /i not "%_final%"=="YES" exit /B 0

echo.
echo ##################################################################
echo Please wait. The device will reboot when installation is finished.
echo ##################################################################
echo %DATE% %TIME% DeadZone Install Start: %Codename% > "%log_file%"
%fastboot% set_active a

:: BEGIN MEZO GENERATED IMAGE FLASH COMMANDS
:: (This section is replaced by the build system with actual ROM images)
:: END MEZO GENERATED IMAGE FLASH COMMANDS

echo.
echo All partitions flashed. Wiping data...
echo %DATE% %TIME% All flash OK >> "%log_file%"
%fastboot% erase metadata
if errorlevel 1 ( echo [ERROR] erase metadata failed ^& pause ^& exit /B 1 )
%fastboot% erase userdata
if errorlevel 1 ( echo [ERROR] erase userdata failed ^& pause ^& exit /B 1 )
%fastboot% reboot
