package com.vidfetch.app.data.cookies

import com.vidfetch.app.domain.domainMatches
import com.vidfetch.app.domain.normalizedHost

/** Validate Netscape exports and discard cookies belonging to unrelated sites. */
fun scopedCookieFile(text: String, site: String, nowSeconds: Long = System.currentTimeMillis() / 1000): String {
    require(text.length <= 2_000_000) { "Cookie file is too large (maximum 2 MB)." }
    require(text.lineSequence().any { it.startsWith("# Netscape HTTP Cookie File") || it.startsWith("# HTTP Cookie File") }) {
        "Choose a cookies.txt file exported in Netscape format."
    }
    val rows = text.lineSequence().map { it.trimEnd('\r') }.filter { it.isNotBlank() && (!it.startsWith('#') || it.startsWith("#HttpOnly_")) }.mapNotNull { line ->
        val fields = line.removePrefix("#HttpOnly_").split('\t')
        require(fields.size == 7 && fields[1] in listOf("TRUE", "FALSE") && fields[3] in listOf("TRUE", "FALSE") &&
            fields[2].startsWith('/') && (fields[4].toLongOrNull() ?: -1) >= 0 && fields[5].isNotBlank() && '\u0000' !in line &&
            fields[0].startsWith('.') == (fields[1] == "TRUE") && fields[0].trimStart('.').matches(Regex("[A-Za-z0-9_-]+(?:\\.[A-Za-z0-9_-]+)*"))) {
            "The cookie file contains an invalid Netscape entry."
        }
        val domain = normalizedHost(fields[0].trimStart('.'))
        val expires = fields[4].toLong()
        line.takeIf { domain != null && domainMatches(domain, site) && (expires == 0L || expires > nowSeconds) }
    }.toList()
    require(rows.isNotEmpty()) { "No unexpired cookies for $site were found. Export a fresh Netscape cookies.txt while signed in to that site." }
    return "# Netscape HTTP Cookie File\n" + rows.joinToString("\n", postfix = "\n")
}

fun cookieFileStatus(text: String, site: String): String = runCatching {
    val rows = scopedCookieFile(text, site).lineSequence().filter { it.isNotBlank() && (!it.startsWith('#') || it.startsWith("#HttpOnly_")) }.toList()
    val names = rows.map { it.removePrefix("#HttpOnly_").split('\t')[5] }
    val accountNames = when (site) {
        "reddit.com" -> setOf("reddit_session")
        "youtube.com" -> setOf("SID", "__Secure-1PSID", "__Secure-3PSID")
        else -> emptySet()
    }
    "${rows.size} unexpired cookies" + if (accountNames.isEmpty()) "" else if (names.any { it in accountNames }) " · sign-in cookie present" else " · no sign-in cookie found"
}.getOrDefault("Cookies expired or invalid. Import a fresh export.")
