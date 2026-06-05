@echo off
chcp 65001 >nul
cd /d "%~dp0"
color 0B
title DeadZone Snapdragon Installer
cls

set "fastboot=bin\windows\fastboot.exe"

if not exist "%fastboot%" (
    echo fastboot not found: %fastboot%
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
if not exist "images\DeadZone_firmware.txt" (
    echo images\DeadZone_firmware.txt not found
    pause
    exit /B 1
)
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

echo.
echo ================================================================
echo            DeadZone Snapdragon Installer  ^|  by MEZO
echo ================================================================
echo.
echo  Style      : %ROM_STYLE%
echo  License    : %ROM_LICENSE%
echo  Developer  : %ROM_DEVELOPER%
echo  Version    : %ROM_VERSION%
echo  Device     : %ROM_DEVICE%
echo  Android    : Android %ROM_ANDROID%
echo  Region     : %ROM_REGION%
echo  SoC        : %ROM_SOC%
echo  Codename   : %Codename%
echo.
echo ================================================================
echo.
echo  1. Unlocked bootloader required.
echo     Close this window if your bootloader is NOT unlocked.
echo  2. This will erase ALL your data.
echo  3. DeadZone ROM is FREE. Contact MEZO if anyone charges you.
echo  4. MEZO is not responsible for bricks or data loss.
echo  5. Make sure this build is for your device.
echo.
pause

set "device=unknown"
for /f "tokens=2" %%D in ('%fastboot% getvar product 2^>^&1 ^| findstr /l /b /c:"product:"') do set "device=%%D"

echo  Detected : %device%
echo  Expected : %Codename%
echo.

if /i not "%device%"=="%Codename%" (
    echo.
    echo  ERROR: wrong device
    echo  ROM is for : %Codename%
    echo  Connected  : %device%
    echo.
    pause
    exit /B 1
)

set /p confirm=This will wipe ALL data. Type YES to continue:
if /i not "%confirm%"=="YES" exit /B 0

echo.
%fastboot% set_active a

:: BEGIN MEZO GENERATED IMAGE FLASH COMMANDS
:: (This section is replaced by the build system with actual ROM images)
:: END MEZO GENERATED IMAGE FLASH COMMANDS

%fastboot% erase metadata
%fastboot% erase userdata
%fastboot% reboot
