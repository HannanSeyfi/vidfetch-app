package com.vidfetch.app.data.storage

import android.content.Context
import android.content.Intent
import android.media.MediaScannerConnection
import android.os.Environment
import androidx.core.content.FileProvider
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

    fun rename(item: DownloadedMedia, requestedName: String): Boolean {
        val cleaned = requestedName.trim().replace(Regex("[\\\\/:*?\"<>|]"), "_").ifBlank { return false }
        val target = File(directory, if (cleaned.contains('.')) cleaned else "$cleaned.${item.file.extension}")
        return target != item.file && !target.exists() && item.file.renameTo(target)
    }

    fun delete(item: DownloadedMedia): Boolean = item.file.delete()

    fun open(item: DownloadedMedia) {
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", item.file)
        context.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "video/*").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    fun share(item: DownloadedMedia) {
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", item.file)
        context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("video/*").putExtra(Intent.EXTRA_STREAM, uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION), "Share video").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}
