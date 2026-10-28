package com.vidfetch.app.service

import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import com.vidfetch.app.data.extractor.YtDlpRepositoryImpl
import com.vidfetch.app.data.storage.DownloadedMediaRepository
import com.vidfetch.app.domain.DownloadStatus
import com.vidfetch.app.notification.DownloadNotifier
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import java.io.File
import java.util.UUID

class DownloadService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val jobs = mutableMapOf<String, Job>()
    private val slots = Semaphore(2)
    private var lastStartId = 0
    private lateinit var notifier: DownloadNotifier

    override fun onCreate() {
        super.onCreate()
        notifier = DownloadNotifier(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        lastStartId = startId
        if (intent?.action == ACTION_CANCEL) {
            intent.getStringExtra(EXTRA_ID)?.let { jobs[it]?.cancel() }
            if (jobs.isEmpty()) stopSelf(startId)
            return START_NOT_STICKY
        }
        val url = intent?.getStringExtra(EXTRA_URL).orEmpty()
        if (url.isBlank()) {
            if (jobs.isEmpty()) stopSelf(startId)
            return START_NOT_STICKY
        }
        val id = intent?.getStringExtra(EXTRA_ID) ?: UUID.randomUUID().toString()
        if (id in jobs) return START_NOT_STICKY
        val title = intent?.getStringExtra(EXTRA_TITLE).orEmpty().ifBlank { "Video" }
        val height = intent!!.getIntExtra(EXTRA_HEIGHT, 0).takeIf { it > 0 }
        val audioOnly = intent.getBooleanExtra(EXTRA_AUDIO_ONLY, false)
        val quality = if (audioOnly) "Audio only" else height?.let { "${it}p" } ?: "Best video"
        DownloadState.queued(id, title, quality)
        startForeground(DownloadNotifier.ID, notifier.summary())
        notifier.task(id, title, "Waiting for a download slot", null)
        val job = scope.launch(Dispatchers.IO, start = CoroutineStart.LAZY) {
            var working: File? = null
            try {
                slots.withPermit {
                    DownloadState.status(id, DownloadStatus.DOWNLOADING)
                    val media = DownloadedMediaRepository(applicationContext)
                    working = media.workingDirectory()
                    val output = File(working, "%(title).180B.%(ext)s").absolutePath
                    var lastProgress = -1
                    val result = YtDlpRepositoryImpl(applicationContext).download(url, height, output, audioOnly) { value ->
                        val next = value.coerceIn(0, 99)
                        if (next != lastProgress) {
                            lastProgress = next
                            DownloadState.advanced(id, next)
                            notifier.task(id, title, "$quality · $next%", next)
                        }
                    }
                    currentCoroutineContext().ensureActive()
                    DownloadState.status(id, DownloadStatus.MERGING, "Saving to Downloads/VidFetch…")
                    notifier.task(id, title, "Saving to Downloads/VidFetch…", null)
                    val downloadContext = currentCoroutineContext()
                    media.publish(result.file) { downloadContext.ensureActive() }
                    val actualQuality = if (audioOnly) " · Audio only" else if (height != null && result.height != null && result.height != height) " · Downloaded ${result.height}p (requested ${height}p)" else ""
                    DownloadState.finished(id, "Saved to Downloads/VidFetch$actualQuality")
                    notifier.finished(id, title, true)
                }
            } catch (error: CancellationException) {
                DownloadState.cancelled(id)
                notifier.cancel(id)
                throw error
            } catch (error: Exception) {
                DownloadState.failed(id, error.message ?: "Download failed")
                notifier.finished(id, title, false)
            } finally {
                working?.deleteRecursively()
            }
        }
        jobs[id] = job
        job.invokeOnCompletion {
            scope.launch {
                jobs.remove(id)
                if (DownloadState.progress.value.downloads.any { it.id == id && it.active }) {
                    DownloadState.cancelled(id)
                    notifier.cancel(id)
                }
                if (jobs.isEmpty()) {
                    stopForeground(STOP_FOREGROUND_REMOVE)
                    stopSelfResult(lastStartId)
                } else notifier.refreshSummary()
            }
        }
        job.start()
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        jobs.keys.toList().forEach { id ->
            DownloadState.cancelled(id)
            notifier.cancel(id)
        }
        scope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val ACTION_CANCEL = "com.vidfetch.app.CANCEL_DOWNLOAD"
        const val EXTRA_ID = "download_id"
        const val EXTRA_URL = "download_url"
        const val EXTRA_TITLE = "download_title"
        const val EXTRA_HEIGHT = "download_height"
        const val EXTRA_AUDIO_ONLY = "download_audio_only"

        fun cancelIntent(context: Context, id: String) = Intent(context, DownloadService::class.java)
            .setAction(ACTION_CANCEL).putExtra(EXTRA_ID, id)
    }
}
