package com.vidfetch.app.domain

import java.util.Locale

fun formatDuration(seconds: Long?): String = seconds?.let { s -> if (s >= 3600) "%d:%02d:%02d".format(s / 3600, (s % 3600) / 60, s % 60) else "%d:%02d".format(s / 60, s % 60) } ?: "Duration unknown"
fun formatBytes(bytes: Long?): String = bytes?.takeIf { it > 0 }?.let { b -> if (b < 1024 * 1024) "${b / 1024} KB" else String.format(Locale.US, "%.1f MB", b / 1024.0 / 1024.0) } ?: "Size unknown"
fun qualityLabel(height: Int?) = when (height) { null -> "Best available"; 720 -> "720p · HD"; 1080 -> "1080p · Full HD"; 1440 -> "1440p · QHD"; 2160 -> "2160p · 4K"; 4320 -> "4320p · 8K"; else -> "${height}p" }
fun qualities(formats: List<VideoFormat>): List<VideoQuality> = listOf(VideoQuality(null, "Best available", null)) + formats.filter { it.hasVideo && (it.height ?: 0) > 0 }.groupBy { it.height!! }.map { (height, same) -> VideoQuality(height, qualityLabel(height), same.mapNotNull { it.filesize ?: it.approximateFilesize }.maxOrNull()) }.sortedByDescending { it.height }
fun selectorFor(height: Int?): String = if (height == null) "bestvideo*+bestaudio/best" else "bestvideo[height=$height][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height=$height]+bestaudio/best[height=$height]/bestvideo[height<=$height]+bestaudio/best[height<=$height]"
fun safeFilename(title: String, extension: String = "mp4"): String = title.replace(Regex("[\\\\/:*?\"<>|]"), "_").trim().take(140).ifBlank { "VidFetch video" } + "." + extension
