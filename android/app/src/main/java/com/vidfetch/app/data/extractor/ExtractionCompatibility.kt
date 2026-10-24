package com.vidfetch.app.data.extractor

import com.vidfetch.app.domain.domainMatches
import com.vidfetch.app.domain.normalizedHost
import com.vidfetch.app.domain.siteForUrl
import kotlinx.coroutines.CancellationException

internal enum class ExtractorBackend { CURRENT, COMPATIBILITY }

internal data class ExtractionAttempt(val backend: ExtractorBackend, val chrome: Boolean = false)

internal fun extractionAttempts(url: String): List<ExtractionAttempt> = when {
    siteForUrl(url) == "reddit.com" -> listOf(
        ExtractionAttempt(ExtractorBackend.CURRENT, chrome = true),
        ExtractionAttempt(ExtractorBackend.COMPATIBILITY, chrome = true),
        ExtractionAttempt(ExtractorBackend.CURRENT),
    )
    supportsCompatibility(url) -> listOf(ExtractionAttempt(ExtractorBackend.COMPATIBILITY), ExtractionAttempt(ExtractorBackend.CURRENT))
    else -> listOf(ExtractionAttempt(ExtractorBackend.CURRENT))
}

internal fun retryableSiteRejection(detail: String): Boolean {
    val value = detail.lowercase()
    if (listOf("429", "private subreddit", "quarantined", "not available", "removed", "deleted").any { it in value }) return false
    return listOf("http error 403", "http 403", "forbidden", "account authentication is required",
        "unable to access the reddit api", "impersonate target", "impersonation target").any { it in value }
}

internal fun supportsCompatibility(url: String): Boolean {
    val host = normalizedHost(url) ?: return false
    return listOf("reddit.com", "redditmedia.com", "redd.it", "redgifs.com").any { domainMatches(host, it) }
}

internal suspend fun <T> extractWithCompatibility(url: String, execute: suspend (ExtractionAttempt) -> T): T {
    val attempts = extractionAttempts(url)
    for ((index, attempt) in attempts.withIndex()) {
        try {
            return execute(attempt)
        } catch (error: CancellationException) {
            throw error
        } catch (error: Exception) {
            if (index == attempts.lastIndex || !retryableSiteRejection(error.message.orEmpty())) throw error
        }
    }
    error("No extraction attempt available")
}
