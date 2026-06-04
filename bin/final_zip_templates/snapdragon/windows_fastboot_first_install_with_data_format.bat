@echo off
cd %~dp0
set fastboot=bin\windows\fastboot.exe
if not exist %fastboot% echo %fastboot% not found. & pause & exit /B 1
echo Waiting for device...
set device=unknown
for /f "tokens=2" %%D in ('%fastboot% getvar product 2^>^&1 ^| findstr /l /b /c:"product:"') do set device=%%D
if "%device%" neq "garnet" echo Compatible devices: garnet & echo Your device: %device% & pause & exit /B 1

echo You are going to wipe your data and internal storage.
echo It will delete all your files and photos stored on internal storage.
set /p choice=Do you agree? (Y/N) 
if /i "%choice%" neq "y" exit /B 0

echo ##################################################################
echo Please wait. The device will reboot when installation is finished.
echo ##################################################################
%fastboot% set_active a
%fastboot% flash abl_ab images\abl.img
%fastboot% flash aop_ab images\aop.img
%fastboot% flash aop_config_ab images\aop_config.img
%fastboot% flash bluetooth_ab images\bluetooth.img
%fastboot% flash cpucp_ab images\cpucp.img
%fastboot% flash devcfg_ab images\devcfg.img
%fastboot% flash dsp_ab images\dsp.img
%fastboot% flash dtbo_ab images\dtbo.img
%fastboot% flash featenabler_ab images\featenabler.img
%fastboot% flash hyp_ab images\hyp.img
%fastboot% flash imagefv_ab images\imagefv.img
%fastboot% flash keymaster_ab images\keymaster.img
%fastboot% flash modem_ab images\modem.img
%fastboot% flash qupfw_ab images\qupfw.img
%fastboot% flash shrm_ab images\shrm.img
%fastboot% flash tz_ab images\tz.img
%fastboot% flash uefi_ab images\uefi.img
%fastboot% flash uefisecapp_ab images\uefisecapp.img
%fastboot% flash vbmeta_ab images\vbmeta.img
%fastboot% flash vbmeta_system_ab images\vbmeta_system.img
%fastboot% flash xbl_ab images\xbl.img
%fastboot% flash xbl_config_ab images\xbl_config.img
%fastboot% flash xbl_ramdump_ab images\xbl_ramdump.img
%fastboot% flash boot_ab images\boot.img
%fastboot% flash vendor_boot_ab images\vendor_boot.img
%fastboot% flash super images\super.img
%fastboot% erase metadata
%fastboot% erase userdata
%fastboot% reboot
