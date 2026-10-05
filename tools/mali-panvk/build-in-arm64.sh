#!/usr/bin/env bash
set -euo pipefail

ROOT=/src
WORK=/tmp/droiddeck-panvk
OUT="$ROOT/app/src/main/assets/linuxfs/usr/local/lib/droiddeck-mali/panvk"
PANVK_REPO=https://github.com/wonderkast02/panvk-g720-kbase-csf.git
PANVK_SHA=980ac91de74df5e5807e6269fd2531fa3ee6b4e5

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  git ca-certificates build-essential python3 python3-pip meson ninja-build pkg-config \
  bison flex libdrm-dev libwayland-dev wayland-protocols \
  libx11-dev libx11-xcb-dev libxext-dev libxfixes-dev libxrandr-dev libxshmfence-dev \
  libxcb1-dev libxcb-dri3-dev libxcb-present-dev libxcb-randr0-dev libxcb-sync-dev \
  libxcb-xfixes0-dev libxcb-shm0-dev libxcb-keysyms1-dev \
  libelf-dev libexpat1-dev zlib1g-dev llvm-dev libclang-dev libclc-dev \
  libllvmspirvlib-dev spirv-tools glslang-tools >/dev/null
python3 -m pip install --break-system-packages -q mako PyYAML packaging

rm -rf "$WORK"
git clone -q "$PANVK_REPO" "$WORK"
git -C "$WORK" checkout -q "$PANVK_SHA"

python3 - "$WORK/src/panfrost/vulkan/panvk_instance.c" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
s=p.read_text()
old='''   /* Enumerate kbase (Mali) non-DRM nodes. */
   for (int i = 0; i < PAN_KBASE_MAX_NODES; i++) {
      char path[PATH_MAX];
      snprintf(path, sizeof(path), "/dev/mali%d", i);
'''
new='''   /* Enumerate kbase (Mali) non-DRM nodes. DroidDeck can keep /dev/mali0
    * open on the Android side and expose that exact file description through
    * procfs, avoiding a PRoot character-device bind that stalls before exec. */
   const char *forced_kbase = os_get_option("DROIDDECK_KBASE_DEVICE");
   const int kbase_node_count =
      forced_kbase && forced_kbase[0] ? 1 : PAN_KBASE_MAX_NODES;
   for (int i = 0; i < kbase_node_count; i++) {
      char path[PATH_MAX];
      if (forced_kbase && forced_kbase[0])
         snprintf(path, sizeof(path), "%s", forced_kbase);
      else
         snprintf(path, sizeof(path), "/dev/mali%d", i);
'''
if old not in s:
    raise SystemExit("PanVK kbase enumeration anchor not found")
p.write_text(s.replace(old,new,1))
PY

cd "$WORK"

meson setup build-host \
  -Dplatforms=[] \
  -Dgallium-drivers=[] \
  -Dvulkan-drivers=[] \
  -Dtools=panfrost \
  -Dprecomp-compiler=enabled \
  -Dinstall-precomp-compiler=true \
  -Dllvm=enabled \
  -Dmesa-clc=enabled \
  -Dinstall-mesa-clc=true \
  -Dbuild-tests=false >/dev/null

ninja -C build-host \
  src/compiler/clc/mesa_clc \
  src/compiler/spirv/vtn_bindgen2 \
  src/panfrost/clc/panfrost_compile >/dev/null

ln -sf "$WORK/build-host/src/compiler/clc/mesa_clc" "$WORK/build-host/src/compiler/clc/mesa-clc"
ln -sf "$WORK/build-host/src/compiler/spirv/vtn_bindgen2" "$WORK/build-host/src/compiler/spirv/vtn-bindgen2"
export PATH="$WORK/build-host/src/compiler/clc:$WORK/build-host/src/compiler/spirv:$WORK/build-host/src/panfrost/clc:$PATH"

meson setup build \
  -Dbuildtype=release \
  -Dplatforms=x11,wayland \
  -Dglx=disabled \
  -Dgbm=disabled \
  -Degl=disabled \
  -Dopengl=false \
  -Dgles1=disabled \
  -Dgles2=disabled \
  -Dglvnd=disabled \
  -Dvalgrind=disabled \
  -Dgallium-drivers=[] \
  -Dshared-glapi=disabled \
  -Dzstd=disabled \
  -Dmesa-clc=system \
  -Dprecomp-compiler=system \
  -Dvulkan-drivers=panfrost \
  -Dllvm=disabled \
  -Dpanfrost-kmds=kbase \
  -Dbuild-tests=false \
  -Dtools=[] >/dev/null

ninja -C build src/panfrost/vulkan/libvulkan_panfrost.so >/dev/null

rm -rf "$OUT"
mkdir -p "$OUT"
install -m755 build/src/panfrost/vulkan/libvulkan_panfrost.so "$OUT/libvulkan_panfrost.so"

cat > "$OUT/panfrost_icd.json" <<'EOF'
{
  "file_format_version": "1.0.0",
  "ICD": {
    "library_path": "/usr/local/lib/droiddeck-mali/panvk/libvulkan_panfrost.so",
    "api_version": "1.4.0"
  }
}
EOF

cat > "$OUT/BUILD.txt" <<EOF
PanVK source $PANVK_REPO
PanVK commit $PANVK_SHA
DroidDeck patch procfd-kbase-v1
Target glibc aarch64
KMD kbase
WSI x11,wayland
EOF

file "$OUT/libvulkan_panfrost.so"
readelf -h "$OUT/libvulkan_panfrost.so" | grep -E 'Class:|Machine:'
readelf -d "$OUT/libvulkan_panfrost.so" | grep -E 'NEEDED|SONAME' || true
sha256sum "$OUT/libvulkan_panfrost.so"
