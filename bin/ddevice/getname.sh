#!/bin/bash
work_dir=$(pwd)
source $work_dir/functions.sh

FILE_JSON1="$work_dir/bin/ddevice/data/devices.json"
FILE_JSON2="$work_dir/bin/ddevice/data/names.json"
KEY=$(cat $work_dir/bin/ddevice/device_f.txt)

if grep -qw "$1" "$work_dir/bin/ddevice/data/devices_data.txt"; then
  VALUE=$(jq -r --arg key "$KEY" '.[$key] // "Không tìm thấy key"' "$FILE_JSON1")
  echo "$VALUE" > $work_dir/bin/ddevice/name_devices.txt
else
  VALUE=$(jq -r --arg key "$KEY" '.[$key] // "Không tìm thấy key"' "$FILE_JSON2")
  echo "$VALUE" > $work_dir/bin/ddevice/name_devices.txt
fi