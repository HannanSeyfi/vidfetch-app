package com.vidfetch.app.domain

data class VideoInfo(val id: String?, val title: String, val uploader: String?, val webpageUrl: String, val thumbnailUrl: String?, val durationSeconds: Long?, val formats: List<VideoFormat>)
data class VideoFormat(val formatId: String, val height: Int?, val width: Int?, val fps: Double?, val extension: String?, val videoCodec: String?, val audioCodec: String?, val filesize: Long?, val approximateFilesize: Long?, val bitrate: Double?, val hasVideo: Boolean, val hasAudio: Boolean)
data class VideoQuality(val height: Int?, val label: String, val estimatedBytes: Long?)
enum class DownloadStatus { QUEUED, DOWNLOADING, MERGING, COMPLETED, FAILED, CANCELLED, WAITING_FOR_WIFI }
data class DownloadRecord(val id: String, val sourceUrl: String, val title: String, val thumbnailUrl: String?, val selectedHeight: Int?, val outputUri: String? = null, val filename: String? = null, val status: DownloadStatus = DownloadStatus.QUEUED, val progress: Int? = null, val errorMessage: String? = null, val createdAt: Long = System.currentTimeMillis())
