package com.vidfetch.app.data.extractor

import com.vidfetch.app.domain.domainMatches
import com.vidfetch.app.domain.normalizedHost
import kotlinx.coroutines.CancellationException

internal enum class ExtractorBackend { CURRENT, COMPATIBILITY }

internal fun supportsCompatibility(url: String): Boolean {
    val host = normalizedHost(url) ?: return false
    return listOf("reddit.com", "redditmedia.com", "redd.it", "redgifs.com").any { domainMatches(host, it) }
}

internal suspend fun <T> extractWithCompatibility(url: String, execute: suspend (ExtractorBackend) -> T): T {
    val compatibleSite = supportsCompatibility(url)
    // 0.2.2 after Update extractor: current yt-dlp, older Python/networking runtime.
    val first = if (compatibleSite) ExtractorBackend.COMPATIBILITY else ExtractorBackend.CURRENT
    try {
        return execute(first)
    } catch (error: CancellationException) {
        throw error
    } catch (error: Exception) {
        val detail = error.message.orEmpty().lowercase()
        val rejected = "http error 403" in detail || "http 403" in detail || "forbidden" in detail || "account authentication is required" in detail
        if (!compatibleSite || !rejected) throw error
        return execute(ExtractorBackend.CURRENT)
    }
}
