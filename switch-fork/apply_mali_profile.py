#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()

def replace(path, old, new, required=True):
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    if old not in text:
        if required:
            raise SystemExit(f"Expected text not found in {path}: {old[:120]!r}")
        return False
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"patched {path}")
    return True

# Keep the Java/Kotlin namespace intact, but install beside official Strato.
replace(
    "app/build.gradle",
    'applicationId "org.stratoemu.strato"',
    'applicationId "com.cloversgamers.cloversnx.mali"'
)
replace(
    "app/build.gradle",
    'versionName getGitVersionName()',
    'versionName "0.1.0-mali-g720"'
)

replace(
    "app/src/main/res/values/strings.xml",
    '<string name="app_name" translatable="false">Skyline</string>',
    '<string name="app_name" translatable="false">CloversNX Mali</string>'
)

trait = ROOT / "app/src/main/cpp/skyline/gpu/trait_manager.cpp"
text = trait.read_text(encoding="utf-8")
old = '''            case vk::DriverId::eArmProprietary: {
                if (deviceProperties.driverVersion < VK_MAKE_VERSION(42, 0, 0))
                    brokenDynamicStateVertexBindings = true;

                brokenSpirvAccessChainOpt = true;
                vkImageMutableFormatCostly = true; // Disables AFBC in some cases
                maxGlobalPriority = vk::QueueGlobalPriorityEXT::eHigh;
                break;
            }
'''
new = '''            case vk::DriverId::eArmProprietary: {
                if (deviceProperties.driverVersion < VK_MAKE_VERSION(42, 0, 0))
                    brokenDynamicStateVertexBindings = true;

                // CloversNX Mali v0.1 compatibility profile.
                // Mali-G720 on recent MediaTek devices is kept on conservative Vulkan paths
                // until per-driver testing proves the faster paths reliable.
                const std::string_view deviceName{deviceProperties.deviceName.data()};
                if (deviceName.find("Mali-G720") != std::string_view::npos) {
                    brokenDynamicStateVertexBindings = true;
                    brokenMultithreadedPipelineCompilation = true;
                    LOGI("CloversNX Mali-G720 compatibility profile enabled for {}", deviceName);
                }

                brokenSpirvAccessChainOpt = true;
                vkImageMutableFormatCostly = true; // Disables AFBC in some cases
                maxGlobalPriority = vk::QueueGlobalPriorityEXT::eHigh;
                break;
            }
'''
if old not in text:
    raise SystemExit("ARM proprietary quirk block changed upstream; refusing to apply an unsafe patch")
trait.write_text(text.replace(old, new, 1), encoding="utf-8")
print("patched app/src/main/cpp/skyline/gpu/trait_manager.cpp")

# Conservative defaults for this device-specific build.
# Keep triple buffering and shader cache enabled; reduce queued GPU work modestly
# to lower transient memory/latency without touching emulation semantics.
replace(
    "app/src/main/java/org/stratoemu/strato/settings/EmulationSettings.kt",
    'var executorSlotCountScale by sharedPreferences(context, 6, prefName = prefName)',
    'var executorSlotCountScale by sharedPreferences(context, 5, prefName = prefName)'
)
replace(
    "app/src/main/java/org/stratoemu/strato/settings/EmulationSettings.kt",
    'var executorFlushThreshold by sharedPreferences(context, 256, prefName = prefName)',
    'var executorFlushThreshold by sharedPreferences(context, 192, prefName = prefName)'
)

print("CloversNX Mali v0.1 profile applied successfully")
