package com.vidfetch.app.data.extractor

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class ExtractionCompatibilityTest {
    @Test fun rejectedRedditAndRedgifsRequestsUseCompatibility() = runBlocking {
        for (url in listOf("https://www.reddit.com/r/videos/s/example", "https://redgifs.com/watch/example", "https://v.redd.it/example", "https://thumbs2.redgifs.com/example.mp4")) {
            val attempts = mutableListOf<ExtractorBackend>()
            val result = extractWithCompatibility(url) { backend ->
                attempts += backend
                if (backend == ExtractorBackend.CURRENT) error("HTTP Error 403: Forbidden")
                "downloaded"
            }
            assertEquals("downloaded", result)
            assertEquals(listOf(ExtractorBackend.CURRENT, ExtractorBackend.COMPATIBILITY), attempts)
        }
    }

    @Test fun successfulRequestsAndOtherSitesDoNotRetry() = runBlocking {
        var attempts = 0
        assertEquals("ok", extractWithCompatibility("https://www.reddit.com/comments/example") { attempts++; "ok" })
        assertEquals(1, attempts)
        for (url in listOf("https://youtu.be/example", "https://pornhub.com/video", "https://reddit.com.attacker.example/video", "https://redgifs.com@attacker.example/video")) {
            attempts = 0
            val error = runCatching { extractWithCompatibility(url) { attempts++; error("HTTP Error 403: Forbidden") } }.exceptionOrNull()
            assertNotNull(error)
            assertEquals(1, attempts)
        }
    }

    @Test fun cancellationAndUnrelatedErrorsAreNotRetried() = runBlocking {
        for (error in listOf(CancellationException("cancelled"), IllegalStateException("Requested format is not available"))) {
            var attempts = 0
            val result = runCatching { extractWithCompatibility("https://redgifs.com/watch/example") { attempts++; throw error } }
            assertSame(error, result.exceptionOrNull())
            assertEquals(1, attempts)
        }
    }

    @Test fun anonymousRedditSessionFailureRetriesOnceAndPreservesFinalError() = runBlocking {
        var attempts = 0
        val result = runCatching {
            extractWithCompatibility("https://www.reddit.com/comments/example") { backend ->
                attempts++
                error(if (backend == ExtractorBackend.CURRENT) "Account authentication is required" else "Private subreddit; approved account required")
            }
        }
        assertEquals(2, attempts)
        assertEquals("Private subreddit; approved account required", result.exceptionOrNull()?.message)
    }
}
