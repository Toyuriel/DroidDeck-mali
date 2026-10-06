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
