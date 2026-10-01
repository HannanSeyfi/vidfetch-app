package com.vidfetch.app.service

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.vidfetch.app.R

class DownloadService : Service() {
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int { createChannel(); startForeground(7, NotificationCompat.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.stat_sys_download).setContentTitle("VidFetch").setContentText("Preparing download").setOngoing(true).build()); return START_NOT_STICKY }
    override fun onBind(intent: Intent?): IBinder? = null
    private fun createChannel() { (getSystemService(NotificationManager::class.java)).createNotificationChannel(NotificationChannel(CHANNEL, "VidFetch downloads", NotificationManager.IMPORTANCE_LOW)) }
    companion object { const val CHANNEL = "downloads" }
}
