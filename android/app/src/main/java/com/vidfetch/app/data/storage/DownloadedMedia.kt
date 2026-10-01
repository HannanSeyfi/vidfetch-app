package com.vidfetch.app.data.storage

import android.content.Context
import android.media.MediaScannerConnection
import android.os.Environment
import com.vidfetch.app.domain.formatBytes
import java.io.File

data class DownloadedMedia(val file: File) {
    val title: String get() = file.name
    val size: String get() = formatBytes(file.length())
}

/** Reads only VidFetch's dedicated public download directory; no broad-storage permission is used. */
class DownloadedMediaRepository(private val context: Context) {
    private val directory = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "VidFetch")

    fun list(): List<DownloadedMedia> = directory.listFiles()
        ?.filter { it.isFile && !it.name.endsWith(".part") }
        ?.sortedByDescending { it.lastModified() }
        ?.map(::DownloadedMedia)
        .orEmpty()

    fun scanNewFiles(before: Set<String>) {
        val paths = directory.listFiles()?.filter { it.isFile && it.absolutePath !in before }?.map(File::getAbsolutePath).orEmpty()
        if (paths.isNotEmpty()) MediaScannerConnection.scanFile(context, paths.toTypedArray(), null, null)
    }

    fun existingPaths(): Set<String> = directory.listFiles()?.map(File::getAbsolutePath)?.toSet().orEmpty()
    fun outputDirectory(): File = directory.apply { mkdirs() }
}
