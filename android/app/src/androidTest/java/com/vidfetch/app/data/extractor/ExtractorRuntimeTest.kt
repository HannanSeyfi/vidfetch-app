package com.vidfetch.app.data.extractor

import android.content.Context
import com.vidfetch.app.BuildConfig
import com.vidfetch.app.data.cookies.SiteCookieStore
import com.vidfetch.app.domain.qualities
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.net.ServerSocket
import kotlin.concurrent.thread

class ExtractorRuntimeTest {
    private val context: Context get() = ExtractorInstrumentationRunner.active.targetContext

    @Test fun pornhubResolutionsRemainSelectableWithoutCodecMetadata() {
        val repository = YtDlpRepositoryImpl(context)
        // Pornhub's direct MP4 formats contain url, format_id and height, without codecs.
        // Use synthetic URLs to exercise Android's JSON parsing without a live site or cookies.
        for (codecMetadata in listOf("", ", \"vcodec\": null", ", \"vcodec\": \"\"")) {
            val info = repository.parseVideoInfo("""
                {
                  "id": "quality-regression", "title": "Quality regression",
                  "webpage_url": "https://www.pornhub.com/view_video.php?viewkey=synthetic",
                  "formats": [
                    {"format_id": "240p", "url": "https://media.example/240.mp4", "height": 240$codecMetadata},
                    {"format_id": "480p", "url": "https://media.example/480.mp4", "height": 480$codecMetadata},
                    {"format_id": "720p", "url": "https://media.example/720.mp4", "height": 720, "filesize": 11$codecMetadata},
                    {"format_id": "720p-duplicate", "height": 720, "filesize_approx": 22$codecMetadata},
                    {"format_id": "1080p", "height": 1080, "vcodec": "h264", "acodec": "aac"},
                    {"format_id": "audio-only", "height": 1440, "vcodec": "none", "acodec": "aac"},
                    {"format_id": "storyboard", "height": 2160, "vcodec": "none", "acodec": "none"},
                    {"format_id": "unknown-resolution"},
                    {"format_id": "zero-resolution", "height": 0, "vcodec": "h264"}
                  ]
                }
            """.trimIndent())
            val options = qualities(info.formats)
            assertEquals(listOf(null, 1080, 720, 480, 240), options.map { it.height })
            assertEquals(22L, options.single { it.height == 720 }.estimatedBytes)
            assertTrue(info.formats.first().hasVideo)
            assertNull(info.formats.first().videoCodec)
        }
    }

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
                    val result = repository.download(url, if (path.endsWith("mpd")) 360 else null, destination.absolutePath) { }
                    if (path.endsWith("mpd")) assertEquals(240, result.height)
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
        val url = ExtractorInstrumentationRunner.active.arguments.getString("liveUrl") ?: return@runBlocking
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
