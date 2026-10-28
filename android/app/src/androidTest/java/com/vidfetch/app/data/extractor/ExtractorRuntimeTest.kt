package com.vidfetch.app.data.extractor

import android.content.Context
import com.vidfetch.app.BuildConfig
import com.vidfetch.app.data.cookies.SiteCookieStore
import com.vidfetch.app.domain.qualities
import com.vidfetch.app.friendlyError
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.ServerSocket
import kotlin.concurrent.thread

class ExtractorRuntimeTest {
    private val context: Context get() = ExtractorInstrumentationRunner.active.targetContext

    @Test fun youtubeSeparateStreamsPublishOnlyCompletedVideo() { checkYoutubeSeparateStreams() }
    @Test fun downloadsReflectCopiedMovedRestoredAndDeletedFiles() { checkDownloadsFolderContents() }
    @Test fun sharedLinkAudioSelectionDownloadsThroughService() { checkSharedLinkAudioDownload() }
    @Test fun parallelRequestsAndCancellationAreIsolated() { checkParallelProcessesAndCancellation() }

    @Test fun mediaProcessesDoNotInheritPythonLibraries() = runBlocking {
        for (backend in ExtractorBackend.entries) {
            val output = ExtractorRuntime.python(context, listOf("-c", """
                import inspect, os, ssl, subprocess, sys
                parent = dict(os.environ)
                assert getattr(subprocess.Popen, 'vidfetch_media_isolated', False), 'Python startup isolation hook did not run'
                expected = parent['VIDFETCH_MEDIA_LIBRARY_PATH']
                assert parent['PYTHONHOME'] + '/lib' not in expected.split(':')
                forbidden = ('PYTHONHOME', 'PYTHONPATH', 'PYTHONNOUSERSITE', 'PYTHONUNBUFFERED', 'OPENSSL_MODULES', 'LD_PRELOAD')
                # Dependency imports may legitimately launch helpers with their own minimal environment.
                sys.path.insert(0, sys.argv[1])
                from yt_dlp.utils import Popen
                original = subprocess.Popen._execute_child
                captured = []
                def checked(self, *args, **kwargs):
                    bound = inspect.signature(original).bind(self, *args, **kwargs).arguments
                    command = bound['args'][0]
                    environment = bound['env']
                    if command in (parent['VIDFETCH_FFMPEG_EXECUTABLE'], parent['VIDFETCH_FFPROBE_EXECUTABLE']):
                        assert environment['LD_LIBRARY_PATH'] == expected, environment['LD_LIBRARY_PATH']
                        assert not any(key in environment for key in forbidden)
                        captured.append(command)
                    else:
                        assert environment is None or environment['LD_LIBRARY_PATH'] == parent['LD_LIBRARY_PATH']
                    return original(self, *args, **kwargs)
                subprocess.Popen._execute_child = checked
                for executable in (parent['VIDFETCH_FFMPEG_EXECUTABLE'], parent['VIDFETCH_FFPROBE_EXECUTABLE']):
                    assert subprocess.run([executable, '-version'], capture_output=True, check=True).stdout
                    with Popen([executable, '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(parent)) as process:
                        stdout, stderr = process.communicate()
                        assert process.returncode == 0, stderr
                        assert stdout
                subprocess.run(['/system/bin/sh', '-c', 'exit 0'], check=True)
                subprocess.run(['/system/bin/sh', '-c', 'exit 0'], env=dict(parent), check=True)
                assert len(captured) == 4
                assert dict(os.environ) == parent, 'Media launches changed the extraction environment'
                print('VIDFETCH_MEDIA_ISOLATION_OK ' + ssl.OPENSSL_VERSION)
            """.trimIndent(), ExtractorRuntime.engineFile(context).absolutePath), backend)
            assertTrue(output.contains("VIDFETCH_MEDIA_ISOLATION_OK"))
        }
        for (tool in listOf("ffmpeg", "ffprobe")) {
            val environment = ExtractorRuntime.mediaProcessBuilder(context, tool, listOf("-version")).environment()
            assertFalse(environment.getValue("LD_LIBRARY_PATH").contains("python/usr/lib"))
            assertFalse(environment.containsKey("PYTHONHOME"))
            assertFalse(environment.containsKey("OPENSSL_MODULES"))
            assertTrue(ExtractorRuntime.media(context, tool, listOf("-version")).contains("$tool version"))
        }
    }

    @Test fun compatibilityRuntimeRestoresRedditAndRedgifsExtractionAndDownloads() = runBlocking {
        val backend = ExtractorBackend.COMPATIBILITY
        assertEquals(BuildConfig.BUNDLED_YTDLP_VERSION, ExtractorRuntime.run(context, listOf("--version"), backend = backend).trim())
        assertEquals(ExtractorRuntime.run(context, listOf("--version")).trim(), ExtractorRuntime.run(context, listOf("--version"), backend = backend).trim())
        val version = ExtractorRuntime.python(context, listOf("-c", "import sys, ssl; print(sys.version); print(ssl.OPENSSL_VERSION)"), backend)
        assertTrue(version.contains("3.12."))
        val folder = File(context.cacheDir, "compatibility-test-media").apply { mkdirs() }
        val native = context.applicationInfo.nativeLibraryDir
        try {
            ExtractorRuntime.python(context, listOf("-c", """
                import subprocess
                subprocess.check_call(['$native/libffmpeg.so', '-y', '-f', 'lavfi', '-i', 'color=c=blue:s=320x240:d=1', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-c:v', 'libx264', '-c:a', 'aac', '-shortest', '${folder.absolutePath}/source.mp4'])
                subprocess.check_call(['$native/libffmpeg.so', '-y', '-i', '${folder.absolutePath}/source.mp4', '-c', 'copy', '-hls_time', '1', '-hls_list_size', '0', '${folder.absolutePath}/source.m3u8'])
                subprocess.check_call(['$native/libffmpeg.so', '-y', '-i', '${folder.absolutePath}/source.mp4', '-c', 'copy', '-f', 'dash', '${folder.absolutePath}/source.mpd'])
            """.trimIndent()), backend)
            val script = File(folder, "compatibility_check.py")
            ExtractorInstrumentationRunner.active.context.assets.open("compatibility_check.py").use { input -> script.outputStream().use { input.copyTo(it) } }
            FixtureServer(folder).use { server ->
                val output = ExtractorRuntime.python(context, listOf(script.absolutePath, ExtractorRuntime.engineFile(context).absolutePath,
                    native, "http://127.0.0.1:${server.port}", folder.absolutePath, BuildConfig.BUNDLED_YTDLP_VERSION), backend)
                assertTrue(output.contains("VIDFETCH_COMPATIBILITY_OK"))
            }
            val info = YtDlpRepositoryImpl(context).parseVideoInfo(File(folder, "compat-info.json").readText())
            assertEquals(listOf(null, 240), qualities(info.formats).filterNot { it.audioOnly }.map { it.height })
            assertTrue(qualities(info.formats).any { it.audioOnly })
        } finally { folder.deleteRecursively() }
    }

    @Test fun updatedCompatibilityUsesAppCliAndReportsRealErrors() = runBlocking {
        val backend = ExtractorBackend.COMPATIBILITY
        val folder = File(context.cacheDir, "compatibility-cli-test").apply { mkdirs() }
        val native = context.applicationInfo.nativeLibraryDir
        val repository = YtDlpRepositoryImpl(context)
        try {
            ExtractorRuntime.python(context, listOf("-c", """
                import subprocess
                subprocess.check_call(['$native/libffmpeg.so', '-y', '-f', 'lavfi', '-i', 'color=c=blue:s=320x240:d=1', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-c:v', 'libx264', '-c:a', 'aac', '-shortest', '${folder.absolutePath}/source.mp4'])
                subprocess.check_call(['$native/libffmpeg.so', '-y', '-i', '${folder.absolutePath}/source.mp4', '-c', 'copy', '-hls_time', '1', '-hls_list_size', '0', '${folder.absolutePath}/source.m3u8'])
            """.trimIndent()), backend)
            val script = File(folder, "compatibility_check.py")
            ExtractorInstrumentationRunner.active.context.assets.open("compatibility_check.py").use { input -> script.outputStream().use { input.copyTo(it) } }
            FixtureServer(folder).use { server ->
                val config = File(folder, "cli.json")
                suspend fun cli(arguments: List<String>, warning: Boolean = false, failure: Boolean = false, executionBackend: ExtractorBackend = backend, publicFallback: Boolean = false): String {
                    config.writeText(JSONObject().put("arguments", JSONArray(arguments)).put("warning", warning).put("failure", failure).put("public_fallback", publicFallback).toString())
                    return ExtractorRuntime.python(context, listOf(script.absolutePath, ExtractorRuntime.engineFile(context).absolutePath,
                        native, "http://127.0.0.1:${server.port}", folder.absolutePath, BuildConfig.BUNDLED_YTDLP_VERSION, config.absolutePath), executionBackend)
                }
                for ((label, url) in listOf("reddit" to "https://www.reddit.com/r/videos/s/synthetic", "redgifs" to "https://www.redgifs.com/watch/syntheticclip")) {
                    assertNull(SiteCookieStore(context).snapshotFor(url))
                    val info = repository.parseVideoInfo(cli(repository.analysisArguments(null, url, chrome = false), warning = true))
                    assertEquals(listOf(null, 240), qualities(info.formats).filterNot { it.audioOnly }.map { it.height })
                    val destination = File(folder, "$label.mp4")
                    val output = cli(repository.downloadArguments(null, url, 360, destination.absolutePath, chrome = false))
                    assertTrue(output.contains("VIDFETCH_HEIGHT:240"))
                    val completed = repository.completedDownload(output, destination.absolutePath)
                    assertEquals(240, completed.height)
                    assertEquals(destination.canonicalFile, completed.file)
                    assertTrue(destination.length() > 1000)
                    val probe = ExtractorRuntime.python(context, listOf("-c", """
                        import subprocess
                        print(subprocess.check_output(['$native/libffprobe.so', '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', '${destination.absolutePath}'], text=True))
                    """.trimIndent()), backend)
                    assertTrue(probe.contains("video") && probe.contains("audio"))
                    val audioTemplate = File(folder, "$label-audio.%(ext)s").absolutePath
                    val audioOutput = cli(repository.downloadArguments(null, url, null, audioTemplate, audioOnly = true, chrome = false))
                    val audio = repository.completedDownload(audioOutput, audioTemplate, audioOnly = true)
                    assertEquals("m4a", audio.file.extension)
                    assertNull(audio.height)
                    val audioProbe = ExtractorRuntime.media(context, "ffprobe", listOf("-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", audio.file.absolutePath))
                    assertTrue(audioProbe.contains("audio"))
                    assertFalse(audioProbe.contains("video"))
                }
                val redditUrl = "https://www.reddit.com/r/videos/s/synthetic"
                val chromeInfo = repository.parseVideoInfo(cli(repository.analysisArguments(null, redditUrl, chrome = true), executionBackend = ExtractorBackend.CURRENT))
                assertTrue(chromeInfo.formats.isNotEmpty())
                val chromeOutput = File(folder, "reddit-chrome.mp4")
                val chromeResult = cli(repository.downloadArguments(null, redditUrl, 360, chromeOutput.absolutePath, chrome = true), executionBackend = ExtractorBackend.CURRENT)
                assertEquals(240, repository.completedDownload(chromeResult, chromeOutput.absolutePath).height)
                for (attempt in extractionAttempts(redditUrl).take(2)) {
                    val publicInfo = repository.parseVideoInfo(cli(repository.analysisArguments(null, redditUrl, attempt.chrome), executionBackend = attempt.backend, publicFallback = true))
                    assertEquals("Public page fixture", publicInfo.title)
                    val publicFile = File(folder, "public-${attempt.backend}.mp4")
                    val publicOutput = cli(repository.downloadArguments(null, redditUrl, 360, publicFile.absolutePath, chrome = attempt.chrome), executionBackend = attempt.backend, publicFallback = true)
                    assertEquals(240, repository.completedDownload(publicOutput, publicFile.absolutePath).height)
                }
                val failure = runCatching { cli(repository.analysisArguments(null, redditUrl, chrome = false), warning = true, failure = true) }.exceptionOrNull()
                assertNotNull(failure)
                assertTrue(failure!!.message.orEmpty().contains("Private subreddit"))
                assertFalse(failure.message.orEmpty().contains("older than 90 days"))
                assertFalse(friendlyError(failure as Exception).contains("outdated"))
            }
        } finally { folder.deleteRecursively() }
    }

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
            assertEquals(listOf(null, 1080, 720, 480, 240), options.filterNot { it.audioOnly }.map { it.height })
            assertTrue(options.last().audioOnly)
            assertEquals(22L, options.single { it.height == 720 }.estimatedBytes)
            assertTrue(info.formats.first().hasVideo)
            assertNull(info.formats.first().videoCodec)
            assertTrue(info.formats.first().hasAudio)
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
                    val audio = repository.download(url, null, File(folder, "audio-${path.substringAfterLast('.')}.%(ext)s").absolutePath, audioOnly = true) { }
                    assertEquals("m4a", audio.file.extension)
                    assertNull(audio.height)
                    val audioProbe = ExtractorRuntime.media(context, "ffprobe", listOf("-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", audio.file.absolutePath))
                    assertTrue(audioProbe.contains("audio"))
                    assertFalse(audioProbe.contains("video"))
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

    @Test fun redditAliasesReceiveScopedCookiesAndCurrentRuntimeSupportsChrome() = runBlocking {
        val store = SiteCookieStore(context)
        val repository = YtDlpRepositoryImpl(context)
        try {
            store.importFile("reddit.com", "# Netscape HTTP Cookie File\n#HttpOnly_.reddit.com\tTRUE\t/\tTRUE\t0\treddit_session\tsynthetic\n".byteInputStream())
            for (url in listOf("https://redd.it/fixture", "https://v.redd.it/fixture", "https://old.reddit.com/comments/fixture")) {
                val snapshot = store.snapshotFor(url)!!
                try {
                    val arguments = repository.analysisArguments(snapshot, url)
                    assertEquals("chrome", arguments[arguments.indexOf("--impersonate") + 1])
                    assertEquals(snapshot.absolutePath, arguments[arguments.indexOf("--cookies") + 1])
                } finally { snapshot.delete() }
            }
            assertNull(store.snapshotFor("https://reddit.com.attacker.example/video"))
            val capability = ExtractorRuntime.python(context, listOf("-c", """
                import sys
                sys.path.insert(0, '${ExtractorRuntime.engineFile(context).absolutePath}')
                from yt_dlp import YoutubeDL
                from yt_dlp.networking.impersonate import ImpersonateTarget
                with YoutubeDL({'quiet': True, 'impersonate': ImpersonateTarget.from_str('chrome')}):
                    print('VIDFETCH_CHROME_OK')
            """.trimIndent()))
            assertTrue(capability.contains("VIDFETCH_CHROME_OK"))
        } finally { store.delete("reddit.com") }
    }

    @Test fun userProvidedYoutubeLink() = runBlocking {
        val url = ExtractorInstrumentationRunner.active.arguments.getString("liveUrl") ?: return@runBlocking
        val repository = YtDlpRepositoryImpl(context)
        val info = repository.analyze(url)
        val input = android.net.Uri.parse(url)
        val expectedId = if (input.host == "youtu.be") input.lastPathSegment else input.getQueryParameter("v")
        assertEquals(expectedId, info.id)
        assertTrue(info.formats.any { it.hasVideo })
        val destination = File(context.cacheDir, "live-smoke.%(ext)s")
        try {
            repository.download(url, 360, destination.absolutePath) { }
            assertTrue(context.cacheDir.listFiles().orEmpty().any { it.name.startsWith("live-smoke.") && it.length() > 1000 && it.extension != "part" })
        }
        finally { context.cacheDir.listFiles()?.filter { it.name.startsWith("live-smoke.") }?.forEach { it.delete() } }
    }
}

internal class FixtureServer(private val folder: File) : AutoCloseable {
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
                    val type = when (file.extension) { "m3u8" -> "application/vnd.apple.mpegurl"; "mpd" -> "application/dash+xml"; "ts" -> "video/mp2t"; "html" -> "text/html"; "json" -> "application/json"; else -> "video/mp4" }
                    val canonical = when (file.name) {
                        "share.html" -> "X-Fixture-Url: https://www.reddit.com/r/videos/comments/fixture123/\r\n"
                        "session.html" -> "Set-Cookie: loid=synthetic-loid; Domain=.reddit.com; Path=/\r\n"
                        else -> ""
                    }
                    val header = "HTTP/1.1 ${if (valid) "200 OK" else "404 Not Found"}\r\nContent-Type: $type\r\nContent-Length: ${bytes.size}\r\n${canonical}Connection: close\r\n\r\n"
                    socket.getOutputStream().write(header.toByteArray())
                    if (request[0] != "HEAD") socket.getOutputStream().write(bytes)
                }
            }
        }
    }
    override fun close() { server.close(); worker.join(2000) }
}
