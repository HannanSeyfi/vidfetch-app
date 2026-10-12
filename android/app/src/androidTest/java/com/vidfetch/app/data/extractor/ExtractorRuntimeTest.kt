package com.vidfetch.app.data.extractor

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.vidfetch.app.BuildConfig
import com.vidfetch.app.data.cookies.SiteCookieStore
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.net.ServerSocket
import kotlin.concurrent.thread

@RunWith(AndroidJUnit4::class)
class ExtractorRuntimeTest {
    private val context: Context get() = InstrumentationRegistry.getInstrumentation().targetContext

    @Test fun packagedInterpreterNetworkingJavascriptAndFfmpegRun() = runBlocking {
        assertTrue(ExtractorRuntime.versions(context).contains(BuildConfig.BUNDLED_YTDLP_VERSION))
        val native = context.applicationInfo.nativeLibraryDir
        val output = ExtractorRuntime.python(context, listOf("-c", """
            import curl_cffi, ssl, subprocess
            print('curl_cffi=' + curl_cffi.__version__)
            print(subprocess.check_output(['$native/libqjs-cli.so', '-e', 'console.log(21 * 2)'], text=True))
            print(subprocess.check_output(['$native/libffmpeg.so', '-version'], text=True))
            print(subprocess.check_output(['$native/libffprobe.so', '-version'], text=True))
        """.trimIndent()))
        assertTrue(output.contains("curl_cffi=0.16."))
        assertTrue(output.contains("42"))
        assertTrue(output.contains("ffmpeg version"))
        assertTrue(output.contains("ffprobe version"))
        val targets = ExtractorRuntime.run(context, listOf("--list-impersonate-targets"))
        assertTrue(targets.lowercase().contains("chrome"))
    }

    @Test fun directMp4HlsAndDashDownloadWithoutCookies() = runBlocking {
        val folder = File(context.cacheDir, "extractor-test-media").apply { mkdirs() }
        val native = context.applicationInfo.nativeLibraryDir
        try {
            ExtractorRuntime.python(context, listOf("-c", """
                import subprocess
                subprocess.check_call(['$native/libffmpeg.so', '-y', '-f', 'lavfi', '-i', 'color=c=blue:s=320x240:d=1', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-c:v', 'libx264', '-c:a', 'aac', '-shortest', '${folder.absolutePath}/source.mp4'])
                subprocess.check_call(['$native/libffmpeg.so', '-y', '-i', '${folder.absolutePath}/source.mp4', '-c', 'copy', '-hls_time', '1', '-hls_list_size', '0', '${folder.absolutePath}/source.m3u8'])
                subprocess.check_call(['$native/libffmpeg.so', '-y', '-i', '${folder.absolutePath}/source.mp4', '-c', 'copy', '-f', 'dash', '${folder.absolutePath}/source.mpd'])
            """.trimIndent()))
            FixtureServer(folder).use { server ->
                val repository = YtDlpRepositoryImpl(context)
                for (path in listOf("source.mp4", "source.m3u8", "source.mpd")) {
                    val url = "http://127.0.0.1:${server.port}/$path"
                    assertNull(SiteCookieStore(context).snapshotFor(url))
                    val info = repository.analyze(url)
                    assertTrue(info.title.isNotBlank())
                    val destination = File(folder, "download-${path.substringAfterLast('.')}.mp4")
                    repository.download(url, if (path.endsWith("mpd")) 360 else null, destination.absolutePath) { }
                    assertTrue(destination.exists() && destination.length() > 1000)
                    val probe = ExtractorRuntime.python(context, listOf("-c", """
                        import subprocess
                        print(subprocess.check_output(['$native/libffprobe.so', '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', '${destination.absolutePath}'], text=True))
                    """.trimIndent()))
                    assertTrue(probe.contains("video"))
                    assertTrue(probe.contains("audio"))
                }
            }
        } finally { folder.deleteRecursively() }
    }

    @Test fun cookiesArePrivateScopedOptionalAndReplaceable() {
        val store = SiteCookieStore(context)
        val host = "cookies-test.example"
        val text = "# Netscape HTTP Cookie File\n.$host\tTRUE\t/\tTRUE\t0\ttest\tsynthetic\n"
        try {
            store.importFile(host, text.byteInputStream())
            val snapshot = store.snapshotFor("https://$host/video")!!
            assertTrue(snapshot.canonicalPath.startsWith(context.noBackupFilesDir.canonicalPath))
            snapshot.delete()
            assertNull(store.snapshotFor("https://$host.attacker.example/video"))
            store.setEnabled(host, false)
            assertNull(store.snapshotFor("https://$host/video"))
            store.importFile(host, text.replace("synthetic", "replacement").byteInputStream())
            val replacement = store.snapshotFor("https://$host/video")!!
            assertTrue(replacement.readText().contains("replacement"))
            replacement.delete()
        } finally { store.delete(host) }
        assertNull(store.snapshotFor("https://$host/video"))
    }

    @Test fun userProvidedYoutubeLink() = runBlocking {
        val url = InstrumentationRegistry.getArguments().getString("liveUrl") ?: return@runBlocking
        val repository = YtDlpRepositoryImpl(context)
        val info = repository.analyze(url)
        assertEquals("G83NKJCd4VY", info.id)
        assertTrue(info.formats.any { it.hasVideo })
        val destination = File(context.cacheDir, "live-smoke.%(ext)s")
        try {
            repository.download(url, 360, destination.absolutePath) { }
            assertTrue(context.cacheDir.listFiles().orEmpty().any { it.name.startsWith("live-smoke.") && it.length() > 1000 && it.extension != "part" })
        }
        finally { context.cacheDir.listFiles()?.filter { it.name.startsWith("live-smoke.") }?.forEach { it.delete() } }
    }
}

private class FixtureServer(private val folder: File) : AutoCloseable {
    private val server = ServerSocket(0)
    val port: Int get() = server.localPort
    private val worker = thread(isDaemon = true) {
        while (!server.isClosed) {
            runCatching {
                server.accept().use { socket ->
                    val reader = socket.getInputStream().bufferedReader()
                    val request = reader.readLine().split(' ')
                    while (!reader.readLine().isNullOrEmpty()) { }
                    val file = File(folder, request[1].substringBefore('?').removePrefix("/"))
                    val valid = file.canonicalPath.startsWith(folder.canonicalPath + File.separator) && file.isFile
                    val bytes = if (valid) file.readBytes() else byteArrayOf()
                    val type = when (file.extension) { "m3u8" -> "application/vnd.apple.mpegurl"; "mpd" -> "application/dash+xml"; "ts" -> "video/mp2t"; else -> "video/mp4" }
                    val header = "HTTP/1.1 ${if (valid) "200 OK" else "404 Not Found"}\r\nContent-Type: $type\r\nContent-Length: ${bytes.size}\r\nConnection: close\r\n\r\n"
                    socket.getOutputStream().write(header.toByteArray())
                    if (request[0] != "HEAD") socket.getOutputStream().write(bytes)
                }
            }
        }
    }
    override fun close() { server.close(); worker.join(2000) }
}
