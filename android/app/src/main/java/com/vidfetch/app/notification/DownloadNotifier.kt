package com.vidfetch.app.notification

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import com.vidfetch.app.MainActivity
import com.vidfetch.app.service.DownloadService
import com.vidfetch.app.service.DownloadState

class DownloadNotifier(private val context: Context) {
    private val manager = context.getSystemService(NotificationManager::class.java)
    private fun open() = PendingIntent.getActivity(context, 0, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    fun summary(): Notification {
        ensureChannel()
        val count = DownloadState.progress.value.downloads.count { it.active }
        return NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle("VidFetch downloads")
            .setContentText("$count active · Tap to view downloads")
            .setContentIntent(open()).setOngoing(true).setOnlyAlertOnce(true)
            .setGroup(GROUP).setGroupSummary(true).build()
    }

    fun refreshSummary() = manager.notify(ID, summary())

    fun task(id: String, title: String, text: String, progress: Int?) {
        ensureChannel()
        val cancel = PendingIntent.getService(context, 0,
            DownloadService.cancelIntent(context, id).setData(Uri.parse("vidfetch://cancel/$id")),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        manager.notify(id, TASK_ID, NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle(title).setContentText(text).setContentIntent(open())
            .setProgress(100, progress ?: 0, progress == null)
            .addAction(android.R.drawable.ic_menu_close_clear_cancel, "Cancel", cancel)
            .setGroup(GROUP).setOngoing(true).setOnlyAlertOnce(true).build())
    }

    fun cancel(id: String) = manager.cancel(id, TASK_ID)

    fun finished(id: String, title: String, success: Boolean) {
        ensureChannel()
        manager.notify(id, TASK_ID, NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(if (success) android.R.drawable.stat_sys_download_done else android.R.drawable.stat_notify_error)
            .setContentTitle(if (success) "Download complete" else "Download failed")
            .setContentText(title).setContentIntent(open())
            .setGroup(GROUP).setAutoCancel(true).build())
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT >= 26) manager.createNotificationChannel(NotificationChannel(CHANNEL, "VidFetch downloads", NotificationManager.IMPORTANCE_LOW))
    }

    companion object {
        const val ID = 7001
        private const val TASK_ID = 7002
        private const val CHANNEL = "downloads"
        private const val GROUP = "vidfetch.downloads"
    }
}
