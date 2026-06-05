baserom="$1"
work_dir=$(pwd)
# Import functions
tools_dir=${work_dir}/bin/$(uname)/$(uname -m)export PATH=$(pwd)/bin/$(uname)/$(uname -m)/:$PATH
chmod 777 ${work_dir}/bin/*
chmod 777 ${work_dir}/bin/Linux/x86_64/*
source $work_dir/functions.sh
if [[ $(git branch --show-current) == "beta" ]]; then
    polyxver="$(cat Version)"
	status="Development"
else
    polyxver="$(cat Version)"
	status="Official"
fi

check unzip aria2c 7z zip java zipalign python3 zstd bc xmlstarlet aapt

rm -rf $work_dir/out
rm -rf $work_dir/build

source "$work_dir/bin/ddevice/getROM.sh" "$baserom"

if unzip -l ${baserom} | grep -q "payload.bin"; then
    baserom_type="payload"
    echo $baserom_type > $work_dir/bin/ddevice/romtype.txt
    unpack "Found payload.bin file"
    super_list="vendor mi_ext odm odm_dlkm system system_dlkm vendor_dlkm product product_dlkm system_ext"
    unpack "ROM validation passed."
elif unzip -l ${baserom} | grep -q "br$";then
    baserom_type="br"
    echo $baserom_type > $work_dir/bin/ddevice/romtype.txt
    super_list="system vendor product odm system_ext mi_ext"
    unpack "Found broli file"
    unpack "ROM validation passed."
elif unzip -l ${baserom} | grep -q "images/super.img*"; then
    unpack "Found super.img.* files"
    is_base_rom_eu=true
    unpack "ROM validation passed."
else
    error "Unpack failed"
    exit 1
fi

rm -rf app
rm -rf tmp
rm -rf config
rm -rf build/baserom/
find . -type d -name 'miui_*' | xargs rm -rf

unpack "Files cleaned up."
mkdir -p build/baserom/images/

# Extract partitions
if [[ ${baserom_type} == 'payload' ]]; then
    unpack "Extracting files payload.bin..."
    unzip ${baserom} payload.bin -d build/baserom >/dev/null 2>&1 || error "Extracting payload.bin error"
    unpack "File payload.bin extracted."
elif [[ ${baserom_type} == 'br' ]];then
    unpack "Extracting files *.new.dat.br"
    unzip ${baserom} -d build/baserom >/dev/null 2>&1 || error "Extracting new.dat.br error"
    unpack "File new.dat.br extracted."
elif [[ ${is_base_rom_eu} == true ]];then
    unpack "Extracting files from BASETROM [super.img]"
    unzip ${baserom} 'images/*' -d build/baserom >  /dev/null 2>&1 ||error "Extracting [super.img] error"
    unpack "Merging super.img.* into super.img (detecting sparse/raw)"
    _super_chunks=$(ls build/baserom/images/super.img.* 2>/dev/null | sort)
    if [ -z "$_super_chunks" ]; then
        error "No super.img.* chunks found after unzip!"
        exit 1
    fi
    python3 bin/scripts/image_utils.py merge \
        --dst build/baserom/images/super.img \
        --simg2img "$(pwd)/bin/Linux/x86_64/simg2img" \
        $_super_chunks \
        || { error "super.img merge failed — see [IMAGE] lines above for sparse/raw details"; exit 1; }
    rm -rf build/baserom/images/super.img.*
    mv build/baserom/images/super.img build/baserom/super.img
    unpack "[super.img] extracted."
    if [[ -f build/baserom/images/cust.img.0 ]];then
        _cust_chunks=$(ls build/baserom/images/cust.img.* 2>/dev/null | sort)
        python3 bin/scripts/image_utils.py merge \
            --dst build/baserom/images/cust.img \
            --simg2img "$(pwd)/bin/Linux/x86_64/simg2img" \
            $_cust_chunks \
            || { error "cust.img merge failed — see [IMAGE] lines above for details"; exit 1; }
        rm -rf build/baserom/images/cust.img.*
    fi
fi

if [[ ${baserom_type} == 'payload' ]]; then
    unpack "Unpacking payload.bin"
    payload-dumper-go -o build/baserom/images/ build/baserom/payload.bin >/dev/null 2>&1 || error "Unpacking payload.bin failed"    
elif [[ ${baserom_type} == 'br' ]];then
    super_list=$(cat build/baserom/dynamic_partitions_op_list | grep "add " | awk '{ print $2 }')
    unpack "Unpacking new.dat.br"
        for brotlipart in ${super_list}; do 
            brotli -d build/baserom/$brotlipart.new.dat.br >/dev/null 2>&1
            python3 $work_dir/bin/Linux/x86_64/sdat2img.py build/baserom/$brotlipart.transfer.list build/baserom/$brotlipart.new.dat build/baserom/images/$brotlipart.img >/dev/null 2>&1
            rm -rf build/baserom/$brotlipart.new.dat* build/baserom/$brotlipart.transfer.list build/baserom/$brotlipart.patch.*
        done
elif [[ ${is_base_rom_eu} == true ]];then
    unpack "Unpacking BASEROM [super.img]"
    super_list=$(python3 bin/lpunpack.py --info build/baserom/super.img | grep "super:" | awk '{ print $5 }')
    for i in ${super_list}; do
        if [[ $i == *_a ]];then
            i=${i%_a}
            python3 bin/lpunpack.py -p ${i}_a build/baserom/super.img build/baserom/images >/dev/null 2>&1
            mv build/baserom/images/${i}_a.img build/baserom/images/${i}.img 
        else
            python3 bin/lpunpack.py -p ${i} build/baserom/super.img build/baserom/images >/dev/null 2>&1
        fi
    done
    super_list=$(echo $super_list | sed 's/_a//g')
fi

for part in ${super_list}; do
    extract_partition $work_dir/build/baserom/images/${part}.img $work_dir/build/baserom/images
    PACK_TYPE=$(cat $work_dir/bin/ddevice/fstype.txt)
done
echo $device_f > $work_dir/bin/ddevice/device_f.txt
getvar=$(cat $work_dir/bin/ddevice/device_f.txt)

rm -rf config

if [ -f $work_dir/${baserom}.zip ]; then
    rm -rf ${baserom}.zip
fi

rm -rf build/baserom/payload.bin
rm -rf build/baserom/images/super.img


mods "Gathering Devices Infomations"
bash $work_dir/bin/ddevice/getname.sh $getvar
bash $work_dir/bin/ddevice/fetchINFO.sh
bash $work_dir/bin/ddevice/DEBLOAT/debloat.sh
info "Done"

bash $work_dir/bin/modfile/OS1/insmod.sh
bash $work_dir/bin/modfile/OS2/insmod.sh
bash $work_dir/bin/modfile/OS3/insmod.sh
bash $work_dir/bin/modfile/Universal/insfile.sh
bash $work_dir/bin/modfile/UpdateFile/insupdate.sh

# ── Style-specific mods ───────────────────────────────────────────────────────
_DZ_STYLE_ID="${DZ_STYLE_ID:-stable}"
case "${_DZ_STYLE_ID,,}" in
    stable) _DZ_STYLE_DIR="Stable" ;;
    legend) _DZ_STYLE_DIR="Legend" ;;
    *)
        echo "[STYLE] ERROR: Unsupported DeadZone style: ${_DZ_STYLE_ID}"
        exit 1
        ;;
esac
_DZ_STYLE_SCRIPT="$work_dir/bin/modfile/Styles/${_DZ_STYLE_DIR}/insmod.sh"
if [[ -f "$_DZ_STYLE_SCRIPT" ]]; then
    echo "[STYLE] Applying ${_DZ_STYLE_DIR} style mods..."
    bash "$_DZ_STYLE_SCRIPT"
else
    echo "[STYLE] No style mod script found at: $_DZ_STYLE_SCRIPT (skipping)"
fi
unset _DZ_STYLE_ID _DZ_STYLE_DIR _DZ_STYLE_SCRIPT

bash $work_dir/bin/package/patchpackage.sh

find "$work_dir/build/baserom/images/" -exec touch -t 200901010000.00 {} + 2> /dev/null || true

