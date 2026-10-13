package com.vidfetch.app.data.extractor

import android.content.Context
import com.vidfetch.app.data.cookies.SiteCookieStore
import com.vidfetch.app.domain.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

data class DownloadResult(val height: Int?, val file: File)

interface YtDlpRepository {
    suspend fun analyze(url: String): VideoInfo
    suspend fun download(url: String, height: Int?, outputTemplate: String, progress: (Int) -> Unit): DownloadResult
}

class YtDlpRepositoryImpl(private val context: Context) : YtDlpRepository {
    suspend fun updateExtractor(): String = ExtractorRuntime.update(context)
    suspend fun runtimeVersions(): String = ExtractorRuntime.versions(context)

    override suspend fun analyze(url: String): VideoInfo = withContext(Dispatchers.IO) {
        withCookies(url) { cookie ->
            extractWithCompatibility(url) { backend ->
                parseVideoInfo(ExtractorRuntime.run(context, analysisArguments(cookie, url), backend = backend))
            }
        }
    }

    override suspend fun download(url: String, height: Int?, outputTemplate: String, progress: (Int) -> Unit): DownloadResult = withContext(Dispatchers.IO) {
        withCookies(url) { cookie ->
            extractWithCompatibility(url) { backend ->
                val output = ExtractorRuntime.run(context, downloadArguments(cookie, url, height, outputTemplate), progress, backend)
                completedDownload(output, outputTemplate)
            }
        }
    }

    internal fun analysisArguments(cookie: File?, url: String) = baseArguments(cookie) + listOf("--dump-single-json", "--skip-download", "--", url)

    internal fun downloadArguments(cookie: File?, url: String, height: Int?, outputTemplate: String): List<String> {
        // Any retried site request starts clean, including a retry on the modern runtime.
        val restart = if (supportsCompatibility(url)) listOf("--force-overwrites", "--no-continue") else emptyList()
        val youtube = if (siteForUrl(url) == "youtube.com") listOf("--format-sort", "res,vcodec:h264,acodec:aac", "--remux-video", "mp4") else emptyList()
        return baseArguments(cookie) + restart + youtube + listOf(
            "-f", selectorFor(height, url), "--merge-output-format", "mp4", "-o", outputTemplate,
            "--newline", "--progress", "--progress-template", "download:VIDFETCH_PROGRESS:%(progress._percent_str)s",
            "--print", "after_move:VIDFETCH_HEIGHT:%(height)s",
            "--print", "after_move:VIDFETCH_FILE:%(filepath)j", "--", url,
        )
    }

    internal suspend fun completedDownload(output: String, outputTemplate: String): DownloadResult {
        val value = output.lineSequence().lastOrNull { it.startsWith("VIDFETCH_FILE:") }?.substringAfter(':')
            ?: error("The extractor did not report a completed video. Video/audio merging may have failed.")
        val file = File(JSONArray("[$value]").getString(0)).canonicalFile
        val folder = File(outputTemplate).parentFile!!.canonicalFile
        check(file.parentFile == folder && file.isFile && file.length() > 0) { "The completed video is missing. Video/audio merging may have failed." }
        check(file.extension.lowercase() in videoFileExtensions) { "The downloaded file is not a video file." }
        val probe = JSONObject(ExtractorRuntime.media(context, "ffprobe", listOf("-v", "error", "-show_streams", "-of", "json", file.absolutePath)))
        val streams = probe.getJSONArray("streams")
        val video = (0 until streams.length()).map { streams.getJSONObject(it) }.firstOrNull {
            it.optString("codec_type") == "video" && it.optJSONObject("disposition")?.optInt("attached_pic") != 1
        } ?: error("The downloaded file contains no video stream. It was not saved to Downloads.")
        return DownloadResult(video.optInt("height").takeIf { it > 0 }, file)
    }

    private fun baseArguments(cookie: File?) = buildList {
        addAll(listOf("--ignore-config", "--no-playlist", "--continue", "--retries", "10", "--fragment-retries", "10", "--socket-timeout", "30"))
        val native = context.applicationInfo.nativeLibraryDir
        addAll(listOf("--no-cache-dir", "--js-runtimes", "quickjs:$native/libqjs-cli.so"))
        addAll(listOf("--ffmpeg-location", "$native/libffmpeg.so"))
        cookie?.let { addAll(listOf("--cookies", it.absolutePath)) }
        // Extractors can use curl_cffi themselves; do not force impersonation on every site.
    }

    private suspend fun <T> withCookies(url: String, action: suspend (File?) -> T): T {
        val cookie = SiteCookieStore(context).snapshotFor(url)
        return try { action(cookie) } finally { cookie?.delete() }
    }

    internal fun parseVideoInfo(raw: String): VideoInfo {
        val json = JSONObject(raw)
        val items = json.optJSONArray("formats") ?: JSONArray().apply { put(json) }
        val formats = (0 until items.length()).map { items.getJSONObject(it).toFormat() }
        return VideoInfo(json.optString("id").ifBlank { null }, json.optString("title", "Untitled video"),
            json.optString("uploader").ifBlank { null }, json.optString("webpage_url", json.optString("original_url")),
            json.optString("thumbnail").ifBlank { null }, json.optLong("duration").takeIf { it > 0 }, formats)
    }

    private fun JSONObject.toFormat(): VideoFormat {
        val videoCodec = optString("vcodec").takeUnless { it.isBlank() || it == "null" }
        // Direct MP4 extractors such as Pornhub may provide a resolution without a codec.
        // yt-dlp uses "none" to explicitly identify formats without video.
        return VideoFormat(optString("format_id"), optInt("height").takeIf { it > 0 }, optInt("width").takeIf { it > 0 },
            optDouble("fps").takeIf { !it.isNaN() }, optString("ext").ifBlank { null }, videoCodec,
            optString("acodec").ifBlank { null }, optLong("filesize").takeIf { it > 0 }, optLong("filesize_approx").takeIf { it > 0 },
            optDouble("tbr").takeIf { !it.isNaN() }, videoCodec != "none", optString("acodec") !in listOf("", "none"))
    }
}
