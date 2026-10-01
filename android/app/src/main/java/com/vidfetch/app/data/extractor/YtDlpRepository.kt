package com.vidfetch.app.data.extractor

import android.content.Context
import com.vidfetch.app.domain.*
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

interface YtDlpRepository { suspend fun analyze(url: String): VideoInfo; suspend fun download(url: String, height: Int?, outputTemplate: String, progress: (Int) -> Unit): String }

class YtDlpRepositoryImpl(private val context: Context) : YtDlpRepository {
    suspend fun updateExtractor(): String = withContext(Dispatchers.IO) {
        YoutubeDL.getInstance().updateYoutubeDL(context, YoutubeDL.UpdateChannel.STABLE).toString()
    }
    override suspend fun analyze(url: String): VideoInfo = withContext(Dispatchers.IO) {
        val request = YoutubeDLRequest(url).apply { addOption("--dump-single-json"); addOption("--no-playlist"); addOption("--skip-download") }
        parse(YoutubeDL.getInstance().execute(request).out)
    }
    override suspend fun download(url: String, height: Int?, outputTemplate: String, progress: (Int) -> Unit): String = withContext(Dispatchers.IO) {
        val request = YoutubeDLRequest(url).apply { addOption("--no-playlist"); addOption("-f", selectorFor(height)); addOption("--merge-output-format", "mp4"); addOption("-o", outputTemplate); addOption("--newline") }
        YoutubeDL.getInstance().execute(request) { value, _, _ -> progress(value.toInt().coerceIn(0, 100)) }.out
    }
    private fun parse(raw: String): VideoInfo {
        val json = JSONObject(raw); val items = json.optJSONArray("formats") ?: JSONArray()
        val formats = (0 until items.length()).map { index -> items.getJSONObject(index).toFormat() }
        return VideoInfo(json.optString("id").ifBlank { null }, json.optString("title", "Untitled video"), json.optString("uploader").ifBlank { null }, json.optString("webpage_url", json.optString("original_url")), json.optString("thumbnail").ifBlank { null }, json.optLong("duration").takeIf { it > 0 }, formats)
    }
    private fun JSONObject.toFormat() = VideoFormat(optString("format_id"), optInt("height").takeIf { it > 0 }, optInt("width").takeIf { it > 0 }, optDouble("fps").takeIf { !it.isNaN() }, optString("ext").ifBlank { null }, optString("vcodec").ifBlank { null }, optString("acodec").ifBlank { null }, optLong("filesize").takeIf { it > 0 }, optLong("filesize_approx").takeIf { it > 0 }, optDouble("tbr").takeIf { !it.isNaN() }, optString("vcodec") !in listOf("", "none"), optString("acodec") !in listOf("", "none"))
}
