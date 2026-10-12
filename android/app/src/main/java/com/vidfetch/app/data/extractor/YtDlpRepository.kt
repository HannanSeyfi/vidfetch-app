package com.vidfetch.app.data.extractor

import android.content.Context
import com.vidfetch.app.data.cookies.SiteCookieStore
import com.vidfetch.app.domain.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

data class DownloadResult(val height: Int?)

interface YtDlpRepository {
    suspend fun analyze(url: String): VideoInfo
    suspend fun download(url: String, height: Int?, outputTemplate: String, progress: (Int) -> Unit): DownloadResult
}

class YtDlpRepositoryImpl(private val context: Context) : YtDlpRepository {
    suspend fun updateExtractor(): String = ExtractorRuntime.update(context)
    suspend fun runtimeVersions(): String = ExtractorRuntime.versions(context)

    override suspend fun analyze(url: String): VideoInfo = withContext(Dispatchers.IO) {
        withCookies(url) { cookie ->
            parse(ExtractorRuntime.run(context, baseArguments(cookie) + listOf("--dump-single-json", "--skip-download", "--", url)))
        }
    }

    override suspend fun download(url: String, height: Int?, outputTemplate: String, progress: (Int) -> Unit): DownloadResult = withContext(Dispatchers.IO) {
        withCookies(url) { cookie ->
            val output = ExtractorRuntime.run(context, baseArguments(cookie) + listOf(
                "-f", selectorFor(height, url), "--merge-output-format", "mp4", "-o", outputTemplate,
                "--newline", "--progress", "--progress-template", "download:VIDFETCH_PROGRESS:%(progress._percent_str)s",
                "--print", "after_move:VIDFETCH_HEIGHT:%(height)s", "--", url,
            ), progress)
            DownloadResult(output.lineSequence().firstOrNull { it.startsWith("VIDFETCH_HEIGHT:") }?.substringAfter(':')?.toIntOrNull())
        }
    }

    private fun baseArguments(cookie: File?) = buildList {
        addAll(listOf("--ignore-config", "--no-playlist", "--continue", "--retries", "10", "--fragment-retries", "10", "--socket-timeout", "30", "--no-cache-dir"))
        val native = context.applicationInfo.nativeLibraryDir
        addAll(listOf("--js-runtimes", "quickjs:$native/libqjs-cli.so", "--ffmpeg-location", "$native/libffmpeg.so"))
        cookie?.let { addAll(listOf("--cookies", it.absolutePath)) }
        // Extractors can use curl_cffi themselves; do not force impersonation on every site.
    }

    private suspend fun <T> withCookies(url: String, action: suspend (File?) -> T): T {
        val cookie = SiteCookieStore(context).snapshotFor(url)
        return try { action(cookie) } finally { cookie?.delete() }
    }

    private fun parse(raw: String): VideoInfo {
        val json = JSONObject(raw)
        val items = json.optJSONArray("formats") ?: JSONArray().apply { put(json) }
        val formats = (0 until items.length()).map { items.getJSONObject(it).toFormat() }
        return VideoInfo(json.optString("id").ifBlank { null }, json.optString("title", "Untitled video"),
            json.optString("uploader").ifBlank { null }, json.optString("webpage_url", json.optString("original_url")),
            json.optString("thumbnail").ifBlank { null }, json.optLong("duration").takeIf { it > 0 }, formats)
    }

    private fun JSONObject.toFormat() = VideoFormat(optString("format_id"), optInt("height").takeIf { it > 0 }, optInt("width").takeIf { it > 0 },
        optDouble("fps").takeIf { !it.isNaN() }, optString("ext").ifBlank { null }, optString("vcodec").ifBlank { null },
        optString("acodec").ifBlank { null }, optLong("filesize").takeIf { it > 0 }, optLong("filesize_approx").takeIf { it > 0 },
        optDouble("tbr").takeIf { !it.isNaN() }, optString("vcodec") !in listOf("", "none"), optString("acodec") !in listOf("", "none"))
}
