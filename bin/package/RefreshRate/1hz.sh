work_dir=$(pwd)
ANDROID_DEVICE=$(cat $work_dir/bin/ddevice/device_f.txt)
_GF_DIR="$work_dir/build/baserom/images/product/etc/device_features"
rom_os=$(cat $work_dir/bin/ddevice/rom_os.txt)
regionTYPE=$(cat $work_dir/bin/ddevice/device_type.txt)
str='<item>120</item>'
str1='<item>90</item>'
str2='<item>1</item>'
checkfps='<bool name="support_smart_fps">true</bool>'

# Collect XML files safely — avoids "binary operator expected" from glob expansion
_gf_files=()
if [ -d "$_GF_DIR" ]; then
    while IFS= read -r -d '' f; do
        _gf_files+=("$f")
    done < <(find "$_GF_DIR" -maxdepth 1 -name "*.xml" -print0 2>/dev/null)
fi

if [ "${#_gf_files[@]}" -eq 0 ]; then
    echo "[RefreshRate] No device_features/*.xml found — SKIPPED"
    exit 0
fi

for gfFile in "${_gf_files[@]}"; do
    echo "[RefreshRate] Patching: $(basename "$gfFile")"

    if [ "$(grep -c "$str" "$gfFile")" -eq '0' ]; then
        sed '/<item>144<\/item>/a\        <item>120<\/item>' "$gfFile" > "${gfFile}.new"
        mv "${gfFile}.new" "$gfFile"
        echo "Added 120hz to ${gfFile}"
    fi

    if [ "$(grep -c "$str1" "$gfFile")" -eq '0' ]; then
        sed '/<item>120<\/item>/a\        <item>90<\/item>' "$gfFile" > "${gfFile}.new"
        mv "${gfFile}.new" "$gfFile"
        echo "Added 90hz to ${gfFile}"
    fi

    if [ "$(grep -c "$str2" "$gfFile")" -eq '0' ]; then
        sed '/<item>60<\/item>/a\        <item>1<\/item>' "$gfFile" > "${gfFile}.new"
        mv "${gfFile}.new" "$gfFile"
        echo "Added 1hz to ${gfFile}"
    fi

    if [ "$(grep -c "$checkfps" "$gfFile")" -eq '0' ]; then
        sed '/<integer name="defaultFps">60<\/integer>/a\    <bool name="support_smart_fps">true<\/bool>\<integer name="smart_fps_value">120<\/integer>' "$gfFile" > "${gfFile}.new"
        mv "${gfFile}.new" "$gfFile"
        echo "Added SmartFPS to ${gfFile}"
    fi
done
