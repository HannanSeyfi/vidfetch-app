package com.vidfetch.app

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.vidfetch.app.data.extractor.YtDlpRepositoryImpl
import com.vidfetch.app.data.extractor.extractorFailureDetail
import com.vidfetch.app.data.cookies.CookieSite
import com.vidfetch.app.data.cookies.SiteCookieStore
import com.vidfetch.app.data.storage.DownloadedMedia
import com.vidfetch.app.data.storage.DownloadedMediaRepository
import com.vidfetch.app.domain.VideoInfo
import com.vidfetch.app.domain.VideoQuality
import com.vidfetch.app.domain.qualities
import com.vidfetch.app.service.DownloadState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class VidFetchUiState(
    val url: String = "",
    val info: VideoInfo? = null,
    val selected: VideoQuality? = null,
    val analyzing: Boolean = false,
    val updating: Boolean = false,
    val message: String? = null,
    val downloads: List<DownloadedMedia> = emptyList(),
    val downloadsLoading: Boolean = false,
    val downloadsMessage: String? = null,
    val downloadsFolderConnected: Boolean = false,
    val cookieSites: List<CookieSite> = emptyList(),
    val importingCookies: Boolean = false,
    val cookieMessage: String? = null,
    val runtimeVersions: String = "yt-dlp ${BuildConfig.BUNDLED_YTDLP_VERSION}",
)

class VidFetchViewModel(application: Application) : AndroidViewModel(application) {
    private val extractor = YtDlpRepositoryImpl(application)
    private val media = DownloadedMediaRepository(application)
    private val cookies = SiteCookieStore(application)
    private val mutable = MutableStateFlow(VidFetchUiState())
    val state = mutable.asStateFlow()
    private var refreshGeneration = 0
    private var lastSharedUrl: String? = null

    init {
        refreshDownloads()
        refreshCookieSites()
        viewModelScope.launch {
            try { mutable.update { it.copy(runtimeVersions = extractor.runtimeVersions()) } }
            catch (error: CancellationException) { throw error }
            catch (error: Exception) { mutable.update { it.copy(message = "Could not initialize download engine: ${error.message}") } }
        }
        viewModelScope.launch {
            var lastCompletion = DownloadState.progress.value.completion
            DownloadState.progress.collect { progress ->
                if (progress.completion != lastCompletion) {
                    lastCompletion = progress.completion
                    refreshDownloads()
                }
            }
        }
    }

    fun setUrl(url: String) {
        mutable.update { it.copy(url = url, info = null, selected = null, message = null) }
    }

    fun acceptSharedUrl(url: String) {
        if (url.isNotBlank() && url != lastSharedUrl) {
            lastSharedUrl = url
            setUrl(url)
        }
    }

    fun setSelected(quality: VideoQuality) { mutable.update { it.copy(selected = quality) } }

    fun analyze() {
        val url = state.value.url.trim()
        if (!url.startsWith("https://") && !url.startsWith("http://")) {
            mutable.update { it.copy(message = "Enter a valid http or https URL.") }
            return
        }
        if (state.value.analyzing || state.value.updating || state.value.importingCookies || DownloadState.progress.value.active) return
        viewModelScope.launch {
            mutable.update { it.copy(analyzing = true, info = null, selected = null, message = null) }
            try {
                val info = extractor.analyze(url)
                if (state.value.url.trim() == url) {
                    mutable.update { it.copy(info = info, selected = qualities(info.formats).firstOrNull()) }
                }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                mutable.update { it.copy(message = friendlyError(error)) }
            } finally {
                mutable.update { it.copy(analyzing = false) }
            }
        }
    }

    fun refreshDownloads() {
        val generation = ++refreshGeneration
        viewModelScope.launch {
            mutable.update { it.copy(downloadsLoading = true, downloadsMessage = null) }
            try {
                val (items, connected) = withContext(Dispatchers.IO) { media.list() to media.hasFolderAccess() }
                if (generation == refreshGeneration) mutable.update { it.copy(downloads = items, downloadsFolderConnected = connected) }
            } catch (error: Exception) {
                if (generation == refreshGeneration) mutable.update { it.copy(downloadsMessage = error.message ?: "Could not load downloads.") }
            } finally {
                if (generation == refreshGeneration) mutable.update { it.copy(downloadsLoading = false) }
            }
        }
    }

    fun connectDownloadsFolder(uri: Uri) {
        viewModelScope.launch {
            try {
                withContext(Dispatchers.IO) { media.connectFolder(uri) }
                refreshDownloads()
            } catch (error: Exception) {
                mutable.update { it.copy(downloadsMessage = error.message ?: "Could not access Downloads/VidFetch.") }
            }
        }
    }

    fun open(item: DownloadedMedia) = action { media.open(item) }
    fun share(item: DownloadedMedia) = action { media.share(item) }

    private fun action(block: () -> Unit) {
        try { block() } catch (error: Exception) {
            mutable.update { it.copy(downloadsMessage = error.message ?: "No app can handle this file.") }
        }
    }

    fun delete(item: DownloadedMedia) = changeFile("Could not delete the file.") { media.delete(item) }
    fun rename(item: DownloadedMedia, name: String) = changeFile("Could not rename the file. Check the name and try again.") { media.rename(item, name) }

    private fun changeFile(failure: String, operation: () -> Boolean) {
        viewModelScope.launch {
            try {
                val changed = withContext(Dispatchers.IO) { operation() }
                if (changed) refreshDownloads() else mutable.update { it.copy(downloadsMessage = failure) }
            } catch (error: Exception) {
                mutable.update { it.copy(downloadsMessage = error.message ?: failure) }
            }
        }
    }

    fun updateExtractor() {
        if (state.value.updating || state.value.analyzing || DownloadState.progress.value.active) return
        viewModelScope.launch {
            mutable.update { it.copy(updating = true, message = null) }
            try {
                val result = extractor.updateExtractor()
                val versions = extractor.runtimeVersions()
                mutable.update { it.copy(message = "Extractor update: $result", runtimeVersions = versions) }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                mutable.update { it.copy(message = "Could not update the extractor: ${error.message ?: "unknown error"}") }
            } finally {
                mutable.update { it.copy(updating = false) }
            }
        }
    }

    private fun refreshCookieSites() { mutable.update { it.copy(cookieSites = cookies.list()) } }

    fun importCookies(site: String, uri: Uri) {
        if (state.value.importingCookies) return
        viewModelScope.launch {
            mutable.update { it.copy(importingCookies = true, cookieMessage = null) }
            try {
                val host = withContext(Dispatchers.IO) {
                    val input = getApplication<Application>().contentResolver.openInputStream(uri)
                        ?: throw IllegalArgumentException("Could not open that cookie file.")
                    input.use { cookies.importFile(site, it) }
                }
                refreshCookieSites()
                mutable.update { it.copy(cookieMessage = "Cookies enabled for $host.", info = null, selected = null) }
            } catch (error: CancellationException) { throw error }
            catch (error: Exception) { mutable.update { it.copy(cookieMessage = error.message ?: "Could not import cookies.") } }
            finally { mutable.update { it.copy(importingCookies = false) } }
        }
    }

    fun setCookiesEnabled(host: String, enabled: Boolean) {
        cookies.setEnabled(host, enabled)
        refreshCookieSites()
        mutable.update { it.copy(info = null, selected = null) }
    }

    fun deleteCookies(host: String) {
        cookies.delete(host)
        refreshCookieSites()
        mutable.update { it.copy(cookieMessage = "Cookies deleted for $host.", info = null, selected = null) }
    }
}

internal fun friendlyError(error: Exception): String {
    val detail = extractorFailureDetail(error.message.orEmpty())
    return when {
        "429" in detail || "too many requests" in detail.lowercase() -> "This website is rate limiting requests (HTTP 429). Wait before trying again."
        "private subreddit" in detail.lowercase() || "quarantined" in detail.lowercase() -> "Reddit requires an account with access to this community. Import fresh reddit.com cookies from an account that can open the post."
        "reddit api" in detail.lowercase() || ("[reddit]" in detail.lowercase() && listOf("403", "authentication", "forbidden").any { it in detail.lowercase() }) -> "Reddit rejected this session or connection. Import fresh reddit.com cookies exported from Chrome while signed in, then analyze the full post link again. If it still fails, try another network; cookies cannot guarantee access."
        "sign in to confirm" in detail.lowercase() || "not a bot" in detail.lowercase() -> "YouTube requires verification. Import or replace youtube.com cookies in Settings, then analyze again. YouTube may also reject the current network."
        "403" in detail || "forbidden" in detail.lowercase() -> "This website rejected the request (HTTP 403). Update the extractor and refresh this site's cookies. If it continues, try another network."
        else -> "Could not complete this request: ${detail.ifBlank { "extractor error" }}"
    }
}
