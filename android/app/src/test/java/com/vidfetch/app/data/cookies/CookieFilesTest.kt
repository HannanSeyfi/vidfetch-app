package com.vidfetch.app.data.cookies

import org.junit.Assert.*
import org.junit.Test

class CookieFilesTest {
    private val header = "# Netscape HTTP Cookie File\n"
    @Test fun dropsExpiredCookiesButPreservesSessionAndHttpOnlyCookies() {
        val text = header + ".reddit.com\tTRUE\t/\tTRUE\t100\texpired\tsecret\n" +
            "#HttpOnly_.reddit.com\tTRUE\t/\tTRUE\t0\treddit_session\tsynthetic\n"
        val result = scopedCookieFile(text, "reddit.com", nowSeconds = 101)
        assertFalse(result.contains("expired"))
        assertTrue(result.contains("#HttpOnly_.reddit.com"))
        assertTrue(cookieFileStatus(result, "reddit.com").contains("sign-in cookie present"))
        assertFalse(cookieFileStatus(result, "reddit.com").contains("synthetic"))
    }
    @Test(expected = IllegalArgumentException::class) fun rejectsEntirelyExpiredExports() {
        scopedCookieFile(header + ".reddit.com\tTRUE\t/\tTRUE\t100\treddit_session\tsynthetic\n", "reddit.com", nowSeconds = 101)
    }
    @Test fun importsOnlySelectedSiteAndItsSubdomains() {
        val text = header + ".example.com\tTRUE\t/\tTRUE\t0\ttest\tsynthetic\n" +
            "#HttpOnly_login.example.com\tFALSE\t/\tTRUE\t0\ttest\tsynthetic\n" +
            ".other.example\tTRUE\t/\tTRUE\t0\ttest\tsynthetic\n" +
            ".example.com.attacker.example\tTRUE\t/\tTRUE\t0\ttest\tsynthetic\n"
        val result = scopedCookieFile(text, "example.com")
        assertTrue(result.contains("#HttpOnly_login.example.com"))
        assertFalse(result.contains("other.example"))
        assertFalse(result.contains("attacker.example"))
    }
    @Test(expected = IllegalArgumentException::class) fun rejectsMalformedFile() {
        scopedCookieFile(header + "example.com\tTRUE\t/\tTRUE\tnot-a-number\ttest\tsynthetic\n", "example.com")
    }
    @Test(expected = IllegalArgumentException::class) fun rejectsWrongSite() {
        scopedCookieFile(header + ".other.example\tTRUE\t/\tTRUE\t0\ttest\tsynthetic\n", "example.com")
    }
    @Test(expected = IllegalArgumentException::class) fun rejectsNonNetscapeExport() {
        scopedCookieFile("[{\"domain\":\"example.com\"}]", "example.com")
    }
}
