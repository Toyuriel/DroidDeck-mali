# POCO X8 Pro: minimal active graphics path

Review: 2026-10-05. Fork baseline: `9e54e094fbdd049a9ec5450932f7b416f2ed8e51`.
Reviewed original DroidDeck through `d3c0d25`, Gamescope `3.16.29`, and the pinned
PanVK source `980ac91de74df5e5807e6269fd2531fa3ee6b4e5`.

The goal is to keep DroidDeck's original Linux/Steam/Gamescope architecture and limit
Mali changes to the driver boundary and the demonstrated presentation regressions.
This change does not merge the original project's unrelated frontend changes or rename
its runtime components. It is a correction of the existing fork, not a claim that Mali
can use the original Turnip binaries.

## Architecture retained

| Component | Original Adreno path | X8 Pro path |
| --- | --- | --- |
| Android, PRoot, ARM64 Linux and Steam client | Existing DroidDeck implementation | Same implementation |
| Guest Vulkan | glibc Turnip | Native glibc PanVK/Kbase; Android passes fresh kernel FDs through the broker |
| Gamescope | Original nested Wayland backend | Same backend with `--force-composition` |
| Steam web interface | Accelerated CEF path | X11 + ANGLE/OpenGL + llvmpipe, isolated to SteamWebHelper |
| Games and PPSSPP | Turnip | PanVK; PPSSPP uses its native Vulkan backend |
| Android presentation | Bionic Turnip | Android system Vulkan |

The software CEF path remains a compatibility compromise. It consumes CPU and does not
establish performance parity with the original. It does not force games onto software
rendering. PanVK/Kbase is experimental; passing `vulkaninfo` establishes device discovery,
not Steam rendering or game compatibility.

## Findings and changes

1. **A previous frame-retention workaround was invalid.** Gamescope's
   `CWaylandConnector::Present` deliberately uses a 1x1 black buffer, enlarged by
   `wp_viewport`, behind translucent layers. The fork discarded small replacements
   after a full-size frame. That leaves the previous image under the new scene.
   Remove the workaround and restore ordinary buffer replacement, including NULL.

2. **The host does not implement synchronized subsurface commits.** Its `set_sync` and
   `set_desync` handlers are empty. Gamescope's normal Wayland path forwards up to nine
   planes and commits them separately. Use Gamescope's existing composed path on Mali:
   it calls `vulkan_composite`, waits for completion with `vulkan_wait`, then presents
   one combined content plane. This avoids depending on incomplete host atomicity for
   Steam/game layers and costs an additional composition pass. It does not make the
   host a fully compliant subsurface compositor. `BL_MALI_FORCE_COMPOSITION=0` is an
   explicit diagnostic opt-out, not the default.

3. **SteamWebHelper acquired a conflicting CPU-raster experiment.** Compared with
   `7fdedad`, the later change added three switches including a second
   `--disable-features`. That replaced Valve's list, including
   `SpareRendererForSitePerProcess`. The latest supplied log shows repeated renderer
   launches and a shared-JS-context error page, with no GPU frames reaching the Android
   compositor. Restore the earlier X11/ANGLE/llvmpipe profile that had reached Steam's
   interface; preserve Valve's feature list. The log correlation does not prove the
   complete cause of the renderer failures. An on-device launch must confirm recovery.

4. **The Vulkan FOREIGN ownership extension was used without being enabled.** Enable
   `VK_EXT_queue_family_foreign` when creating the Android device, and report a missing
   required extension explicitly. `VK_QUEUE_FAMILY_EXTERNAL` is not an equivalent
   substitute when the producer and consumer use different driver implementations.

5. **Vulkan was probed twice.** The second `vulkaninfo` ran inside Gamescope, creating
   temporary windows through its WSI layer before Steam launched. Probe once outside;
   the child keeps the selected native PanVK driver. A failed probe or missing broker
   now stops with an explicit error instead of silently switching to libhybris and
   then continuing after another failed probe.

6. **The package completeness check did not check PanVK.** Require its library and ICD
   in both installed and staged packages. Legacy bridge files remain in the package
   for compatibility with older APKs but are not selected by the active X8 Pro path.
   Preserve the existing automatic package update mechanism and log PanVK's source
   record. Also restore the original `$$` process ID in the emulator CPU-affinity call.

The earlier per-swapchain-image Vulkan semaphore fix, GENERAL-layout preservation,
session-log rotation and toplevel reconfigure fix are retained. A NULL-attach log named
“Gamescope” alone does not identify a toplevel: the diagnostic name is inherited by
subsurfaces. The latest log therefore does not prove the configure fix explains the
missing first frame.

## Validation and remaining device check

Host regressions execute the production buffer/commit functions across repeated remaps
and full-size-to-1x1 replacements. Vulkan calls and Wayland transport are mocked. The
CEF test compiles and loads the real preload into a fixture executable named
`steamwebhelper`, exercising its actual re-exec, argument preservation and environment;
an emulator and non-Mali process must retain their original driver. Shell tests execute
the production selection/argument blocks with a simulated probe, including failed and
missing-package cases. These tests do not run Steam, PanVK workloads or Android graphics.

On the X8 Pro, the next required observation is Steam reaching Big Picture, followed by
opening/closing its menu and switching to a running PPSSPP game without an old image
remaining underneath. The same-session diagnostic ZIP must show the APK revision,
PanVK package version, the single-composition launch line and actual presented frames.
Successful compilation alone must not be described as a confirmed device fix.

## Primary source references

- [Original DroidDeck](https://github.com/Droid-Deck/DroidDeck)
- [Gamescope Wayland presentation](https://github.com/ValveSoftware/gamescope/blob/3.16.29/src/Backends/WaylandBackend.cpp)
- [Gamescope command-line options](https://github.com/ValveSoftware/gamescope/blob/3.16.29/src/main.cpp)
- [Pinned PanVK WSI](https://github.com/wonderkast02/panvk-g720-kbase-csf/blob/980ac91de74df5e5807e6269fd2531fa3ee6b4e5/src/panfrost/vulkan/panvk_wsi.c)
- [Vulkan FOREIGN ownership extension](https://docs.vulkan.org/refpages/latest/refpages/source/VK_EXT_queue_family_foreign.html)
