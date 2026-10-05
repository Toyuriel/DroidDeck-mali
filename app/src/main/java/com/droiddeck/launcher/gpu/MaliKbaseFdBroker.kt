package com.droiddeck.launcher.gpu

import android.net.LocalServerSocket
import android.net.LocalSocket
import android.os.ParcelFileDescriptor
import android.util.Log
import com.droiddeck.launcher.core.SessionPart
import java.io.File

/**
 * Gives the Linux guest a fresh Kbase fd without bind-mounting /dev/mali0 through PRoot.
 *
 * The socket lives in Linux's abstract AF_UNIX namespace, which is shared with the guest. Each
 * client request gets a newly opened /dev/mali0 sent with SCM_RIGHTS. PanVK therefore receives a
 * real Kbase file description while Android keeps filesystem/device policy on the host side.
 */
class MaliKbaseFdBroker(val socketName: String) : SessionPart() {
    companion object {
        private const val TAG = "MaliKbaseFdBroker"
    }

    @Volatile private var running = false
    private var server: LocalServerSocket? = null
    private var worker: Thread? = null

    override fun start() {
        if (running) return
        try {
            val srv = LocalServerSocket(socketName)
            server = srv
            running = true
            worker = Thread({
                while (running) {
                    var client: LocalSocket? = null
                    var kbase: ParcelFileDescriptor? = null
                    try {
                        client = srv.accept()
                        kbase = ParcelFileDescriptor.open(
                            File("/dev/mali0"),
                            ParcelFileDescriptor.MODE_READ_WRITE,
                        )
                        client.setFileDescriptorsForSend(arrayOf(kbase.fileDescriptor))
                        client.outputStream.write(1)
                        client.outputStream.flush()
                        client.setFileDescriptorsForSend(null)
                        Log.i(TAG, "sent fresh /dev/mali0 fd to PanVK")
                    } catch (e: Exception) {
                        if (running) {
                            Log.w(TAG, "serving Kbase fd", e)
                            runCatching {
                                client?.outputStream?.write(0)
                                client?.outputStream?.flush()
                            }
                        }
                    } finally {
                        runCatching { client?.setFileDescriptorsForSend(null) }
                        runCatching { kbase?.close() }
                        runCatching { client?.close() }
                    }
                }
            }, "mali-kbase-broker").apply {
                isDaemon = true
                start()
            }
            Log.i(TAG, "listening on abstract socket $socketName")
        } catch (e: Exception) {
            running = false
            runCatching { server?.close() }
            server = null
            throw e
        }
    }

    override fun stop() {
        running = false
        runCatching { server?.close() }
        server = null
        worker?.interrupt()
        worker = null
    }
}
