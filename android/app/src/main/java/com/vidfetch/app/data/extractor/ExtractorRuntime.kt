package com.vidfetch.app.data.extractor

import android.content.Context
import android.system.Os
import com.vidfetch.app.BuildConfig
import com.vidfetch.app.R
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runInterruptible
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.zip.ZipFile
import java.util.zip.ZipInputStream
import kotlin.concurrent.thread

/** APK-installed native executables; private, non-backed-up Python data and shared libraries. */
internal object ExtractorRuntime {
    private val mutex = Mutex()
    private var initialized = false
    private var compatibilityInitialized = false

    suspend fun run(context: Context, arguments: List<String>, progress: ((Int) -> Unit)? = null, backend: ExtractorBackend = ExtractorBackend.CURRENT): String = withContext(Dispatchers.IO) {
        mutex.withLock {
            prepare(context)
            if (backend == ExtractorBackend.COMPATIBILITY) prepareCompatibility(context)
            execute(context, listOf(engineFile(context).absolutePath) + arguments, progress, backend)
        }
    }

    suspend fun versions(context: Context): String = withContext(Dispatchers.IO) {
        mutex.withLock {
            prepare(context)
            val version = execute(context, listOf(binary(context).absolutePath, "--version")).trim()
            val packages = execute(context, listOf("-c", "import platform, curl_cffi; print('Python ' + platform.python_version() + ' · curl_cffi ' + curl_cffi.__version__)")).trim()
            "yt-dlp $version · $packages · QuickJS-ng 0.16.2 · FFmpeg 8.1.2"
        }
    }

    internal suspend fun python(context: Context, arguments: List<String>, backend: ExtractorBackend = ExtractorBackend.CURRENT): String = withContext(Dispatchers.IO) {
        mutex.withLock {
            prepare(context)
            if (backend == ExtractorBackend.COMPATIBILITY) prepareCompatibility(context)
            execute(context, arguments, backend = backend)
        }
    }

    internal suspend fun media(context: Context, tool: String, arguments: List<String>): String = withContext(Dispatchers.IO) {
        mutex.withLock {
            prepare(context)
            executeProcess(mediaProcessBuilder(context, tool, arguments))
        }
    }

    internal fun mediaProcessBuilder(context: Context, tool: String, arguments: List<String>): ProcessBuilder {
        require(tool in setOf("ffmpeg", "ffprobe"))
        val native = context.applicationInfo.nativeLibraryDir
        return ProcessBuilder(listOf("$native/lib$tool.so") + arguments).apply {
            environment().apply {
                put("LD_LIBRARY_PATH", mediaLibraryPath(context))
                listOf("PYTHONHOME", "PYTHONPATH", "PYTHONNOUSERSITE", "PYTHONUNBUFFERED", "OPENSSL_MODULES", "LD_PRELOAD").forEach(::remove)
                put("TMPDIR", context.cacheDir.absolutePath)
            }
        }
    }

    private fun mediaLibraryPath(context: Context) = "${File(root(context), "ffmpeg/usr/lib").absolutePath}:${context.applicationInfo.nativeLibraryDir}"

    suspend fun update(context: Context): String = withContext(Dispatchers.IO) {
        mutex.withLock {
            prepare(context)
            val prefix = "https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/download/"
            val release = JSONObject(fetch("https://api.github.com/repos/yt-dlp/yt-dlp-nightly-builds/releases/latest", 2_000_000).toString(Charsets.UTF_8))
            val version = release.getString("tag_name")
            val installed = archiveVersion(binary(context))
            if (installed != null && compareVersions(installed, version) >= 0) return@withLock "Already up to date ($installed)"
            val assets = release.getJSONArray("assets")
            val items = (0 until assets.length()).map { assets.getJSONObject(it) }
            val asset = items.first { it.getString("name") == "yt-dlp" }
            val url = asset.getString("browser_download_url")
            require(url.startsWith(prefix))
            val expected = asset.optString("digest").removePrefix("sha256:").takeIf { it.matches(Regex("[a-f0-9]{64}")) }
                ?: run {
                    val sumsUrl = items.first { it.getString("name") == "SHA2-256SUMS" }.getString("browser_download_url")
                    require(sumsUrl.startsWith(prefix))
                    fetch(sumsUrl, 100_000).toString(Charsets.UTF_8).lineSequence()
                        .first { it.trim().endsWith(" yt-dlp") }.substringBefore(' ')
                }
            val bytes = fetch(url, 15_000_000)
            require(MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) } == expected) { "Extractor checksum verification failed" }
            val temporary = File(binary(context).parentFile, "yt-dlp.update")
            try {
                temporary.writeBytes(bytes)
                require(archiveVersion(temporary) == version) { "Unexpected extractor version" }
                replace(temporary, binary(context))
            } finally { temporary.delete() }
            "Updated to $version"
        }
    }

    private fun root(context: Context) = File(context.noBackupFilesDir, "extractor-runtime")
    private fun binary(context: Context) = File(root(context), "yt-dlp")
    private fun compatibilityRoot(context: Context) = File(context.noBackupFilesDir, "extractor-compatibility")
    // Both interpreters use this file, including replacements made by Update extractor.
    internal fun engineFile(context: Context) = binary(context)

    private fun prepareCompatibility(context: Context) {
        if (compatibilityInitialized) return
        val root = compatibilityRoot(context).apply { mkdirs() }
        val marker = File(root, "runtime-version")
        val version = "${BuildConfig.COMPATIBILITY_RUNTIME_COMMIT}:zip-links-v1"
        if (!marker.exists() || marker.readText() != version) {
            unpack(File(context.applicationInfo.nativeLibraryDir, "libpython-compat.zip.so"), File(root, "python"))
            File(root, "python/usr/lib/liblzma.so").delete()
            marker.writeText(version)
        }
        // Retire 0.3.3's frozen extractor even if the Python payload is already installed.
        File(root, "yt-dlp").delete()
        compatibilityInitialized = true
    }

    private fun prepare(context: Context) {
        if (initialized) return
        val root = root(context).apply { mkdirs() }
        val marker = File(root, "runtime-version")
        val runtimeVersion = "${BuildConfig.RUNTIME_COMMIT}:zip-links-v1"
        if (!marker.exists() || marker.readText() != runtimeVersion) {
            val native = File(context.applicationInfo.nativeLibraryDir)
            unpack(File(native, "libpython.zip.so"), File(root, "python"))
            unpack(File(native, "libffmpeg.zip.so"), File(root, "ffmpeg"))
            // Do not shadow the platform liblzma used by Android's unwinder.
            File(root, "python/usr/lib/liblzma.so").delete()
            File(root, "ffmpeg/usr/lib/liblzma.so").delete()
            marker.writeText(runtimeVersion)
        }
        val target = binary(context)
        val legacy = File(context.noBackupFilesDir, "youtubedl-android/yt-dlp/yt-dlp")
        if (!target.exists() && archiveVersion(legacy)?.let { compareVersions(it, BuildConfig.BUNDLED_YTDLP_VERSION) >= 0 } == true) legacy.copyTo(target)
        if (archiveVersion(target)?.let { compareVersions(it, BuildConfig.BUNDLED_YTDLP_VERSION) < 0 } != false) {
            val temporary = File(root, "yt-dlp.install")
            context.resources.openRawResource(R.raw.ytdlp).use { input -> temporary.outputStream().use { input.copyTo(it) } }
            replace(temporary, target)
        }
        // Install from this APK on every process initialization so upgrades replace the hook.
        val startup = File(root, "startup").apply { mkdirs() }
        val hook = File(startup, "sitecustomize.install")
        context.resources.openRawResource(R.raw.sitecustomize).use { input -> hook.outputStream().use { input.copyTo(it) } }
        replace(hook, File(startup, "sitecustomize.py"))
        initialized = true
    }

    private fun unpack(archive: File, destination: File) {
        destination.deleteRecursively()
        destination.mkdirs()
        val prefix = destination.canonicalPath + File.separator
        val linkNames = runtimeArchiveLinks(archive)
        val links = mutableListOf<Pair<File, String>>()
        ZipInputStream(archive.inputStream().buffered()).use { zip ->
            while (true) {
                val entry = zip.nextEntry ?: break
                val output = File(destination, entry.name)
                require(output.canonicalPath.startsWith(prefix)) { "Unsafe runtime archive path" }
                if (entry.name in linkNames) {
                    val target = zip.bufferedReader(Charsets.UTF_8).readText()
                    require(target.length <= 4096 && !File(target).isAbsolute && '\u0000' !in target) { "Invalid runtime symbolic link" }
                    require(File(output.parentFile, target).canonicalPath.startsWith(prefix)) { "Unsafe runtime symbolic link" }
                    links += output to target
                } else if (entry.isDirectory) output.mkdirs() else {
                    output.parentFile?.mkdirs()
                    output.outputStream().use { zip.copyTo(it) }
                }
            }
        }
        // Restore links after regular files so shared-library aliases remain valid ELF files.
        for ((output, target) in links) {
            output.parentFile?.mkdirs()
            Os.symlink(target, output.absolutePath)
        }
    }

    private fun replace(temporary: File, target: File) {
        check(temporary.renameTo(target)) { "Could not install extractor" }
    }

    private fun archiveVersion(file: File): String? = runCatching {
        ZipFile(file).use { zip ->
            val entry = zip.getEntry("yt_dlp/version.py") ?: return null
            val content = zip.getInputStream(entry).bufferedReader().use { it.readText() }
            Regex("__version__ = ['\"]([^'\"]+)").find(content)?.groupValues?.get(1)
        }
    }.getOrNull()

    private suspend fun execute(context: Context, arguments: List<String>, progress: ((Int) -> Unit)? = null, backend: ExtractorBackend = ExtractorBackend.CURRENT): String {
        val compatible = backend == ExtractorBackend.COMPATIBILITY
        val runtimeRoot = if (compatible) compatibilityRoot(context) else root(context)
        val native = File(context.applicationInfo.nativeLibraryDir)
        val python = File(runtimeRoot, "python/usr")
        val ffmpeg = File(root(context), "ffmpeg/usr")
        val builder = ProcessBuilder(listOf(File(native, if (compatible) "libpython-compat.so" else "libpython.so").absolutePath) + arguments)
        builder.environment().apply {
            put("PYTHONHOME", python.absolutePath)
            put("PYTHONNOUSERSITE", "1")
            put("PYTHONUNBUFFERED", "1")
            put("PYTHONPATH", File(root(context), "startup").absolutePath)
            put("LD_LIBRARY_PATH", "${python.absolutePath}/lib:${ffmpeg.absolutePath}/lib:${native.absolutePath}")
            put("VIDFETCH_FFMPEG_EXECUTABLE", File(native, "libffmpeg.so").absolutePath)
            put("VIDFETCH_FFPROBE_EXECUTABLE", File(native, "libffprobe.so").absolutePath)
            put("VIDFETCH_MEDIA_LIBRARY_PATH", mediaLibraryPath(context))
            put("SSL_CERT_FILE", if (compatible) "${python.absolutePath}/etc/tls/cert.pem" else "${python.absolutePath}/lib/python3.14/site-packages/certifi/cacert.pem")
            if (compatible) remove("OPENSSL_MODULES") else put("OPENSSL_MODULES", "${python.absolutePath}/lib/ossl-modules")
            put("HOME", runtimeRoot.absolutePath)
            put("TMPDIR", context.cacheDir.absolutePath)
            put("PATH", "${native.absolutePath}:${python.absolutePath}/bin:${get("PATH").orEmpty()}")
        }
        return executeProcess(builder, progress)
    }

    private suspend fun executeProcess(builder: ProcessBuilder, progress: ((Int) -> Unit)? = null): String = runInterruptible {
        val process = builder.start()
        val out = StringBuilder()
        val error = StringBuilder()
        val readers = listOf(
            thread(name = "vidfetch-extractor-output", isDaemon = true) {
                runCatching { process.inputStream.bufferedReader().useLines { lines -> lines.forEach { line ->
                    if (line.startsWith("VIDFETCH_PROGRESS:")) {
                        Regex("([0-9.]+)%").find(line)?.groupValues?.get(1)?.toDoubleOrNull()?.toInt()?.let { progress?.invoke(it.coerceIn(0, 100)) }
                    } else if (out.length < 10_000_000) out.appendLine(line)
                } } }
            },
            thread(name = "vidfetch-extractor-errors", isDaemon = true) {
                runCatching { process.errorStream.bufferedReader().useLines { lines -> lines.forEach { line ->
                    error.appendLine(line)
                    if (error.length > 32000) error.delete(0, error.length - 32000)
                } } }
            },
        )
        try {
            val status = process.waitFor()
            readers.forEach { it.join() }
            if (status != 0) throw IllegalStateException(extractorFailureDetail(error.toString(), status))
            out.toString()
        } finally {
            process.destroy()
            process.inputStream.close()
            process.errorStream.close()
            readers.forEach { it.interrupt() }
        }
    }

    private fun fetch(url: String, limit: Int): ByteArray {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.connectTimeout = 30000
        connection.readTimeout = 60000
        connection.setRequestProperty("User-Agent", "VidFetch/${BuildConfig.VERSION_NAME}")
        try {
            require(connection.responseCode == 200) { "Extractor update failed (HTTP ${connection.responseCode})" }
            return connection.inputStream.use { input ->
                val out = ByteArrayOutputStream()
                val buffer = ByteArray(65536)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    require(out.size() + count <= limit) { "Extractor response too large" }
                    out.write(buffer, 0, count)
                }
                out.toByteArray()
            }
        } finally { connection.disconnect() }
    }
}

internal fun compareVersions(first: String, second: String): Int {
    val a = first.split('.').map { it.toLongOrNull() ?: 0L }
    val b = second.split('.').map { it.toLongOrNull() ?: 0L }
    return (0 until maxOf(a.size, b.size)).map { a.getOrElse(it) { 0L }.compareTo(b.getOrElse(it) { 0L }) }.firstOrNull { it != 0 } ?: 0
}
