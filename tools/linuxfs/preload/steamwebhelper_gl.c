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

  /*
   * Nested gamescope exports ENABLE_GAMESCOPE_WSI=1 to every child. Chromium should not
   * use the gamescope implicit bypass layer: its own Wayland surface belongs to the nested
   * compositor and must follow ordinary damage/visibility semantics.
   */
  unsetenv("ENABLE_GAMESCOPE_WSI");
  setenv("DISABLE_GAMESCOPE_WSI", "1", 1);

  /*
   * Preferred Mali path: CEF talks Wayland directly and ANGLE uses PanVK.  Do not inherit
   * the old X11/GLX llvmpipe isolation in this mode. The session script sets this only for
   * the Steam client; games continue to use the same PanVK ICD either way.
   */
  const char *wayland = getenv("BL_STEAM_CEF_WAYLAND");
  if (wayland != NULL && strcmp(wayland, "1") == 0) {
    unsetenv("LIBGL_ALWAYS_SOFTWARE");
    unsetenv("GALLIUM_DRIVER");
    unsetenv("LIBGL_KOPPER_DISABLE");
    static const char msg[] =
        "DroidDeck: steamwebhelper uses native Wayland + PanVK; Gamescope WSI bypass disabled\n";
    (void) write(STDERR_FILENO, msg, sizeof(msg) - 1);
    return;
  }

  /* Recovery path for devices/builds where native CEF Wayland is unavailable. */
  setenv("LIBGL_ALWAYS_SOFTWARE", "1", 1);
  unsetenv("MESA_LOADER_DRIVER_OVERRIDE");
  setenv("GALLIUM_DRIVER", "llvmpipe", 1);
  setenv("LIBGL_KOPPER_DISABLE", "true", 1);
  setenv("MESA_NO_ERROR", "1", 0);

  static const char msg[] =
      "DroidDeck: steamwebhelper recovery mode uses llvmpipe GL; games remain on PanVK\n";
  (void) write(STDERR_FILENO, msg, sizeof(msg) - 1);
}
