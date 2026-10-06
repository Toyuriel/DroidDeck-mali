#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()

def replace(path, old, new, required=True):
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    if old not in text:
        if required:
            raise SystemExit(f"Expected text not found in {path}: {old[:140]!r}")
        return False
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"patched {path}")
    return True

# Install beside upstream Strato while preserving the Java/Kotlin namespace.
replace(
    "app/build.gradle",
    'applicationId "org.stratoemu.strato"',
    'applicationId "com.cloversgamers.cloversnx.mali"'
)
replace(
    "app/build.gradle",
    'versionName getGitVersionName()',
    'versionName "0.2.0-mali-g720-safe"'
)

replace(
    "app/src/main/res/values/strings.xml",
    '<string name="app_name" translatable="false">Skyline</string>',
    '<string name="app_name" translatable="false">CloversNX Mali</string>'
)

# Mali-G720 / Arm r49 profile.
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

                const std::string_view deviceName{deviceProperties.deviceName.data()};
                const bool cloversMaliG720{deviceName.find("Mali-G720") != std::string_view::npos};

                // CloversNX Mali v0.2 safe profile.
                // r49 on the G720 is new enough for VK_EXT_extended_dynamic_state, so do not
                // force the old vertex-binding path as v0.1 did. Pipeline compilation remains
                // serialized to avoid proprietary-driver races.
                if (cloversMaliG720) {
                    brokenMultithreadedPipelineCompilation = true;
                    LOGI("CloversNX Mali-G720 v0.2 safe profile enabled for {}", deviceName);
                }

                brokenSpirvAccessChainOpt = true;

                // Upstream disables mutable-format images on proprietary ARM to preserve AFBC.
                // ACNH on the tested G720 requests UNORM/SRGB views of the same image. Creating
                // those views without VK_IMAGE_CREATE_MUTABLE_FORMAT_BIT is not a safe path on
                // this driver, so prefer correctness over AFBC for G720.
                vkImageMutableFormatCostly = !cloversMaliG720;

                maxGlobalPriority = vk::QueueGlobalPriorityEXT::eHigh;
                break;
            }
'''
if old not in text:
    raise SystemExit("ARM proprietary quirk block changed upstream; refusing unsafe patch")
trait.write_text(text.replace(old, new, 1), encoding="utf-8")
print("patched app/src/main/cpp/skyline/gpu/trait_manager.cpp")

# ACNH produced hundreds of unmapped vertex-buffer events immediately before the
# process disappeared. Use a real page-sized backing allocation instead of a
# zero-length fallback. With extended dynamic state on r49, this also supplies a
# valid bound size and gives robust vertex fetches a safe zero page.
active = ROOT / "app/src/main/cpp/skyline/gpu/interconnect/maxwell_3d/active_state.cpp"
text = active.read_text(encoding="utf-8")
old = '''        megaBufferBinding = {};
        if (ctx.gpu.traits.supportsNullDescriptor)
            builder.SetVertexBuffer(index, BufferBinding{}, ctx.gpu.traits.supportsExtendedDynamicState, engine->vertexStream.format.stride);
        else
            builder.SetVertexBuffer(index, {ctx.gpu.megaBufferAllocator.Allocate(ctx.executor.cycle, 0).buffer}, ctx.gpu.traits.supportsExtendedDynamicState, engine->vertexStream.format.stride);
'''
new = '''        megaBufferBinding = {};
        if (ctx.gpu.traits.supportsNullDescriptor) {
            builder.SetVertexBuffer(index, BufferBinding{}, ctx.gpu.traits.supportsExtendedDynamicState, engine->vertexStream.format.stride);
        } else {
            auto fallback{ctx.gpu.megaBufferAllocator.Allocate(ctx.executor.cycle, PAGE_SIZE)};
            std::fill(fallback.region.begin(), fallback.region.end(), 0);
            builder.SetVertexBuffer(index, BufferBinding{fallback}, ctx.gpu.traits.supportsExtendedDynamicState, engine->vertexStream.format.stride);
        }
'''
if old not in text:
    raise SystemExit("Vertex buffer fallback block changed upstream; refusing unsafe patch")
active.write_text(text.replace(old, new, 1), encoding="utf-8")
print("patched app/src/main/cpp/skyline/gpu/interconnect/maxwell_3d/active_state.cpp")

# Capture aborts from the Vulkan driver in the emulator log when possible.
replace(
    "app/src/main/cpp/emu_jni.cpp",
    'skyline::signal::SetHostSignalHandler({SIGINT, SIGILL, SIGTRAP, SIGBUS, SIGFPE, SIGSEGV}, skyline::signal::ExceptionalSignalHandler);',
    'skyline::signal::SetHostSignalHandler({SIGINT, SIGILL, SIGTRAP, SIGBUS, SIGFPE, SIGSEGV, SIGABRT}, skyline::signal::ExceptionalSignalHandler);'
)

# Use a fresh pipeline cache namespace so v0.1 driver cache data is not reused
# after changing vertex binding and image-create behavior.
replace(
    "app/src/main/cpp/skyline/gpu.cpp",
    'state.os->publicAppFilesPath + "vk_graphics_pipeline_cache/" + titleId',
    'state.os->publicAppFilesPath + "vk_graphics_pipeline_cache_v02/" + titleId'
)

# Conservative defaults for Mali-G720. These reduce queued work and swapchain
# pressure while testing stability. Users can still override them in settings.
replace(
    "app/src/main/java/org/stratoemu/strato/settings/EmulationSettings.kt",
    'var isDocked by sharedPreferences(context, true, prefName = prefName)',
    'var isDocked by sharedPreferences(context, false, prefName = prefName)'
)
replace(
    "app/src/main/java/org/stratoemu/strato/settings/EmulationSettings.kt",
    'var forceTripleBuffering by sharedPreferences(context, true, prefName = prefName)',
    'var forceTripleBuffering by sharedPreferences(context, false, prefName = prefName)'
)
replace(
    "app/src/main/java/org/stratoemu/strato/settings/EmulationSettings.kt",
    'var executorSlotCountScale by sharedPreferences(context, 6, prefName = prefName)',
    'var executorSlotCountScale by sharedPreferences(context, 4, prefName = prefName)'
)
replace(
    "app/src/main/java/org/stratoemu/strato/settings/EmulationSettings.kt",
    'var executorFlushThreshold by sharedPreferences(context, 256, prefName = prefName)',
    'var executorFlushThreshold by sharedPreferences(context, 96, prefName = prefName)'
)

print("CloversNX Mali v0.2 safe profile applied successfully")
