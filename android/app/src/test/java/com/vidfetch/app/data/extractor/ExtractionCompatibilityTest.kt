package com.vidfetch.app.data.extractor

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class ExtractionCompatibilityTest {
    @Test fun redditTriesChromeOnBothRuntimesThenDefaultAndPreservesLastFailure() = runBlocking {
        for (url in listOf("https://www.reddit.com/comments/example", "https://redd.it/example", "https://v.redd.it/example")) {
            val attempts = mutableListOf<ExtractionAttempt>()
            val result = runCatching { extractWithCompatibility(url) {
                attempts += it
                error(if (it.chrome) "Your IP address is unable to access the Reddit API" else "HTTP Error 403: final failure")
            } }
            assertEquals(listOf(ExtractionAttempt(ExtractorBackend.CURRENT, true), ExtractionAttempt(ExtractorBackend.COMPATIBILITY, true), ExtractionAttempt(ExtractorBackend.CURRENT)), attempts)
            assertEquals("HTTP Error 403: final failure", result.exceptionOrNull()?.message)
        }
    }
    @Test fun redgifsKeepsCompatibilityFirst() = runBlocking {
        val attempts = mutableListOf<ExtractionAttempt>()
        val result = extractWithCompatibility("https://redgifs.com/watch/example") {
            attempts += it
            if (it.backend == ExtractorBackend.COMPATIBILITY) error("HTTP Error 403: Forbidden")
            "ok"
        }
        assertEquals("ok", result)
        assertEquals(listOf(ExtractionAttempt(ExtractorBackend.COMPATIBILITY), ExtractionAttempt(ExtractorBackend.CURRENT)), attempts)
    }
    @Test fun successAndOtherSitesDoNotRetryOrImpersonate() = runBlocking {
        var attempts = 0
        assertEquals("ok", extractWithCompatibility("https://reddit.com/comments/example") { attempts++; "ok" })
        assertEquals(1, attempts)
        for (url in listOf("https://youtu.be/example", "https://pornhub.com/video", "https://reddit.com.attacker.example/video", "https://redgifs.com@attacker.example/video")) {
            attempts = 0
            runCatching { extractWithCompatibility(url) { assertEquals(ExtractionAttempt(ExtractorBackend.CURRENT), it); attempts++; error("HTTP Error 403: Forbidden") } }
            assertEquals(1, attempts)
        }
    }
    @Test fun cancellationRateLimitsPrivatePostsAndUnrelatedFailuresStopImmediately() = runBlocking {
        for (failure in listOf(CancellationException("cancelled"), IllegalStateException("Requested format is not available"), IllegalStateException("HTTP 429"), IllegalStateException("Private subreddit; HTTP 403"))) {
            var attempts = 0
            val result = runCatching { extractWithCompatibility("https://reddit.com/comments/example") { attempts++; throw failure } }
            assertSame(failure, result.exceptionOrNull())
            assertEquals(1, attempts)
        }
    }
}
