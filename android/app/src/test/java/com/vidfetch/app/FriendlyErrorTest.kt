package com.vidfetch.app

import org.junit.Assert.*
import org.junit.Test

class FriendlyErrorTest {
    @Test fun redditAndRedgifsForbiddenErrorsDoNotMentionYoutube() {
        for (detail in listOf("[Reddit] HTTP Error 403: Forbidden", "[RedGifs] HTTP Error 403: Forbidden", "HTTP Error 403: Blocked", "forbidden")) {
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
        assertTrue(message.contains("Account authentication is required"))
        assertFalse(message.contains("outdated"))
        assertFalse(message.contains("YouTube"))
    }
}
