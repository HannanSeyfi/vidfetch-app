package com.vidfetch.app.service

import com.vidfetch.app.domain.DownloadStatus
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update

data class DownloadItem(
    val id: String,
    val title: String,
    val quality: String,
    val status: DownloadStatus = DownloadStatus.QUEUED,
    val percent: Int = 0,
    val message: String? = null,
) {
    val active get() = status in setOf(DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING, DownloadStatus.MERGING)
}

data class DownloadProgress(
    val downloads: List<DownloadItem> = emptyList(),
    val message: String? = null,
    val completion: Long = 0,
) {
    val active get() = downloads.any { it.active }
}

/** Process-local transfers; completed media in Downloads remains the durable history. */
open class DownloadTracker {
    private val mutable = MutableStateFlow(DownloadProgress())
    val progress = mutable.asStateFlow()

    fun queued(id: String, title: String, quality: String) = mutable.update { state ->
        if (state.downloads.any { it.id == id }) state else state.copy(
            downloads = state.downloads.filter { it.active } + state.downloads.filterNot { it.active }.takeLast(19) + DownloadItem(id, title, quality),
        )
    }

    private fun change(id: String, transform: (DownloadItem) -> DownloadItem) = mutable.update { state ->
        state.copy(downloads = state.downloads.map { if (it.id == id && it.active) transform(it) else it })
    }

    fun status(id: String, status: DownloadStatus, message: String? = null) = change(id) { it.copy(status = status, message = message) }
    fun advanced(id: String, percent: Int) = change(id) { it.copy(percent = percent.coerceIn(0, 99)) }
    fun cancelled(id: String) = change(id) { it.copy(status = DownloadStatus.CANCELLED, message = "Cancelled") }
    fun failed(id: String, message: String) = change(id) { it.copy(status = DownloadStatus.FAILED, message = message) }
    fun finished(id: String, message: String) = mutable.update { state ->
        if (state.downloads.none { it.id == id && it.active }) state else state.copy(
            downloads = state.downloads.map { if (it.id == id) it.copy(status = DownloadStatus.COMPLETED, percent = 100, message = message) else it },
            message = message,
            completion = state.completion + 1,
        )
    }
}

object DownloadState : DownloadTracker()
