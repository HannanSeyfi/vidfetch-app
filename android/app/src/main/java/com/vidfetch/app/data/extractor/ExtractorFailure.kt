package com.vidfetch.app.data.extractor

/** Startup warnings must not replace the terminal error reported by yt-dlp. */
internal fun extractorFailureDetail(stderr: String, exitCode: Int? = null): String {
    val lines = stderr.replace(Regex("\u001B\\[[0-9;]*m"), "").lines()
    val lastError = lines.indexOfLast { it.trimStart().startsWith("ERROR:") }
    val detail = if (lastError >= 0) {
        lines.drop(lastError).takeWhile { !it.trimStart().startsWith("WARNING:") }.joinToString("\n").trim()
    } else stderr.trim()
    return detail.ifBlank { if (exitCode == null) "extractor error" else "Extraction failed (exit $exitCode)" }
}
