package com.vidfetch.app.notification

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import androidx.core.app.NotificationCompat

class DownloadNotifier(private val context: Context) {
    private val manager = context.getSystemService(NotificationManager::class.java)

    fun progress(title: String, value: Int) {
        ensureChannel()
        manager.notify(ID, NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle("Downloading $title")
            .setContentText("$value% complete")
            .setProgress(100, value, false)
            .setOngoing(true)
            .build())
    }

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
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "VidFetch downloads", NotificationManager.IMPORTANCE_LOW))
    }

    companion object { private const val CHANNEL = "downloads"; private const val ID = 7001 }
}
