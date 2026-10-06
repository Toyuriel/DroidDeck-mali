#!/usr/bin/env bash
set -euo pipefail

PANVK_REPO="https://github.com/wonderkast02/panvk-g720-kbase-csf.git"
PANVK_SHA="980ac91de74df5e5807e6269fd2531fa3ee6b4e5"
ROOT="${1:-$PWD/.panvk-linux}"
DEST="${2:-$PWD/app/src/main/assets/linuxfs/usr/local/lib/droiddeck-mali/panvk}"
SRC="$ROOT/src"
HOST="$ROOT/build-host"
BUILD="$ROOT/build-aarch64"

sudo dpkg --add-architecture arm64
# Ubuntu publishes arm64 Noble packages on ports.ubuntu.com. Restrict the
# runner's normal archive/security stanzas to amd64, then add a native arm64
# ports stanza for the target development libraries.
if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then
  sudo sed -i '/^Architectures:/d; /^Components:/a Architectures: amd64' /etc/apt/sources.list.d/ubuntu.sources
fi
sudo tee /etc/apt/sources.list.d/droiddeck-arm64.sources >/dev/null <<'EOF'
Types: deb
URIs: http://ports.ubuntu.com/ubuntu-ports
Suites: noble noble-updates noble-backports noble-security
Components: main universe restricted multiverse
Architectures: arm64
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
sudo apt-get update -qq
sudo apt-get install -y -qq \
  git build-essential gcc-aarch64-linux-gnu g++-aarch64-linux-gnu \
  pkg-config bison flex libdrm-dev libelf-dev libwayland-dev wayland-protocols \
  llvm-20-dev libclang-20-dev libclc-20-dev libllvmspirvlib-20-dev spirv-tools \
  libdrm-dev:arm64 libelf-dev:arm64 libwayland-dev:arm64 \
  libx11-dev:arm64 libx11-xcb-dev:arm64 libxext-dev:arm64 libxfixes-dev:arm64 \
  libxrandr-dev:arm64 libxshmfence-dev:arm64 \
  libxcb1-dev:arm64 libxcb-dri3-dev:arm64 libxcb-present-dev:arm64 \
  libxcb-randr0-dev:arm64 libxcb-sync-dev:arm64 libxcb-xfixes0-dev:arm64 \
  libxcb-shm0-dev:arm64 libxcb-keysyms1-dev:arm64 \
  libexpat1-dev:arm64 zlib1g-dev:arm64 >/dev/null
python3 -m pip install --user -q --upgrade meson ninja mako PyYAML packaging

rm -rf "$ROOT"
mkdir -p "$ROOT"
git clone -q --filter=blob:none "$PANVK_REPO" "$SRC"
git -C "$SRC" checkout -q "$PANVK_SHA"

# DroidDeck-specific Kbase FD broker. Android can open /dev/mali0 on the target
# phone, while PRoot cannot safely bind that character device into the guest.
# PanVK asks an abstract AF_UNIX socket for a fresh fd for each Kbase context.
cat > "$SRC/src/panfrost/vulkan/panvk_kbase_broker.h" <<'EOF'
#ifndef PANVK_KBASE_BROKER_H
#define PANVK_KBASE_BROKER_H
int panvk_kbase_broker_get_fd(void);
#endif
EOF

cat > "$SRC/src/panfrost/vulkan/panvk_kbase_broker.c" <<'EOF'
#include "panvk_kbase_broker.h"

#include <errno.h>
#include <fcntl.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

int
panvk_kbase_broker_get_fd(void)
{
   const char *name = getenv("PANVK_KBASE_FD_SOCKET");
   if (!name || !name[0])
      return -1;

   size_t name_len = strlen(name);
   if (name_len + 1 >= sizeof(((struct sockaddr_un *)0)->sun_path)) {
      errno = ENAMETOOLONG;
      return -1;
   }

   int sock = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
   if (sock < 0)
      return -1;

   struct sockaddr_un addr = {0};
   addr.sun_family = AF_UNIX;
   addr.sun_path[0] = '\0';
   memcpy(addr.sun_path + 1, name, name_len);
   socklen_t addr_len =
      (socklen_t)(offsetof(struct sockaddr_un, sun_path) + 1 + name_len);

   if (connect(sock, (struct sockaddr *)&addr, addr_len) < 0) {
      int saved = errno;
      close(sock);
      errno = saved;
      return -1;
   }

   char byte = 0;
   struct iovec iov = { .iov_base = &byte, .iov_len = sizeof(byte) };
   char control[CMSG_SPACE(sizeof(int))] = {0};
   struct msghdr msg = {
      .msg_iov = &iov,
      .msg_iovlen = 1,
      .msg_control = control,
      .msg_controllen = sizeof(control),
   };

   if (recvmsg(sock, &msg, 0) <= 0) {
      int saved = errno ? errno : EIO;
      close(sock);
      errno = saved;
      return -1;
   }

   int fd = -1;
   for (struct cmsghdr *cmsg = CMSG_FIRSTHDR(&msg);
        cmsg != NULL;
        cmsg = CMSG_NXTHDR(&msg, cmsg)) {
      if (cmsg->cmsg_level == SOL_SOCKET &&
          cmsg->cmsg_type == SCM_RIGHTS &&
          cmsg->cmsg_len >= CMSG_LEN(sizeof(int))) {
         memcpy(&fd, CMSG_DATA(cmsg), sizeof(fd));
         break;
      }
   }

   close(sock);
   if (fd < 0) {
      errno = ENOMSG;
      return -1;
   }

   fcntl(fd, F_SETFD, fcntl(fd, F_GETFD) | FD_CLOEXEC);
   return fd;
}
EOF

python3 - "$SRC" <<'PY'
from pathlib import Path
import sys

src = Path(sys.argv[1])

# Compile the broker into libvulkan_panfrost.
p = src / "src/panfrost/vulkan/meson.build"
s = p.read_text()
needle = "  'panvk_instance.c',\n"
if needle not in s:
    # Current source lists instance elsewhere; insert after the opening file list.
    needle = "libpanvk_files = files(\n"
    if needle not in s:
        raise SystemExit("panvk meson file list anchor not found")
    s = s.replace(needle, needle + "  'panvk_kbase_broker.c',\n", 1)
else:
    s = s.replace(needle, needle + "  'panvk_kbase_broker.c',\n", 1)
p.write_text(s)

# If a broker is configured, enumerate one virtual Kbase path without requiring
# /dev/mali0 to exist in the PRoot namespace.
p = src / "src/panfrost/vulkan/panvk_instance.c"
s = p.read_text()
if '#include "panvk_kbase_broker.h"' not in s:
    s = s.replace('#include "panvk_physical_device.h"\n',
                  '#include "panvk_physical_device.h"\n#include "panvk_kbase_broker.h"\n', 1)
old = '''#if defined(HAVE_PAN_KMOD_KBASE)
   /* Enumerate kbase (Mali) non-DRM nodes. */
   for (int i = 0; i < PAN_KBASE_MAX_NODES; i++) {
      char path[PATH_MAX];
      snprintf(path, sizeof(path), "/dev/mali%d", i);

      /* Missing optional nodes are normal and should not emit loader
       * warnings.  Existing nodes still go through full initialization so
       * permission and uAPI failures remain visible. */
      if (access(path, F_OK) != 0)
         continue;
'''
new = '''#if defined(HAVE_PAN_KMOD_KBASE)
   /* Enumerate kbase (Mali) non-DRM nodes. DroidDeck can pass the kernel fd
    * over an abstract AF_UNIX broker when /dev/mali0 is not visible in PRoot. */
   const char *droiddeck_broker = os_get_option("PANVK_KBASE_FD_SOCKET");
   int kbase_nodes = (droiddeck_broker && droiddeck_broker[0]) ? 1 : PAN_KBASE_MAX_NODES;
   for (int i = 0; i < kbase_nodes; i++) {
      char path[PATH_MAX];
      snprintf(path, sizeof(path), "/dev/mali%d", i);

      if ((!droiddeck_broker || !droiddeck_broker[0]) && access(path, F_OK) != 0)
         continue;
'''
if old not in s:
    raise SystemExit("PanVK Kbase enumeration anchor not found")
s = s.replace(old, new, 1)
p.write_text(s)

# Physical-device Kbase context: receive a fresh fd from the Android broker.
p = src / "src/panfrost/vulkan/panvk_physical_device.c"
s = p.read_text()
if '#include "panvk_kbase_broker.h"' not in s:
    # Place beside local panvk headers.
    anchor = '#include "panvk_physical_device.h"\n'
    if anchor not in s:
        raise SystemExit("physical device include anchor not found")
    s = s.replace(anchor, anchor + '#include "panvk_kbase_broker.h"\n', 1)
old = '''   fd = open(path, O_RDWR | O_CLOEXEC);
   if (fd < 0) {
      return panvk_errorf(instance, VK_ERROR_INCOMPATIBLE_DRIVER,
                          "failed to open kbase device %s", path);
   }
'''
new = '''   const char *broker = os_get_option("PANVK_KBASE_FD_SOCKET");
   fd = (broker && broker[0]) ? panvk_kbase_broker_get_fd()
                              : open(path, O_RDWR | O_CLOEXEC);
   if (fd < 0) {
      return panvk_errorf(instance, VK_ERROR_INCOMPATIBLE_DRIVER,
                          "failed to acquire kbase device %s: %s",
                          path, strerror(errno));
   }
'''
if old not in s:
    raise SystemExit("physical Kbase open anchor not found")
s = s.replace(old, new, 1)
p.write_text(s)

# Logical VkDevice needs its own Kbase context/handshake, so ask the broker again.
p = src / "src/panfrost/vulkan/panvk_vX_device.c"
s = p.read_text()
if '#include "panvk_kbase_broker.h"' not in s:
    anchor = '#include "panvk_physical_device.h"\n'
    if anchor not in s:
        raise SystemExit("logical device include anchor not found")
    s = s.replace(anchor, anchor + '#include "panvk_kbase_broker.h"\n', 1)
old = '''      int kbase_fd =
         open(physical_device->kbase_node_path, O_RDWR | O_CLOEXEC);
'''
new = '''      const char *broker = os_get_option("PANVK_KBASE_FD_SOCKET");
      int kbase_fd = (broker && broker[0]) ? panvk_kbase_broker_get_fd()
                                           : open(physical_device->kbase_node_path,
                                                  O_RDWR | O_CLOEXEC);
'''
if old not in s:
    raise SystemExit("logical Kbase open anchor not found")
s = s.replace(old, new, 1)
p.write_text(s)
PY

rm -rf "$HOST" "$BUILD"
export PATH="$HOME/.local/bin:$PATH"

# Mesa's precompiled Panfrost shaders are generated by host tools.
meson setup "$HOST" "$SRC" \
  -Dplatforms=[] -Dgallium-drivers=[] -Dvulkan-drivers=[] \
  -Dtools=panfrost -Dprecomp-compiler=enabled -Dinstall-precomp-compiler=true \
  -Dllvm=enabled -Dmesa-clc=enabled -Dinstall-mesa-clc=true \
  -Dbuild-tests=false
ninja -C "$HOST" \
  src/compiler/clc/mesa_clc \
  src/compiler/spirv/vtn_bindgen2 \
  src/panfrost/clc/panfrost_compile
ln -sf mesa_clc "$HOST/src/compiler/clc/mesa-clc"
ln -sf vtn_bindgen2 "$HOST/src/compiler/spirv/vtn-bindgen2"
export PATH="$HOST/src/compiler/clc:$HOST/src/compiler/spirv:$HOST/src/panfrost/clc:$PATH"

cat > "$ROOT/aarch64-pkg-config" <<'EOF'
#!/usr/bin/env bash
export PKG_CONFIG_LIBDIR=/usr/lib/aarch64-linux-gnu/pkgconfig:/usr/share/pkgconfig
exec pkg-config "$@"
EOF
chmod +x "$ROOT/aarch64-pkg-config"

cat > "$ROOT/aarch64-linux.txt" <<EOF
[binaries]
c = 'aarch64-linux-gnu-gcc'
cpp = 'aarch64-linux-gnu-g++'
ar = 'aarch64-linux-gnu-ar'
strip = 'aarch64-linux-gnu-strip'
pkg-config = '$ROOT/aarch64-pkg-config'

[host_machine]
system = 'linux'
cpu_family = 'aarch64'
cpu = 'aarch64'
endian = 'little'

[properties]
needs_exe_wrapper = true
EOF

meson setup "$BUILD" "$SRC" --cross-file "$ROOT/aarch64-linux.txt" \
  -Dbuildtype=release \
  -Dplatforms=x11,wayland \
  -Dgallium-drivers=[] \
  -Dvulkan-drivers=panfrost \
  -Dpanfrost-kmds=kbase \
  -Dglx=disabled -Dgbm=disabled -Degl=disabled \
  -Dopengl=false -Dgles1=disabled -Dgles2=disabled -Dglvnd=disabled \
  -Dllvm=disabled -Dvalgrind=disabled -Dlibunwind=disabled -Dlmsensors=disabled \
  -Dzstd=disabled -Dzlib=disabled -Dxmlconfig=disabled -Dshader-cache=disabled \
  -Dmesa-clc=system -Dprecomp-compiler=system \
  -Dbuild-tests=false -Dtools=[] -Dvideo-codecs=[] -Dperfetto=false

ninja -C "$BUILD" src/panfrost/vulkan/libvulkan_panfrost.so

rm -rf "$DEST"
mkdir -p "$DEST"
install -m755 "$BUILD/src/panfrost/vulkan/libvulkan_panfrost.so" "$DEST/libvulkan_panfrost.so"
aarch64-linux-gnu-strip --strip-unneeded "$DEST/libvulkan_panfrost.so"

cat > "$DEST/panfrost_icd.json" <<EOF
{
  "file_format_version": "1.0.0",
  "ICD": {
    "library_path": "/usr/local/lib/droiddeck-mali/panvk/libvulkan_panfrost.so",
    "api_version": "1.3.0"
  }
}
EOF

cat > "$DEST/SOURCE.txt" <<EOF
PanVK G720 source $PANVK_REPO
technical source authority $PANVK_SHA
target glibc aarch64
platforms x11,wayland
panfrost-kmds kbase
DroidDeck patch kbase-fd-broker-v1
EOF

file "$DEST/libvulkan_panfrost.so"
aarch64-linux-gnu-readelf -d "$DEST/libvulkan_panfrost.so" | grep NEEDED || true
strings "$DEST/libvulkan_panfrost.so" | grep -q 'VK_KHR_wayland_surface'
strings "$DEST/libvulkan_panfrost.so" | grep -q 'VK_KHR_xlib_surface'
strings "$DEST/libvulkan_panfrost.so" | grep -q 'VK_KHR_xcb_surface'
echo "PanVK WSI check: Wayland + Xlib + XCB present"
sha256sum "$DEST/libvulkan_panfrost.so"
