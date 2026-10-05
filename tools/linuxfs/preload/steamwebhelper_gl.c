/*
 * Steam Gamepad UI: software GL only for steamwebhelper on the experimental Mali path.
 *
 * gamescope and games use PanVK/Kbase. Steam's Chromium UI, however, creates a separate
 * GLX browser-compositor context. ANGLE/OpenGL over Zink/PanVK can enumerate the G720 but
 * Steam's CCompositorGLThread fails to acquire its output context and restarts webhelper
 * every ~10 seconds. --disable-gpu is not a usable fallback either: Chromium starts
 * SwiftShader/ANGLE Vulkan and requests VK_KHR_xcb_surface, which the Kbase PanVK build
 * intentionally does not expose.
 *
 * Keep Steam's GLX mode, but make only steamwebhelper use Mesa's software rasterizer.
 * LD_PRELOAD is inherited by the helper and its zygote/renderer children; games are
 * descendants of the Steam client, not of steamwebhelper, so they retain PanVK.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int is_mali_session(void) {
  const char *v = getenv("BL_MALI_ANDROID_VULKAN");
  return v != NULL && strcmp(v, "1") == 0;
}

__attribute__((constructor))
static void droiddeck_steamwebhelper_software_gl(void) {
  const char *name = program_invocation_short_name;
  if (!is_mali_session() || name == NULL || strcmp(name, "steamwebhelper") != 0)
    return;

  setenv("LIBGL_ALWAYS_SOFTWARE", "1", 1);
  unsetenv("MESA_LOADER_DRIVER_OVERRIDE");
  setenv("GALLIUM_DRIVER", "llvmpipe", 1);
  setenv("MESA_NO_ERROR", "1", 0);

  static const char msg[] =
      "DroidDeck: steamwebhelper uses llvmpipe GL; games remain on PanVK\n";
  (void) write(STDERR_FILENO, msg, sizeof(msg) - 1);
}
