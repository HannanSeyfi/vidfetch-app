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
    try {
        return execute(ExtractorBackend.CURRENT)
    } catch (error: CancellationException) {
        throw error
    } catch (error: Exception) {
        val detail = error.message.orEmpty().lowercase()
        val rejected = "http error 403" in detail || "http 403" in detail || "forbidden" in detail || "account authentication is required" in detail
        if (!supportsCompatibility(url) || !rejected) throw error
        // Restore the packaged 0.2.2 Python/networking and extractor path for these sites.
        return execute(ExtractorBackend.COMPATIBILITY)
    }
}
