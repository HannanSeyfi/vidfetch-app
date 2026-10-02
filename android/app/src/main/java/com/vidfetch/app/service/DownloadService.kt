package com.vidfetch.app.service

import android.app.Service
import android.content.Intent
import android.os.IBinder
import com.vidfetch.app.data.extractor.YtDlpRepositoryImpl
import com.vidfetch.app.data.storage.DownloadedMediaRepository
import com.vidfetch.app.notification.DownloadNotifier
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.io.File

data class DownloadProgress(
    val active: Boolean = false,
    val title: String = "",
    val percent: Int = 0,
    val message: String? = null,
    val completion: Long = 0,
)

/** Process-local state for the UI; completed files remain the durable source of truth. */
object DownloadState {
    private val mutable = MutableStateFlow(DownloadProgress())
    val progress = mutable.asStateFlow()

    fun started(title: String) { mutable.value = DownloadProgress(active = true, title = title) }
    fun advanced(percent: Int) { mutable.value = mutable.value.copy(percent = percent) }
    fun finished(message: String) {
        mutable.value = mutable.value.copy(active = false, percent = 100, message = message, completion = mutable.value.completion + 1)
    }
    fun failed(message: String) { mutable.value = mutable.value.copy(active = false, message = message) }
}

class DownloadService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var job: Job? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (job?.isActive == true) return START_NOT_STICKY
        val url = intent?.getStringExtra(EXTRA_URL).orEmpty()
        val title = intent?.getStringExtra(EXTRA_TITLE).orEmpty().ifBlank { "Video" }
        if (url.isBlank()) {
            stopSelf(startId)
            return START_NOT_STICKY
        }
        val notifier = DownloadNotifier(this)
        startForeground(DownloadNotifier.ID, notifier.foreground(title))
        DownloadState.started(title)
        job = scope.launch {
            val media = DownloadedMediaRepository(applicationContext)
            var working: File? = null
            try {
                working = media.workingDirectory()
                val output = File(working, "%(title).180B.%(ext)s").absolutePath
                var lastProgress = -1
                YtDlpRepositoryImpl(applicationContext).download(url, intent!!.getIntExtra(EXTRA_HEIGHT, 0).takeIf { it > 0 }, output) { value ->
                    val next = value.coerceIn(0, 99)
                    if (next != lastProgress) {
                        lastProgress = next
                        DownloadState.advanced(next)
                        notifier.progress(title, next)
                    }
                }
                DownloadState.advanced(99)
                media.publish(media.finishedVideo(working))
                DownloadState.finished("Saved to Downloads/VidFetch")
                stopForeground(STOP_FOREGROUND_REMOVE)
                notifier.complete(title)
            } catch (error: CancellationException) {
                DownloadState.failed("Download interrupted")
                throw error
            } catch (error: Exception) {
                DownloadState.failed(error.message ?: "Download failed")
                stopForeground(STOP_FOREGROUND_REMOVE)
                notifier.failed(title)
            } finally {
                working?.deleteRecursively()
                stopSelf(startId)
            }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val EXTRA_URL = "download_url"
        const val EXTRA_TITLE = "download_title"
        const val EXTRA_HEIGHT = "download_height"
    }
}
