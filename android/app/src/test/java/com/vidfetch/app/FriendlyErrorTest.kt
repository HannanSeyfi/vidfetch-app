package com.vidfetch.app

import org.junit.Assert.*
import org.junit.Test

class FriendlyErrorTest {
    @Test fun redditAndRedgifsForbiddenErrorsDoNotMentionYoutube() {
        for (detail in listOf("[RedGifs] HTTP Error 403: Forbidden", "HTTP Error 403: Blocked", "forbidden")) {
            val message = friendlyError(IllegalStateException(detail))
            assertTrue(message.contains("HTTP 403"))
            assertFalse(message.contains("YouTube"))
        }
    }

    @Test fun otherErrorsKeepTheirUsefulDetails() {
        assertTrue(friendlyError(IllegalStateException("Requested format is not available")).contains("Requested format is not available"))
        assertTrue(friendlyError(IllegalStateException("[youtube] Sign in to confirm you're not a bot")).contains("verification"))
    }

    @Test fun startupAgeWarningDoesNotHideTheTerminalRedditError() {
        val message = friendlyError(IllegalStateException("""
            WARNING: Your yt-dlp version (2025.11.12) is older than 90 days!
                     It is strongly recommended to always use the latest version.
            ERROR: [Reddit] Account authentication is required
        """.trimIndent()))
        assertTrue(message.contains("Chrome"))
        assertFalse(message.contains("outdated"))
        assertFalse(message.contains("YouTube"))
    }
    @Test fun redditSessionAndRateLimitErrorsGiveDifferentNextSteps() {
        assertTrue(friendlyError(IllegalStateException("[Reddit] Your IP address is unable to access the Reddit API")).contains("reddit.com"))
        assertTrue(friendlyError(IllegalStateException("[Reddit] HTTP Error 403")).contains("Chrome"))
        assertTrue(friendlyError(IllegalStateException("HTTP Error 429")).contains("Wait"))
    }
}
