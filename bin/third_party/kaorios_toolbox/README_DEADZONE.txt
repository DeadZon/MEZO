Kaorios Toolbox — DeadZone Integration
=======================================

This directory contains the Kaorios Toolbox assets integrated into the
DeadZone ROM build pipeline as a Stable/base feature.

Version:   2.0.4.0  (tag V2.0.4, build date 23-05-2026)
Source:    https://github.com/Wuang26/Kaorios-Toolbox
Guide:     Toolbox-docs/V2.0.3+ (see docs/ subdirectory)

Binary assets (APK, XML, classes.dex) are downloaded at build time by:
  bin/scripts/deadzone_kaorios_toolbox.py

The install.sh in bin/modfile/UpdateFile/DeadZone_KaoriosToolbox/ runs
for ALL DeadZone styles (Stable, Legend, and future) because this is a
base feature, not a Legend-exclusive feature.

Directory layout:
  app/                  KaoriosToolbox.apk
  permissions/          privapp_whitelist_com.kousei.kaorios.xml
  framework/            classes.dex  (Kaorios framework DEX)
  docs/V2.0.3+/         Integration guide and reference docs

Integration steps performed by deadzone_kaorios_toolbox.py:
  1. Validate / download assets
  2. Install APK  → system_ext/priv-app/KaoriosToolbox/  (fallback: product/)
  3. Install XML  → system_ext/etc/permissions/          (fallback: product/)
  4. Patch build.prop  (persist.sys.kaorios, ro.control_privapp_permissions)
  5. Inject classes.dex into framework.jar as next classesN.dex
  6. Apply V2.0.3+ smali hooks to framework.jar
  7. Apply V2.0.3+ SystemServer hook to services.jar

Reports are written to output/reports/kaorios_*.txt
