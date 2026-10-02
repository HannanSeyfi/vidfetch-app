package com.vidfetch.app.notification

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import androidx.core.app.NotificationCompat

class DownloadNotifier(private val context: Context) {
    private val manager = context.getSystemService(NotificationManager::class.java)

    fun foreground(title: String, progress: Int = 0): Notification {
        ensureChannel()
        return NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle(title)
            .setContentText(if (progress == 0) "Preparing download" else "$progress% complete")
            .setProgress(100, progress, progress == 0)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()
    }

    fun progress(title: String, value: Int) = manager.notify(ID, foreground(title, value))

    fun complete(title: String) {
        ensureChannel()
        manager.notify(ID, NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle("Download complete")
            .setContentText(title)
            .setAutoCancel(true)
            .build())
    }

    fun failed(title: String) {
        ensureChannel()
        manager.notify(ID, NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_notify_error)
            .setContentTitle("Download failed")
            .setContentText(title)
            .setAutoCancel(true)
            .build())
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            manager.createNotificationChannel(NotificationChannel(CHANNEL, "VidFetch downloads", NotificationManager.IMPORTANCE_LOW))
        }
    }

    companion object { const val ID = 7001; private const val CHANNEL = "downloads" }
}
