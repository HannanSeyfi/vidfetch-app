package com.vidfetch.app.data.storage

import android.content.ContentUris
import android.content.ContentValues
import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import androidx.annotation.RequiresApi
import androidx.core.content.FileProvider
import com.vidfetch.app.domain.formatBytes
import java.io.File

data class DownloadedMedia(
    val uri: Uri,
    val title: String,
    val sizeBytes: Long,
    val modifiedAt: Long,
    val legacyFile: File? = null,
    val pending: Boolean = false,
) {
    val id: String get() = uri.toString()
    val size: String get() = formatBytes(sizeBytes)
}

/** Publishes completed videos while keeping yt-dlp's working files private to the app. */
class DownloadedMediaRepository(private val context: Context) {
    private val directory = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "VidFetch")
    private val resolver = context.contentResolver
    private val videoExtensions = setOf("mp4", "mkv", "webm", "mov", "m4v", "avi", "ts")

    fun list(): List<DownloadedMedia> {
        val indexed = if (Build.VERSION.SDK_INT >= 29) listIndexed() else emptyList()
        // Files made by older VidFetch versions may not have a MediaStore owner or row.
        val indexedNames = indexed.mapTo(HashSet()) { it.title }
        val legacy = runCatching { directory.listFiles().orEmpty() }.getOrDefault(emptyArray())
            .filter { it.isFile && it.canRead() && it.extension.lowercase() in videoExtensions && it.name !in indexedNames }
            .map(::legacyItem)
        return (indexed.filterNot { it.pending } + legacy).sortedByDescending { it.modifiedAt }
    }

    private fun legacyItem(file: File) = DownloadedMedia(
        uri = FileProvider.getUriForFile(context, "${context.packageName}.files", file),
        title = file.name,
        sizeBytes = file.length(),
        modifiedAt = file.lastModified(),
        legacyFile = file,
    )

    @RequiresApi(29)
    private fun listIndexed(): List<DownloadedMedia> {
        val result = mutableListOf<DownloadedMedia>()
        val collection = MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        val columns = arrayOf(
            MediaStore.Downloads._ID,
            MediaStore.Downloads.DISPLAY_NAME,
            MediaStore.Downloads.SIZE,
            MediaStore.Downloads.DATE_MODIFIED,
            MediaStore.Downloads.IS_PENDING,
        )
        val path = "${Environment.DIRECTORY_DOWNLOADS}/VidFetch/"
        resolver.query(collection, columns, "${MediaStore.Downloads.RELATIVE_PATH} = ?", arrayOf(path), null)?.use { cursor ->
            val id = cursor.getColumnIndexOrThrow(MediaStore.Downloads._ID)
            val name = cursor.getColumnIndexOrThrow(MediaStore.Downloads.DISPLAY_NAME)
            val size = cursor.getColumnIndexOrThrow(MediaStore.Downloads.SIZE)
            val modified = cursor.getColumnIndexOrThrow(MediaStore.Downloads.DATE_MODIFIED)
            val pending = cursor.getColumnIndexOrThrow(MediaStore.Downloads.IS_PENDING)
            while (cursor.moveToNext()) {
                val title = cursor.getString(name) ?: continue
                if (title.substringAfterLast('.', "").lowercase() !in videoExtensions) continue
                result += DownloadedMedia(
                    uri = ContentUris.withAppendedId(collection, cursor.getLong(id)),
                    title = title,
                    sizeBytes = cursor.getLong(size),
                    modifiedAt = cursor.getLong(modified) * 1000,
                    pending = cursor.getInt(pending) != 0,
                )
            }
        }
        return result
    }

    fun workingDirectory(): File {
        val root = requireNotNull(context.getExternalFilesDir(null)) { "App storage is unavailable." }
        val workRoot = File(root, "downloads")
        check(workRoot.isDirectory || workRoot.mkdirs()) { "Could not prepare download storage." }
        val staleBefore = System.currentTimeMillis() - 24 * 60 * 60 * 1000L
        workRoot.listFiles().orEmpty().filter { it.isDirectory && it.lastModified() < staleBefore }.forEach { it.deleteRecursively() }
        val folder = File(workRoot, "${System.currentTimeMillis()}-${java.util.UUID.randomUUID()}")
        check(folder.mkdirs()) { "Could not prepare download storage." }
        return folder
    }

    fun finishedVideo(folder: File): File = folder.listFiles().orEmpty()
        .filter { it.isFile && it.extension.lowercase() in videoExtensions }
        .maxByOrNull(File::lastModified)
        ?: error("The download finished without a playable video file.")

    fun publish(file: File) {
        if (Build.VERSION.SDK_INT >= 29) {
            val displayName = uniqueName(file.name, list().mapTo(HashSet()) { it.title })
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, displayName)
                put(MediaStore.Downloads.MIME_TYPE, mimeType(file.extension))
                put(MediaStore.Downloads.RELATIVE_PATH, "${Environment.DIRECTORY_DOWNLOADS}/VidFetch/")
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
            val uri = resolver.insert(MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY), values)
                ?: error("Could not create a Downloads entry.")
            try {
                val output = resolver.openOutputStream(uri) ?: error("Could not open the Downloads entry.")
                output.use { stream -> file.inputStream().use { it.copyTo(stream) } }
                values.clear()
                values.put(MediaStore.Downloads.IS_PENDING, 0)
                check(resolver.update(uri, values, null, null) > 0) { "Could not finalize the download." }
            } catch (error: Exception) {
                runCatching { resolver.delete(uri, null, null) }
                throw error
            }
        } else {
            check(directory.isDirectory || directory.mkdirs()) { "Could not create Downloads/VidFetch." }
            val target = uniqueFile(directory, file.name)
            check(target.createNewFile()) { "Could not reserve a file in Downloads/VidFetch." }
            try {
                target.outputStream().use { stream -> file.inputStream().use { it.copyTo(stream) } }
            } catch (error: Exception) {
                target.delete()
                throw error
            }
            MediaScannerConnection.scanFile(context, arrayOf(target.absolutePath), null, null)
        }
    }

    fun rename(item: DownloadedMedia, requestedName: String): Boolean {
        val extension = item.title.substringAfterLast('.', "mp4")
        val base = cleanName(requestedName.removeSuffix(".$extension")) ?: return false
        val name = "$base.$extension"
        if (name == item.title) return true
        if (list().any { it.title == name }) return false
        return if (item.legacyFile != null) {
            val old = item.legacyFile
            val target = File(directory, name)
            val renamed = !target.exists() && old.renameTo(target)
            if (renamed) MediaScannerConnection.scanFile(context, arrayOf(old.absolutePath, target.absolutePath), null, null)
            renamed
        } else {
            val values = ContentValues().apply { put(MediaStore.Downloads.DISPLAY_NAME, name) }
            resolver.update(item.uri, values, null, null) > 0
        }
    }

    fun delete(item: DownloadedMedia): Boolean = if (item.legacyFile != null) {
        val deleted = item.legacyFile.delete()
        if (deleted) MediaScannerConnection.scanFile(context, arrayOf(item.legacyFile.absolutePath), null, null)
        deleted
    } else resolver.delete(item.uri, null, null) > 0

    fun open(item: DownloadedMedia) {
        context.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(item.uri, mimeType(item.title.substringAfterLast('.')))
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    fun share(item: DownloadedMedia) {
        val send = Intent(Intent.ACTION_SEND).setType(mimeType(item.title.substringAfterLast('.')))
            .putExtra(Intent.EXTRA_STREAM, item.uri)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        send.clipData = ClipData.newUri(resolver, item.title, item.uri)
        context.startActivity(Intent.createChooser(send, "Share video").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    private fun mimeType(extension: String) = when (extension.lowercase()) {
        "mp4", "m4v" -> "video/mp4"
        "webm" -> "video/webm"
        "mkv" -> "video/x-matroska"
        "mov" -> "video/quicktime"
        "avi" -> "video/x-msvideo"
        "ts" -> "video/mp2t"
        else -> "video/*"
    }
}

internal fun cleanName(value: String): String? = value.trim()
    .replace(Regex("[\\\\/:*?\"<>|]"), "_")
    .trimEnd('.', ' ')
    .take(140)
    .ifBlank { null }

internal fun uniqueFile(directory: File, name: String): File {
    val first = File(directory, name)
    if (!first.exists()) return first
    val base = name.substringBeforeLast('.')
    val extension = name.substringAfterLast('.', "")
    return generateSequence(2) { it + 1 }
        .map { File(directory, "$base ($it)${if (extension.isEmpty()) "" else ".$extension"}") }
        .first { !it.exists() }
}

internal fun uniqueName(name: String, existing: Set<String>): String {
    if (name !in existing) return name
    val base = name.substringBeforeLast('.')
    val extension = name.substringAfterLast('.', "")
    return generateSequence(2) { it + 1 }
        .map { "$base ($it)${if (extension.isEmpty()) "" else ".$extension"}" }
        .first { it !in existing }
}
