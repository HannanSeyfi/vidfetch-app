package com.vidfetch.app.data.cookies

import android.content.Context
import com.vidfetch.app.domain.domainMatches
import com.vidfetch.app.domain.siteForUrl
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.InputStream
import java.security.MessageDigest
import java.util.Properties
import java.util.concurrent.atomic.AtomicBoolean

data class CookieSite(val host: String, val enabled: Boolean, val status: String = "")

class SiteCookieStore(context: Context) {
    private val directory = File(context.noBackupFilesDir, "site-cookies").apply { mkdirs() }
    private val snapshots = File(directory, "snapshots").apply { mkdirs() }

    init {
        synchronized(lock) {
            if (cleaned.compareAndSet(false, true)) snapshots.listFiles()?.forEach { it.delete() }
        }
    }

    fun list(): List<CookieSite> = synchronized(lock) {
        directory.listFiles().orEmpty().filter { it.extension == "properties" }.mapNotNull { file ->
            runCatching {
                val settings = Properties().apply { file.inputStream().use(::load) }
                val host = settings.getProperty("host")
                CookieSite(host, settings.getProperty("enabled") == "true", cookieFileStatus(cookieFile(host).readText(), host))
            }.getOrNull()
        }.sortedBy { it.host }
    }

    fun importFile(site: String, input: InputStream): String = synchronized(lock) {
        val host = siteForUrl(site) ?: throw IllegalArgumentException("Enter a valid website domain, such as youtube.com.")
        require('.' in host) { "Enter the full website domain, such as youtube.com." }
        val out = ByteArrayOutputStream()
        val buffer = ByteArray(8192)
        while (true) {
            val count = input.read(buffer)
            if (count < 0) break
            require(out.size() + count <= 2_000_000) { "Cookie file is too large (maximum 2 MB)." }
            out.write(buffer, 0, count)
        }
        val cookies = scopedCookieFile(out.toString("UTF-8"), host)
        writeAtomically(cookieFile(host), cookies)
        saveSettings(host, true)
        host
    }

    fun setEnabled(host: String, enabled: Boolean) = synchronized(lock) { saveSettings(host, enabled) }

    fun delete(host: String) = synchronized(lock) {
        cookieFile(host).delete()
        settingsFile(host).delete()
        Unit
    }

    fun snapshotFor(url: String): File? = synchronized(lock) {
        val host = siteForUrl(url) ?: return null
        val configured = list().filter { domainMatches(host, it.host) }.maxByOrNull { it.host.length } ?: return null
        if (!configured.enabled) return null
        val source = cookieFile(configured.host)
        if (!source.exists()) return null
        // yt-dlp can modify the jar; use a separate private snapshot for each invocation.
        val value = scopedCookieFile(source.readText(), configured.host)
        File.createTempFile("session-", ".txt", snapshots).also { it.writeText(value) }
    }

    private fun name(host: String) = MessageDigest.getInstance("SHA-256").digest(host.toByteArray()).joinToString("") { "%02x".format(it) }
    private fun cookieFile(host: String) = File(directory, "${name(host)}.txt")
    private fun settingsFile(host: String) = File(directory, "${name(host)}.properties")

    private fun saveSettings(host: String, enabled: Boolean) {
        val settings = Properties().apply { setProperty("host", host); setProperty("enabled", enabled.toString()) }
        val temporary = File(directory, "${name(host)}.settings.tmp")
        try {
            temporary.outputStream().use { settings.store(it, null) }
            check(temporary.renameTo(settingsFile(host))) { "Could not save site settings." }
        } finally { temporary.delete() }
    }

    private fun writeAtomically(target: File, value: String) {
        val temporary = File(directory, "${target.name}.tmp")
        try {
            temporary.writeText(value)
            check(temporary.renameTo(target)) { "Could not import cookie file." }
        } finally { temporary.delete() }
    }

    companion object {
        private val lock = Any()
        private val cleaned = AtomicBoolean(false)
    }
}
