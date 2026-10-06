package com.droiddeck.launcher.gpu

import android.system.OsConstants

/**
 * Capability probe for stock ARM mali_kbase (/dev/mali0).
 *
 * The important distinction for DroidDeck is not merely "Mali".  A glibc PanVK package must match
 * the kernel command frontend and Kbase UAPI it was built against.  This object asks the native
 * probe for exactly those values and caches the throw-away-fd result for the life of the process.
 */
object MaliKbaseProbe {
    enum class Frontend { UNKNOWN, JM, CSF }

    data class Result(
        val usable: Boolean,
        val frontend: Frontend,
        val uapiMajor: Int,
        val uapiMinor: Int,
        val productId: Long,
        val versionStatus: Int,
        val majorRevision: Int,
        val minorRevision: Int,
        val shaderPresent: Long,
        val errno: Int,
        val gpuId: Long = 0L,
    ) {
        val shaderCores: Int get() = java.lang.Long.bitCount(shaderPresent)
        /**
         * Kbase trees do not all expose the GPU identifier in the same width. Some report the
         * 16-bit product code (for example 0xb8a3), while public validation logs often use the
         * full 32-bit GPU ID (for example 0xb8a31030). Compatibility must compare the product
         * code, not the revision/status suffix.
         */
        val productCode: Long get() = canonicalProductId(if (productId != 0L) productId else gpuId)
        val productIdHex: String get() = formatGpuId(productId)
        val gpuIdHex: String get() = formatGpuId(gpuId)
        val productCodeHex: String get() = if (productCode == 0L) "desconocido" else "0x%04x".format(productCode)
        val uapi: String get() = if (uapiMajor > 0) "$uapiMajor.$uapiMinor" else "desconocida"
        val frontendName: String get() = frontend.name.lowercase()

        fun shortSummary(): String = when {
            usable -> buildString {
                append("Kbase ").append(frontend.name).append(" UAPI ").append(uapi)
                if (productCode != 0L) append(" · producto ").append(productCodeHex)
                if (gpuId != 0L) append(" · GPU ID ").append(gpuIdHex)
                if (shaderCores > 0) append(" · ").append(shaderCores).append(" núcleos")
            }
            errno != 0 -> "/dev/mali0 no disponible (${MaliKbaseProbe.errnoName(errno)})"
            else -> "/dev/mali0 no respondió a un VERSION_CHECK Kbase compatible"
        }
    }

    private val cached: Result by lazy { readNative() }

    @JvmStatic
    fun probe(): Result = cached

    @JvmStatic
    fun usable(): Boolean = cached.usable

    /** Normalize a Kbase product/GPU id to the 16-bit product code used by Mesa profiles. */
    @JvmStatic
    fun canonicalProductId(value: Long): Long = when {
        value <= 0L -> 0L
        value <= 0xffffL -> value
        else -> (value ushr 16) and 0xffffL
    }

    private fun formatGpuId(value: Long): String = when {
        value <= 0L -> "desconocido"
        value <= 0xffffL -> "0x%04x".format(value)
        value <= 0xffffffffL -> "0x%08x".format(value)
        else -> "0x%x".format(value)
    }

    private fun readNative(): Result {
        return try {
            System.loadLibrary("sdnative")
            val r = nativeProbe()
            if (r.size < 10) return Result(false, Frontend.UNKNOWN, 0, 0, 0, 0, 0, 0, 0, 0)
            Result(
                usable = r[0] != 0L,
                frontend = when (r[1].toInt()) { 1 -> Frontend.JM; 2 -> Frontend.CSF; else -> Frontend.UNKNOWN },
                uapiMajor = r[2].toInt(),
                uapiMinor = r[3].toInt(),
                productId = r[4],
                versionStatus = r[5].toInt(),
                majorRevision = r[6].toInt(),
                minorRevision = r[7].toInt(),
                shaderPresent = r[8],
                errno = r[9].toInt(),
                gpuId = if (r.size > 10) r[10] else 0L,
            )
        } catch (_: Throwable) {
            Result(false, Frontend.UNKNOWN, 0, 0, 0, 0, 0, 0, 0, 0)
        }
    }

    private fun errnoName(errno: Int): String = when (errno) {
        OsConstants.EACCES -> "EACCES"
        OsConstants.EPERM -> "EPERM"
        OsConstants.ENOENT -> "ENOENT"
        OsConstants.ENODEV -> "ENODEV"
        OsConstants.ENOTTY -> "ENOTTY"
        OsConstants.EINVAL -> "EINVAL"
        else -> "errno $errno"
    }

    @JvmStatic
    private external fun nativeProbe(): LongArray
}
