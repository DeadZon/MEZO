work_dir=$(pwd)
source $work_dir/functions.sh
vendor="$work_dir/build/baserom/images/vendor"
odm="$work_dir/build/baserom/images/odm"

mods "Update Thermal Services to none-limit..."
# Modify thermal config
if ls "$vendor/etc/"*-normal.conf > /dev/null 2>&1; then
  for i in "$vendor/etc/"*-nolimit.conf; do
    cp -rf "$work_dir/bin/modfile/UpdateFile/ThermalServices/thermal.conf" "$i"
  done
  for i in "$vendor/etc/"*-tgame.conf; do
    cp -rf "$work_dir/bin/modfile/UpdateFile/ThermalServices/thermal.conf" "$i"
  done
  mods "Modified thermal configs"
elif ls "$odm/etc/"*-normal.conf > /dev/null 2>&1; then
  for i in "$odm/etc/"*-nolimit.conf; do
    cp -rf "$work_dir/bin/modfile/UpdateFile/ThermalServices/thermal.conf" "$i"
  done
  for i in "$odm/etc/"*-tgame.conf; do
    cp -rf "$work_dir/bin/modfile/UpdateFile/ThermalServices/thermal.conf" "$i"
  done
  mods "Modified thermal configs"
fi
mods "Done"