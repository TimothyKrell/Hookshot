#!/bin/bash
# A development rebuild on Linux: this checkout's code, the builder's work folder (its lifted chunks and object cache),
# the extracted AppImage's toolchain. Only what changed is compiled: a host/ or gpu/vk change relinks in about a minute,
# not the builder's 40.
#
#   scripts/linux/dev-build.sh [--lift] [--no-vk] [--install]
#     --lift     lift the game again first (after nx2/ or hook changes; the chunks that come out the same stay cached)
#     --no-vk    keep the Vulkan back end as it is (hookshot_vk.so is not compiled)
#     --install  copy hookshot, hookshot_vk.so and image.bin into the game folder ($HOOKSHOT_GAME)
#
# Environment: HOOKSHOT_APPDIR (the extracted AppImage, ~/.cache/hookshot-appimage/squashfs-root), HOOKSHOT_WORK
# (~/.cache/hookshot-builder), HOOKSHOT_GAME (~/Games/Hookshot), RX_CPM (Vulkan-Headers, SPIRV-Headers, VMA in CPM's
# layout: scripts/linux/deps.sh makes one), HOOKSHOT_JOBS (all threads).
set -euo pipefail
cd "$(dirname "$0")/../.."
APPDIR=${HOOKSHOT_APPDIR:-$HOME/.cache/hookshot-appimage/squashfs-root}
WORK=${HOOKSHOT_WORK:-$HOME/.cache/hookshot-builder}
GAME=${HOOKSHOT_GAME:-$HOME/Games/Hookshot}
export RX_CPM=${RX_CPM:-$HOME/.cache/hookshot-deps/cpm}
LIB=$APPDIR/usr/lib/hookshot
PY=$APPDIR/usr/python/bin/python3
[ -x "$PY" ] || { echo "no extracted AppImage at $APPDIR (Hookshot-*.AppImage --appimage-extract)"; exit 1; }

lift=0 vk=1 install=0
for a in "$@"; do
    case $a in
        --lift) lift=1 ;;
        --no-vk) vk=0 ;;
        --install) install=1 ;;
        *) echo "unknown option $a"; exit 2 ;;
    esac
done

export HOOKSHOT_VK_SYSTEM=${HOOKSHOT_VK_SYSTEM:-1}
export EMSDK=$LIB/emsdk HOOKSHOT_SYSROOT=$LIB/sysroot HOOKSHOT_FFMPEG=$LIB/ffmpeg HOOKSHOT_SDL2=$LIB/libSDL2-2.0.so.0
export OOT_WORK=$WORK OOT_EXEFS=$WORK/exefs OOT_ROMFS=$GAME/romfs OOT_DUMP=$GAME RX_RELEASE=1 A64_HOT_CHUNK=1
[ -f "$WORK/hot_funcs.txt" ] && export A64_HOT_FUNCS=$WORK/hot_funcs.txt
[ -f "$WORK/hookshot_pieces.prof" ] && export RX_PGO=$WORK/hookshot_pieces.prof
if [ $vk = 0 ]; then export HOOKSHOT_VK_PREBUILT=$GAME/hookshot_vk.so; else unset HOOKSHOT_VK_PREBUILT; fi
JOBS=${HOOKSHOT_JOBS:-$(nproc)}

t0=$(date +%s)
if [ $lift = 1 ]; then
    "$PY" -I -u nx2/lift.py --standalone --write --exefs "$OOT_EXEFS" --work "$WORK"
    [ -f "$WORK/sa/gen/code_hot.c" ] && "$PY" -I -u nx2/split_hot.py "$WORK/sa/gen"
fi
"$PY" -I -u nx2/build.py --standalone --jobs "$JOBS"
echo "built in $(( $(date +%s) - t0 )) s"
# (a declaration that landed in an anonymous namespace leaves the back end with a symbol nothing defines: it then fails to load and the
# game runs with nothing drawn, at a perfect 60 fps. Caught here instead)
if [ -f "$WORK/sa/build/hookshot_vk.so" ] && nm -D --undefined-only "$WORK/sa/build/hookshot_vk.so" | grep -q '_GLOBAL__N_'; then
    echo "hookshot_vk.so has undefined anonymous-namespace symbols (it would not load):"
    nm -D --undefined-only "$WORK/sa/build/hookshot_vk.so" | grep '_GLOBAL__N_' | c++filt
    exit 1
fi

if [ $install = 1 ]; then
    for f in hookshot hookshot_vk.so libSDL2-2.0.so.0 libSDL3.so.0; do
        [ -f "$WORK/sa/build/$f" ] || continue
        rm -f "$GAME/$f"   # (not over a running copy's file)
        cp -p "$WORK/sa/build/$f" "$GAME/$f"
    done
    cp -p "$WORK/sa/image/image.bin" "$GAME/image.bin"
    echo "installed into $GAME"
fi
