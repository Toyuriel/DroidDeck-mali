#!/usr/bin/env bash
set -euo pipefail

# Build the experimental glibc -> Android vendor Vulkan bridge on a real/emulated
# AArch64 Ubuntu userspace. The output is copied into the APK's linuxfs assets.
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  ca-certificates git build-essential autoconf automake libtool pkg-config \
  cmake ninja-build python3 patch \
  libwayland-dev wayland-protocols libdrm-dev libvulkan-dev \
  libx11-dev libx11-xcb-dev libxcb1-dev libxcb-dri3-dev libxcb-present-dev \
  libxcb-sync-dev libxcb-shm0-dev libxrandr-dev >/dev/null

ANDROID_HEADERS_SHA=a6261c5cce8e945868b68318e867e382dea4bffd
LIBHYBRIS_SHA=7079712a42ea2754adf747e70c6cc75764c8596e
SYSVK_SHA=23ecd775ed6fe06bb5ac0063b5f981f70c543c67
WSI_SHA=40cfec09d0e2d42c5e1f2642cf4cba11e7008112
VULKAN_HEADERS_SHA=c46850864f4661461b0f6cb9922c058ffea4915e

WORK=/tmp/droiddeck-mali-build
SRC="$WORK/src"
STAGE="$WORK/stage"
ANDROID_PREFIX="$WORK/android-headers"
PREFIX=/usr/local/lib/droiddeck-mali
OUT=/src/app/src/main/assets/linuxfs

rm -rf "$WORK"
mkdir -p "$SRC" "$STAGE" "$ANDROID_PREFIX"

fetch_at() {
  local url=$1 sha=$2 dir=$3
  git init -q "$dir"
  git -C "$dir" remote add origin "$url"
  git -C "$dir" fetch -q --depth 1 origin "$sha"
  git -C "$dir" checkout -q --detach FETCH_HEAD
}

echo "== Mali bridge: fetching pinned sources"
fetch_at https://github.com/Linux-on-droid/android-headers-30.git "$ANDROID_HEADERS_SHA" "$SRC/android-headers"
fetch_at https://github.com/libhybris/libhybris.git "$LIBHYBRIS_SHA" "$SRC/libhybris"
fetch_at https://github.com/xMeM/sysvk.git "$SYSVK_SHA" "$SRC/sysvk"
fetch_at https://github.com/ginkage/vulkan-wsi-layer.git "$WSI_SHA" "$SRC/wsi"
fetch_at https://github.com/KhronosGroup/Vulkan-Headers.git "$VULKAN_HEADERS_SHA" "$SRC/vulkan-headers"

echo "== Mali bridge: Android headers"
make -C "$SRC/android-headers" DESTDIR="$ANDROID_PREFIX" PREFIX=/usr install >/dev/null
ANDROID_INCLUDE="$ANDROID_PREFIX/usr/include/android"
test -f "$ANDROID_INCLUDE/hardware/hardware.h"

echo "== Mali bridge: patched libhybris"
git -C "$SRC/libhybris" apply /src/tools/mali-bridge/patches/libhybris-0001-optional-raw-pthread-exit.patch
# Mali vendor blobs can resolve Android static TLS into glibc's TCB and crash the host
# process (typically rc=139). Isolate Android static TLS in a per-host-thread sidecar.
# GNU patch is intentionally used here because this proof patch was generated from the
# same pinned linker snapshot but carries slightly different surrounding context.
(
  cd "$SRC/libhybris"
  patch -p1 --fuzz=3 --forward < /src/tools/mali-bridge/patches/libhybris-0002-isolate-android-static-tls.patch
)
(
  cd "$SRC/libhybris/hybris"
  NOCONFIGURE=1 ./autogen.sh >/dev/null
  PKG_CONFIG_PATH="$ANDROID_PREFIX/usr/lib/pkgconfig" \
  ./configure \
    --prefix="$PREFIX" \
    --libdir="$PREFIX/lib" \
    --with-android-headers="$ANDROID_INCLUDE" \
    --with-default-hybris-ld-library-path=/system/lib64:/system_ext/lib64:/product/lib64:/vendor/lib64:/vendor/lib64/egl:/vendor/lib64/hw:/odm/lib64:/apex/com.android.runtime/lib64/bionic \
    --enable-arch=arm64 \
    --enable-mali-quirks \
    --enable-property-cache \
    --enable-experimental \
    CFLAGS='-O2 -fPIC -Wa,--noexecstack' \
    CXXFLAGS='-O2 -fPIC -Wa,--noexecstack' \
    LDFLAGS='-Wl,-z,noexecstack' >/dev/null
  make -j2 >/dev/null
  make DESTDIR="$STAGE" install >/dev/null
)
test -f "$STAGE$PREFIX/lib/libhardware.so" || {
  echo "libhybris did not install libhardware.so" >&2
  find "$STAGE$PREFIX" -maxdepth 4 -type f -o -type l
  exit 1
}
test -d "$STAGE$PREFIX/lib/libhybris/linker"

echo "== Mali bridge: sysvk ICD"
mkdir -p "$STAGE$PREFIX/lib" "$STAGE$PREFIX/share/vulkan/icd.d"
gcc -shared -fPIC -O2 "$SRC/sysvk/sysvk.c" \
  -o "$STAGE$PREFIX/lib/libsysvk.so" \
  -I"$SRC/sysvk/include" \
  -L"$STAGE$PREFIX/lib" \
  -Wl,-rpath,"$PREFIX/lib" \
  -Wl,-z,nodelete \
  -lhardware
cat >"$STAGE$PREFIX/share/vulkan/icd.d/sysvk.json" <<EOF
{
  "file_format_version": "1.0.0",
  "ICD": {
    "library_path": "$PREFIX/lib/libsysvk.so",
    "api_version": "1.3.128"
  }
}
EOF

echo "== Mali bridge: Wayland WSI layer"
# Android exposes the public dma_heap character device read-only to regular apps,
# while DMA_HEAP_IOCTL_ALLOC is still permitted. Upstream opens it O_RDWR.
python3 - "$SRC/wsi/util/wsialloc/wsialloc_dma_buf_heaps.c" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
s = p.read_text()
old = 'open("/dev/dma_heap/" STR(WSIALLOC_MEMORY_HEAP_NAME), O_RDWR)'
new = 'open("/dev/dma_heap/" STR(WSIALLOC_MEMORY_HEAP_NAME), O_RDONLY | O_CLOEXEC)'
if old not in s:
    raise SystemExit("WSI dma_heap open pattern changed; refusing an unreviewed build")
p.write_text(s.replace(old, new))
PY

cmake -S "$SRC/wsi" -B "$WORK/wsi-build" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$PREFIX" \
  -DVULKAN_CXX_INCLUDE="$SRC/vulkan-headers/include" \
  -DBUILD_WSI_HEADLESS=OFF \
  -DBUILD_WSI_WAYLAND=ON \
  -DBUILD_WSI_DISPLAY=OFF \
  -DBUILD_WSI_X11=OFF \
  -DSELECT_EXTERNAL_ALLOCATOR=dma_buf_heaps \
  -DWSIALLOC_MEMORY_HEAP_NAME=system \
  -DENABLE_WAYLAND_FIFO_PRESENTATION_THREAD=ON >/dev/null
cmake --build "$WORK/wsi-build" -j2 >/dev/null
DESTDIR="$STAGE" cmake --install "$WORK/wsi-build" >/dev/null

WSI_INST="$STAGE$PREFIX/share/vulkan/implicit_layer.d"
test -f "$WSI_INST/libVkLayer_window_system_integration.so"
install -Dm755 "$WSI_INST/libVkLayer_window_system_integration.so" \
  "$STAGE$PREFIX/lib/libVkLayer_window_system_integration.so"

mkdir -p "$STAGE/usr/share/vulkan/implicit_layer.d"
python3 - "$WSI_INST/VkLayer_window_system_integration.json" \
  "$STAGE/usr/share/vulkan/implicit_layer.d/droiddeck-mali-wsi.json" "$PREFIX" <<'PY'
import json, pathlib, sys
src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])
prefix = sys.argv[3]
data = json.loads(src.read_text())
layer = data["layer"]
layer["library_path"] = prefix + "/lib/libVkLayer_window_system_integration.so"
# Keep this GLOBAL layer completely inert for Adreno and all non-Mali sessions.
layer["enable_environment"] = {"DROIDDECK_MALI_WSI": "1"}
dst.write_text(json.dumps(data, indent=2) + "\n")
PY
rm -rf "$WSI_INST"

# Keep source provenance next to the bridge. The Android vendor driver itself is
# never copied or redistributed; it is bind-mounted from the user's device.
cat >"$STAGE$PREFIX/SOURCES.txt" <<EOF
android-headers-30 $ANDROID_HEADERS_SHA
libhybris $LIBHYBRIS_SHA
sysvk $SYSVK_SHA
vulkan-wsi-layer $WSI_SHA
Vulkan-Headers $VULKAN_HEADERS_SHA
droiddeck-patches tls-sidecar-v1
EOF

echo "== Mali bridge: dependency audit"
readelf -d "$STAGE$PREFIX/lib/libsysvk.so" | grep -E 'NEEDED|RPATH|RUNPATH|FLAGS_1' || true
readelf -d "$STAGE$PREFIX/lib/libVkLayer_window_system_integration.so" | grep -E 'NEEDED|RPATH|RUNPATH' || true

echo "== Mali bridge: staging into APK assets"
rm -rf "$OUT$PREFIX"
mkdir -p "$OUT/usr/local/lib" "$OUT/usr/share/vulkan/implicit_layer.d"
# Dereference libtool symlinks: Android assets are regular files, not a Unix package tree.
cp -aL "$STAGE$PREFIX" "$OUT/usr/local/lib/droiddeck-mali"
install -Dm644 "$STAGE/usr/share/vulkan/implicit_layer.d/droiddeck-mali-wsi.json" \
  "$OUT/usr/share/vulkan/implicit_layer.d/droiddeck-mali-wsi.json"

test -f "$OUT$PREFIX/lib/libsysvk.so"
test -f "$OUT$PREFIX/lib/libhardware.so"
test -f "$OUT$PREFIX/lib/libVkLayer_window_system_integration.so"
test -f "$OUT/usr/share/vulkan/implicit_layer.d/droiddeck-mali-wsi.json"

echo "== Mali bridge: staged files"
find "$OUT$PREFIX" -maxdepth 4 -type f | sort
