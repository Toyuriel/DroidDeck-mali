#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else "symbiosis").resolve()

mali = root / "patch/symbiosis/mali_tuning.cpp"
text = mali.read_text(encoding="utf-8")

old = '''    } else if (model == 615 || model == 715 || model == 720) {
        traits.generation = MaliGeneration::Valhall5;
    } else if (model >= 300) {'''
new = '''    } else if (model == 615 || model == 715 || model == 720) {
        traits.generation = MaliGeneration::Valhall5;

        // CloversNX POCO X8 Pro profile.
        // The ARM r49 Mali-G720 MC8 driver is kept to one pipeline worker for
        // the first stability build. We can relax this after device testing.
        if (model == 720) {
            traits.fragile_parallel_compile = true;
        }
    } else if (model >= 300) {'''
if old not in text:
    raise SystemExit("Symbiosis Mali generation table changed; refusing unsafe patch")
text = text.replace(old, new, 1)

marker = '''    // A part with very few cores cannot sustain native resolution regardless of
    // its generation. Core count is a better signal here than model number.
'''
insert = '''    // CloversNX v0.4: conservative Mali-G720 MC8 baseline for POCO X8 Pro.
    // ACNH exposed a long-standing unmapped-buffer failure in Skyline/Strato;
    // on Eden we start by lowering queue/texture pressure rather than carrying
    // that old renderer workaround across architectures.
    {
        std::string name = Lower(traits.device_name);
        if (name.find("mali-g720") != std::string::npos) {
            advice.resolution_index = 2;          // 0.75x for first device test
            advice.allow_async_shaders = false;  // deterministic pipeline order
            advice.gpu_astc = true;               // G720 supports ASTC natively
            advice.texture_budget_fraction = 0.45f;
            advice.rationale =
                "CloversNX G720 safe profile: 0.75x, single-threaded pipeline builds, "
                "native ASTC and a 45% texture-cache share for ARM r49 stability.";
        }
    }

'''
if marker not in text:
    raise SystemExit("Symbiosis advice marker changed; refusing unsafe patch")
text = text.replace(marker, insert + marker, 1)
mali.write_text(text, encoding="utf-8")
print("patched Symbiosis Mali-G720 profile")

# Extend the host test so the G720 classification is pinned by CI.
test = root / "tests/t_mali.cpp"
t = test.read_text(encoding="utf-8")
needle = '''        {"Mali-G710",     true, 16, v13, MaliGeneration::ValhallGen3},
'''
if needle not in t:
    raise SystemExit("Mali test table changed")
t = t.replace(
    needle,
    needle + '        {"Mali-G720 MC8", true, 16, v13, MaliGeneration::Valhall5},\n',
    1,
)
test.write_text(t, encoding="utf-8")
print("extended G720 host test")


# CloversNX v0.4 is a stability diagnostic build. Make Stability genuinely
# deterministic on startup, rather than relying on settings left by a prior run.
auto = root / "patch/symbiosis/auto_modes.cpp"
a = auto.read_text(encoding="utf-8")

old = '''    d.tweaks = {
        {"resolution_setup", "3", "Native resolution (Res1X): no scaling maths to get wrong."},
        {"scaling_filter", "1", "Bilinear."},
        {"anti_aliasing", "0", "Extra passes are extra chances to hit a driver bug."},
        {"gpu_accuracy", "1", "High accuracy: fewer glitches, at some cost."},
        {"use_asynchronous_shaders", "false",
         "Synchronous compilation stutters, but avoids async shader bugs on weak drivers."},
        {"use_asynchronous_gpu_emulation", "true", "Still worth keeping."},
        {"use_disk_shader_cache", "true", "Reduces recompilation."},
        {"astc_recompression", "1", "Lower memory pressure means fewer OOM kills."},
        {"use_speed_limit", "true", "Steady pacing."},
        {"speed_limit", "100", "100%."},
        {"use_reactive_flushing", "false", "A frequent source of hangs on mobile drivers."},
        {"max_anisotropy", "1", "Default (1x)."},
    };'''
new = '''    d.tweaks = {
        {"resolution_setup", "2", "CloversNX Mali safe baseline: 0.75x."},
        {"scaling_filter", "1", "Bilinear."},
        {"anti_aliasing", "0", "Extra passes are extra chances to hit a driver bug."},
        {"gpu_accuracy", "1", "High accuracy: fewer glitches, at some cost."},
        {"use_asynchronous_shaders", "false",
         "Synchronous compilation gives deterministic pipeline order on ARM r49."},
        {"use_asynchronous_gpu_emulation", "true", "Keep CPU/GPU threads decoupled."},
        {"use_disk_shader_cache", "true", "Reduces recompilation."},
        {"astc_recompression", "0", "Do not recompress to BC formats unavailable on Mali-G720."},
        {"accelerate_astc", "1", "Use G720 native ASTC support."},
        {"use_extended_memory_layout", "false", "Preserve Android memory headroom."},
        {"use_speed_limit", "true", "Steady pacing."},
        {"speed_limit", "100", "100%."},
        {"use_vsync", "2", "FIFO avoids building a long presentation queue."},
        {"use_reactive_flushing", "false", "Avoid tiler-hostile mid-frame readback."},
        {"max_anisotropy", "1", "Default (1x)."},
    };'''
if old not in a:
    raise SystemExit("Stability mode changed upstream; refusing unsafe patch")
a = a.replace(old, new, 1)

old = '''    // Do NOT re-apply the mode here.
    //
    // Re-applying on every launch was a mistake: a mode owns resolution,
    // accuracy, filtering and more, so any value the user changed by hand was
    // silently overwritten the next time a game started. The visible symptom is
    // exactly "changing the quality setting does nothing to the frame rate" -
    // the setting really did change, and then got reset before the renderer
    // ever read it.
    //
    // A mode is now applied only when the user picks it. That is the moment
    // they asked for a coherent set of values; every moment after that, their
    // own edits win.
    LogInfo(LogArea::Profile,
            std::string{"startup: mode is "} + ToString(mode) +
                "; leaving settings untouched so manual changes survive");'''
new = '''    // CloversNX v0.4 is a reproducible stability build: the selected mode is
    // applied before the renderer reads graphics settings. Custom remains the
    // escape hatch and is handled above.
    const auto applied = Apply(mode, family, origin);
    LogInfo(LogArea::Profile,
            std::string{"CloversNX startup mode "} + ToString(mode) +
                "; applied " + std::to_string(applied) + " setting(s)");'''
if old not in a:
    raise SystemExit("ApplyCurrentOnStartup implementation changed")
a = a.replace(old, new, 1)
auto.write_text(a, encoding="utf-8")
print("patched Stability startup mode")

# Default a fresh install to Stability and fix the range to include the already
# implemented AaaMin enum value.
up = root / "patch/upstream_changes.patch"
u = up.read_text(encoding="utf-8")
old = '        linkage, 1, 0, 6, "symbiosis_auto_mode", Category::RendererAdvanced};'
new = '        linkage, 3, 0, 7, "symbiosis_auto_mode", Category::RendererAdvanced};'
if old not in u:
    raise SystemExit("Symbiosis auto-mode setting patch changed")
u = u.replace(old, new, 1)
up.write_text(u, encoding="utf-8")
print("defaulted fresh installs to Stability")
