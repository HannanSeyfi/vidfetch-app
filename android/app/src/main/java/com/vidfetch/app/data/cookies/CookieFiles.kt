package com.vidfetch.app.data.cookies

import com.vidfetch.app.domain.domainMatches
import com.vidfetch.app.domain.normalizedHost

/** Validate Netscape exports and discard cookies belonging to unrelated sites. */
fun scopedCookieFile(text: String, site: String): String {
    require(text.length <= 2_000_000) { "Cookie file is too large (maximum 2 MB)." }
    require(text.lineSequence().any { it.startsWith("# Netscape HTTP Cookie File") || it.startsWith("# HTTP Cookie File") }) {
        "Choose a cookies.txt file exported in Netscape format."
    }
    val rows = text.lineSequence().map { it.trimEnd('\r') }.filter { it.isNotBlank() && (!it.startsWith('#') || it.startsWith("#HttpOnly_")) }.mapNotNull { line ->
        val fields = line.removePrefix("#HttpOnly_").split('\t')
        require(fields.size == 7 && fields[1] in listOf("TRUE", "FALSE") && fields[3] in listOf("TRUE", "FALSE") &&
            fields[2].startsWith('/') && (fields[4].toLongOrNull() ?: -1) >= 0 && fields[5].isNotBlank() && '\u0000' !in line) {
            "The cookie file contains an invalid Netscape entry."
        }
        val domain = normalizedHost(fields[0].trimStart('.'))
        line.takeIf { domain != null && domainMatches(domain, site) }
    }.toList()
    require(rows.isNotEmpty()) { "No cookies for $site were found in this file." }
    return "# Netscape HTTP Cookie File\n" + rows.joinToString("\n", postfix = "\n")
}
