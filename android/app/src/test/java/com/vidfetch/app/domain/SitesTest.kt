package com.vidfetch.app.domain

import org.junit.Assert.*
import org.junit.Test

class SitesTest {
    @Test fun redditAliasesUseTheSameCookieConfiguration() {
        for (host in listOf("reddit.com", "www.reddit.com", "old.reddit.com", "redd.it", "v.redd.it", "www.redditmedia.com")) {
            assertEquals("reddit.com", siteForUrl("https://$host/example"))
        }
        assertEquals("reddit.com.attacker.example", siteForUrl("https://reddit.com.attacker.example/example"))
        assertEquals("redd.it.attacker.example", siteForUrl("https://redd.it.attacker.example/example"))
        assertNull(siteForUrl("https://reddit.com@attacker.example/example"))
    }
}
