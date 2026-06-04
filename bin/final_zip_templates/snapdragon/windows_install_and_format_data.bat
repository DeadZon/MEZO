@echo off
cd %~dp0
set fastboot=bin\windows\fastboot.exe
set log_file=%~dp0installer_log.txt

if not exist %fastboot% echo [ERROR] %fastboot% not found. & pause & exit /B 1

:: Read ROM info from DeadZone_firmware.txt
set "Codename=unknown"
set "DeviceName=unknown"
set "ROM_VERSION=UNKNOWN"
set "ROM_ANDROID=UNKNOWN"
set "ROM_STYLE=DeadZone"
set "ROM_LICENSE=Free"
if exist "images\DeadZone_firmware.txt" (
    for /f "usebackq tokens=1,* delims==" %%a in ("images\DeadZone_firmware.txt") do (
        if /i "%%a"=="Codename"  set "Codename=%%b"
        if /i "%%a"=="Device"    set "DeviceName=%%b"
        if /i "%%a"=="version"   set "ROM_VERSION=%%b"
        if /i "%%a"=="Android"   set "ROM_ANDROID=%%b"
        if /i "%%a"=="Style"     set "ROM_STYLE=%%b"
        if /i "%%a"=="License"   set "ROM_LICENSE=%%b"
    )
)

echo.
echo ================================================================
echo              DEADZONE TEAM  ^|  by MEZO
echo          Based on China Firmware - Snapdragon ROM
echo ================================================================
echo.
echo  [ROM] Style    : %ROM_STYLE%
echo  [ROM] License  : %ROM_LICENSE%
echo  [ROM] Developer: MEZO
echo  [ROM] Version  : %ROM_VERSION%
echo  [ROM] Codename : %Codename%
echo  [ROM] Android  : Android %ROM_ANDROID%
echo  [ROM] SoC      : Snapdragon
echo.
echo ================================================================
echo.
echo  [i] Read this before flashing:
echo.
echo  1. UNLOCKED BOOTLOADER required.
echo     Close this window if your bootloader is NOT unlocked.
echo  2. This will ERASE ALL your data. Proceed carefully.
echo  3. DeadZone ROM is FREE. Contact MEZO if charged.
echo  4. MEZO is NOT responsible for bricks or data loss.
echo  5. This ROM is built for codename: %Codename%
echo.
echo  [i] Press any key to continue, or close to cancel.
echo.
pause >nul

echo Waiting for fastboot device...
set device=unknown
for /f "tokens=2" %%D in ('%fastboot% getvar product 2^>^&1 ^| findstr /l /b /c:"product:"') do set device=%%D
echo  Detected device: %device%

if /i not "%device%"=="%Codename%" (
    echo.
    echo [WARNING] Codename mismatch!
    echo  ROM expected : %Codename%
    echo  Device found : %device%
    echo.
    echo  Flashing the WRONG ROM may permanently BRICK your device!
    echo.
    setlocal enabledelayedexpansion
    set /p _confirm=Type YES to continue at your own risk, or press Enter to exit:
    if /i not "!_confirm!"=="YES" exit /B 1
    endlocal
)
echo  Device check passed: %device%

echo.
echo ##################################################################
echo Please wait. The device will reboot when installation is finished.
echo ##################################################################
echo %DATE% %TIME% DeadZone Install Start: %Codename% > "%log_file%"
%fastboot% set_active a

:: BEGIN MEZO GENERATED IMAGE FLASH COMMANDS
%fastboot% flash abl_ab images\abl.img
if errorlevel 1 ( echo [ERROR] FLASH FAILED: abl_ab & echo FAILED: abl_ab >> "%log_file%" & pause & exit /B 1 )
%fastboot% flash boot_ab images\boot.img
if errorlevel 1 ( echo [ERROR] FLASH FAILED: boot_ab & echo FAILED: boot_ab >> "%log_file%" & pause & exit /B 1 )
%fastboot% flash super images\super.img
if errorlevel 1 ( echo [ERROR] FLASH FAILED: super & echo FAILED: super >> "%log_file%" & pause & exit /B 1 )
:: END MEZO GENERATED IMAGE FLASH COMMANDS

echo.
echo All partitions flashed. Wiping data...
echo %DATE% %TIME% All flash OK >> "%log_file%"
%fastboot% erase metadata
%fastboot% erase userdata
%fastboot% reboot
