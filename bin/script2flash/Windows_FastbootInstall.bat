@echo off&setlocal enabledelayedexpansion
title DeadZone Stable ROM By MEZO Installer
cd %~dp0
set fastboot=bin\windows\fastboot.exe
if not exist "%fastboot%" set fastboot=fastboot
echo.
echo.[i] - Read this information before flashing
echo.
echo.1. DeadZone Stable ROM,like most other custom ROMS,requires an unlocked bootloader!If your device is NOT,please close this window.
echo.2. You have to choose carefully else you will LOST ALL DATA!
echo.3. THIS IS A FREE ROM!!!If you see someone sell or install this ROM for fees,please CONTACT MEZO NOW.
echo.4. We will NOT take responsibility if you brick your phone or lose all data while installing this ROM.
echo.5. Make sure you have downloaded the exact build for your device, else you might get bricked.

echo.[i] - If you have read and agreed to all of the above,press any key to start the installation.
echo.[i] - Else, exit this window.
pause >NUL 2>NUL
echo.=========================================================================================
echo. Please Choose Format Option Before Flash ROM
echo.
echo.   y = Format All Data(Clean Flash)
echo.   n = Keep Data And Document(Dirty Flash)
echo.
echo.=========================================================================================
set /p CHOICE="Your choice {y/n}: "
echo.=========================================================================================
echo.Make Sure Your Devices Is On Fastboot Mode
echo.If It Still Not Detect Please Install Driver
echo.And Try Again...
echo.=========================================================================================

for /f "tokens=2" %%a in ('!fastboot! getvar slot-count 2^>^&1 ^| findstr /l /b /c:"slot-count:"') do set fqlx=%%a
if "!fqlx!" == "2" (set fqlx=AB)  else (set fqlx=A)

:: BEGIN MEZO GENERATED IMAGE FLASH COMMANDS
:: END MEZO GENERATED IMAGE FLASH COMMANDS

if /I "%CHOICE%" == "y" (
	echo.  Formatting...
	!fastboot! erase frp  >NUL 2>NUL
	!fastboot! erase userdata  >NUL 2>NUL
	!fastboot! erase metadata  >NUL 2>NUL
	echo.
)

echo.  All done,Your Devices Is Automatic Restart...
echo.  Now Wait For 10-15 Min For Booting
echo.
echo.
if !fqlx! == AB (!fastboot! set_active a  >NUL 2>NUL)
!fastboot! reboot
pause
exit
