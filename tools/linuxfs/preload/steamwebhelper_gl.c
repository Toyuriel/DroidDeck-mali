/*
 * Steam Gamepad UI graphics isolation for the experimental Mali path.
 *
 * Gamescope and games use PanVK/Kbase. Steam's CEF UI has proven less tolerant of this
 * experimental PanVK path: Chromium GPU work can trigger fatal Kbase CSF group errors, while
 * Steam's own -cef-ozone-platform/-cef-use-angle switches are not copied to steamwebhelper's
 * argv. A fully --disable-gpu CEF fallback avoids the reset but is far too slow.
 *
 * Keep Chromium's GPU process/compositor enabled, but re-exec steamwebhelper once with Chromium's
 * real Ozone/ANGLE switches and isolate only that process tree onto llvmpipe. Games and gamescope
 * remain on PanVK.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

extern char **environ;

static int is_mali_session(void) {
  const char *v = getenv("BL_MALI_ANDROID_VULKAN");
  return v != NULL && strcmp(v, "1") == 0;
}

static int is_steamwebhelper(void) {
  const char *name = program_invocation_short_name;
  return name != NULL && strcmp(name, "steamwebhelper") == 0;
}

static void isolate_webhelper_graphics(void) {
  /* Never let CEF enter PanVK/Kbase, directly or through zink. */
  unsetenv("ENABLE_GAMESCOPE_WSI");
  setenv("DISABLE_GAMESCOPE_WSI", "1", 1);
  unsetenv("VK_DRIVER_FILES");
  unsetenv("VK_ICD_FILENAMES");
  unsetenv("MESA_LOADER_DRIVER_OVERRIDE");
  setenv("LIBGL_ALWAYS_SOFTWARE", "1", 1);
  setenv("GALLIUM_DRIVER", "llvmpipe", 1);
  setenv("LIBGL_KOPPER_DISABLE", "true", 1);
  setenv("MESA_NO_ERROR", "1", 0);

  /*
   * The global Steam tuning may enable Mesa's GL command marshalling. llvmpipe is already
   * internally threaded, and Chromium/ANGLE destroys shared-image resources aggressively.
   * Deferred GL commands here make those lifetimes even less deterministic, so keep glthread
   * off only in the webhelper process tree.
   */
  setenv("mesa_glthread", "false", 1);
}

/* Read the argv Linux gave this process. Constructors do not receive argc/argv. */
static char *read_cmdline(size_t *size_out) {
  int fd = open("/proc/self/cmdline", O_RDONLY | O_CLOEXEC);
  if (fd < 0) return NULL;
  size_t cap = 8192, used = 0;
  char *buf = malloc(cap);
  if (!buf) { close(fd); return NULL; }
  for (;;) {
    if (used == cap) {
      if (cap >= 131072) { free(buf); close(fd); return NULL; }
      cap *= 2;
      char *grown = realloc(buf, cap);
      if (!grown) { free(buf); close(fd); return NULL; }
      buf = grown;
    }
    ssize_t n = read(fd, buf + used, cap - used);
    if (n < 0) {
      if (errno == EINTR) continue;
      free(buf); close(fd); return NULL;
    }
    if (n == 0) break;
    used += (size_t)n;
  }
  close(fd);
  if (!used) { free(buf); return NULL; }
  if (buf[used - 1] != '\0') {
    if (used == cap) {
      char *grown = realloc(buf, cap + 1);
      if (!grown) { free(buf); return NULL; }
      buf = grown;
    }
    buf[used++] = '\0';
  }
  *size_out = used;
  return buf;
}

static void reexec_with_x11_llvmpipe(void) {
  if (getenv("BL_STEAMWEBHELPER_GRAPHICS_READY")) return;

  size_t bytes = 0;
  char *cmd = read_cmdline(&bytes);
  if (!cmd) return;

  size_t argc = 0;
  for (size_t off = 0; off < bytes;) {
    size_t n = strnlen(cmd + off, bytes - off);
    if (n == 0) break;
    argc++;
    off += n + 1;
  }

  /* Keep the X11/ANGLE/llvmpipe profile that reached Steam's UI. Do not add another
   * --disable-features: Chromium treats that as a replacement for Valve's list, including
   * SpareRendererForSitePerProcess. The CPU-raster experiment coincided with repeated renderer
   * deaths and the shared JS context error page, before any Steam frame reached the host.
   * llvmpipe already executes the GL work in software without touching PanVK.
   * Eight switches plus NULL. */
  char **argv = calloc(argc + 9, sizeof(*argv));
  if (!argv) { free(cmd); return; }

  size_t ai = 0;
  for (size_t off = 0; off < bytes && ai < argc;) {
    size_t n = strnlen(cmd + off, bytes - off);
    if (n == 0) break;
    argv[ai++] = cmd + off;
    off += n + 1;
  }
  argv[ai++] = "--ozone-platform=x11";
  argv[ai++] = "--use-gl=angle";
  argv[ai++] = "--use-angle=gl";
  argv[ai++] = "--disable-gpu-memory-buffer-compositor-resources";
  argv[ai++] = "--disable-gpu-memory-buffer-video-frames";
  argv[ai++] = "--disable-zero-copy";
  argv[ai++] = "--disable-oop-rasterization";
  argv[ai++] = "--disable-accelerated-video-decode";
  argv[ai] = NULL;

  isolate_webhelper_graphics();
  setenv("BL_STEAMWEBHELPER_GRAPHICS_READY", "1", 1);

  static const char msg[] =
      "DroidDeck: re-exec steamwebhelper on X11 + ANGLE/GL + llvmpipe; GMB/zero-copy/OOP-raster disabled; Valve features preserved\n";
  (void)write(STDERR_FILENO, msg, sizeof(msg) - 1);

  /* /proc/self/exe preserves Steam's exact webhelper binary even after client updates. */
  execve("/proc/self/exe", argv, environ);

  /* If re-exec fails, continue with isolated llvmpipe rather than falling into PanVK. */
  static const char fail[] =
      "DroidDeck: steamwebhelper X11 re-exec failed; continuing with llvmpipe isolation\n";
  (void)write(STDERR_FILENO, fail, sizeof(fail) - 1);
  free(argv);
  free(cmd);
}

__attribute__((constructor))
static void droiddeck_steamwebhelper_graphics(void) {
  if (!is_mali_session() || !is_steamwebhelper()) return;

  isolate_webhelper_graphics();

  const char *enabled = getenv("BL_STEAM_CEF_ISOLATED");
  if (enabled != NULL && strcmp(enabled, "1") == 0) {
    if (!getenv("BL_STEAMWEBHELPER_GRAPHICS_READY")) {
      reexec_with_x11_llvmpipe();
      return;
    }
    static const char msg[] =
        "DroidDeck: steamwebhelper X11 llvmpipe GPU compositor active; games remain on PanVK\n";
    (void)write(STDERR_FILENO, msg, sizeof(msg) - 1);
    return;
  }

  static const char msg[] =
      "DroidDeck: steamwebhelper recovery mode uses llvmpipe GL; games remain on PanVK\n";
  (void)write(STDERR_FILENO, msg, sizeof(msg) - 1);
}
