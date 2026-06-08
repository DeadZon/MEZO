work_dir=$(pwd)
source $work_dir/functions.sh

mods "Add Package..."
target_dir="$work_dir/bin/package/"

bash $target_dir/COREPATCH/update.sh
bash $target_dir/DISABLE_AVB/DISABLEavb.sh

if [ -f "$target_dir/KouseiPatcher/update.sh" ]; then
    bash $target_dir/KouseiPatcher/update.sh
else
    echo "[package] KouseiPatcher not present — now handled by Lite style engine"
fi

if [ -f "$target_dir/NOTIFICATION_FIX/notificationFIX.sh" ]; then
    bash $target_dir/NOTIFICATION_FIX/notificationFIX.sh
else
    echo "[package] NOTIFICATION_FIX not present — skipping"
fi

bash $target_dir/RefreshRate/1hz.sh
mods "Add Package Done"
