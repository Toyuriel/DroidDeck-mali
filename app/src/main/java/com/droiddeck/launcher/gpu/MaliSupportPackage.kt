package com.droiddeck.launcher.gpu

import android.content.Context
import android.util.Log
import com.droiddeck.launcher.core.Downloader
import com.droiddeck.launcher.core.FileUtils
import com.droiddeck.launcher.core.Hashes
import com.droiddeck.launcher.runtime.LinuxRuntime
import com.droiddeck.launcher.runtime.LinuxRuntimeInstaller
import org.json.JSONObject
import java.io.File

/**
 * Downloadable runtime support for ARM Mali/MediaTek.
 *
 * The APK contains the compositor, but native PanVK is versioned separately. The package is a
 * tar.zst rooted at / and contains only DroidDeck-owned files under /usr/local/lib/droiddeck-mali
 * plus its Vulkan implicit-layer manifest.
 */
object MaliSupportPackage {
    private const val TAG = "MaliSupportPackage"
    private const val RELEASE_TAG = "mali-support-latest"
    private const val BASE = "https://github.com/Toyuriel/DroidDeck-mali/releases/download/$RELEASE_TAG/"
    private const val MANIFEST_URL = BASE + "mali-support.json"
    private const val MARKER = ".droiddeck-mali-support"

    data class Release(val version: String, val url: String, val sha256: String, val size: Long)

    private fun marker(context: Context) = File(LinuxRuntime.rootDir(context), MARKER)
    private fun bridgeDir(context: Context) = File(LinuxRuntime.rootDir(context), "usr/local/lib/droiddeck-mali")
    private fun wsiManifest(context: Context) =
        File(LinuxRuntime.rootDir(context), "usr/share/vulkan/implicit_layer.d/droiddeck-mali-wsi.json")

    fun installedVersion(context: Context): String? {
        val version = FileUtils.readString(marker(context))?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        return if (requiredFiles(context).all { it.isFile || it.isDirectory }) version else null
    }

    fun isInstalled(context: Context): Boolean = installedVersion(context) != null

    private fun requiredFiles(context: Context) = listOf(
        File(bridgeDir(context), "panvk/libvulkan_panfrost.so"),
        File(bridgeDir(context), "panvk/panfrost_icd.json"),
        File(bridgeDir(context), "lib/libsysvk.so"),
        File(bridgeDir(context), "lib/libhardware.so"),
        File(bridgeDir(context), "lib/libVkLayer_window_system_integration.so"),
        File(bridgeDir(context), "lib/libhybris/linker"),
        wsiManifest(context),
    )

    fun fetchRelease(): Release? {
        val body = Downloader.downloadString(MANIFEST_URL) ?: return null
        return try {
            val o = JSONObject(body)
            val version = o.optString("version")
            val url = o.optString("url")
            val sha = o.optString("sha256")
            if (version.isBlank() || !url.startsWith(BASE) || sha.length != 64 || !sha.all { it in "0123456789abcdefABCDEF" }) {
                Log.w(TAG, "invalid Mali support manifest")
                null
            } else Release(version, url, sha.lowercase(), o.optLong("size", 0L))
        } catch (e: Exception) {
            Log.w(TAG, "manifest", e)
            null
        }
    }

    /**
     * Install or update the bridge. Returns null on success, otherwise a user-facing error.
     * Extraction happens in a staging directory and the live bridge is replaced only after the
     * expected files are present, so a bad download never destroys a working installation.
     */
    fun install(context: Context, release: Release, listener: LinuxRuntimeInstaller.ProgressListener? = null): String? {
        val root = LinuxRuntime.rootDir(context)
        if (!LinuxRuntime.isInstalled(context)) return "The Linux runtime is not installed"

        val archive = File(context.cacheDir, "mali-support.tar.zst")
        val staging = File(context.filesDir, "mali-support.staging")
        try {
            listener?.onProgress("Downloading Mali Vulkan support", 0)
            archive.delete()
            val ok = Downloader.downloadFile(release.url, archive, true) { f ->
                listener?.onProgress("Downloading Mali Vulkan support", if (f < 0) -1 else (f * 100f).toInt().coerceIn(0, 100))
            }
            if (!ok) return "Mali Vulkan support download failed"

            listener?.onProgress("Verifying Mali Vulkan support", -1)
            if (!Hashes.sha256(archive).equals(release.sha256, true)) return "Mali Vulkan support checksum mismatch"

            staging.deleteRecursively()
            staging.mkdirs()
            listener?.onProgress("Installing Mali Vulkan support", -1)
            if (!LinuxRuntimeInstaller.extract(archive, staging, listener)) return "Could not extract Mali Vulkan support"

            val stagedBridge = File(staging, "usr/local/lib/droiddeck-mali")
            val stagedWsi = File(staging, "usr/share/vulkan/implicit_layer.d/droiddeck-mali-wsi.json")
            val required = listOf(
                File(stagedBridge, "panvk/libvulkan_panfrost.so"),
                File(stagedBridge, "panvk/panfrost_icd.json"),
                File(stagedBridge, "lib/libsysvk.so"),
                File(stagedBridge, "lib/libhardware.so"),
                File(stagedBridge, "lib/libVkLayer_window_system_integration.so"),
                File(stagedBridge, "lib/libhybris/linker"),
                stagedWsi,
            )
            if (!required.all { it.isFile || it.isDirectory }) return "Mali Vulkan support package is incomplete"

            val targetBridge = bridgeDir(context)
            val oldBridge = File(targetBridge.parentFile, targetBridge.name + ".old")
            oldBridge.deleteRecursively()
            if (targetBridge.exists() && !targetBridge.renameTo(oldBridge)) return "Could not replace the previous Mali bridge"
            targetBridge.parentFile?.mkdirs()
            if (!stagedBridge.renameTo(targetBridge)) {
                oldBridge.renameTo(targetBridge)
                return "Could not place the Mali bridge"
            }

            val targetWsi = wsiManifest(context)
            targetWsi.parentFile?.mkdirs()
            val stagedTarget = File(targetWsi.parentFile, targetWsi.name + ".staged")
            stagedWsi.copyTo(stagedTarget, overwrite = true)
            if (!stagedTarget.renameTo(targetWsi)) {
                targetBridge.deleteRecursively()
                oldBridge.renameTo(targetBridge)
                return "Could not place the Mali WSI manifest"
            }

            oldBridge.deleteRecursively()
            FileUtils.writeString(marker(context), release.version)
            Log.i(TAG, "installed Mali Vulkan support " + release.version)
            return null
        } catch (e: Exception) {
            Log.e(TAG, "install", e)
            return e.message ?: "Mali Vulkan support install failed"
        } finally {
            archive.delete()
            staging.deleteRecursively()
        }
    }

    fun installLatest(context: Context, listener: LinuxRuntimeInstaller.ProgressListener? = null): String? {
        val release = fetchRelease() ?: return "Could not reach the Mali Vulkan support catalog"
        if (installedVersion(context) == release.version) return null
        return install(context, release, listener)
    }

    fun remove(context: Context) {
        bridgeDir(context).deleteRecursively()
        wsiManifest(context).delete()
        marker(context).delete()
    }
}
