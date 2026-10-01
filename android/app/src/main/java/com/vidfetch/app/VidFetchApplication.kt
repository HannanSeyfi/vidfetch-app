package com.vidfetch.app

import android.app.Application
import android.util.Log
import com.yausername.ffmpeg.FFmpeg
import com.yausername.youtubedl_android.YoutubeDL

class VidFetchApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        try {
            YoutubeDL.getInstance().init(this)
            FFmpeg.getInstance().init(this)
        } catch (error: Throwable) {
            // A native runtime failure must not prevent the UI from opening.
            Log.e("VidFetch", "Local downloader initialization failed", error)
        }
    }
}
