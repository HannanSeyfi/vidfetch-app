package com.vidfetch.app.domain

import java.net.IDN
import java.net.URI
import java.util.Locale

fun normalizedHost(value: String): String? = runCatching {
    val uri = URI(if ("://" in value) value.trim() else "https://${value.trim()}")
    require(uri.scheme.lowercase(Locale.ROOT) in listOf("http", "https") && uri.userInfo == null)
    IDN.toASCII(uri.host ?: return null).lowercase(Locale.ROOT).trimEnd('.').removePrefix("www.")
        .takeIf { it.isNotBlank() }
}.getOrNull()

fun domainMatches(host: String, domain: String): Boolean = host == domain || host.endsWith(".$domain")

fun siteForUrl(value: String): String? {
    val host = normalizedHost(value) ?: return null
    return when {
        host == "youtu.be" || domainMatches(host, "youtube.com") || domainMatches(host, "youtube-nocookie.com") -> "youtube.com"
        domainMatches(host, "pornhub.com") -> "pornhub.com"
        else -> host
    }
}
