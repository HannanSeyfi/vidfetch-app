package com.vidfetch.app.data.extractor

import android.Manifest
import android.content.Intent
import android.os.Build
import android.os.Environment
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import com.vidfetch.app.MainActivity
import com.vidfetch.app.data.storage.DownloadedMediaRepository
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.junit.Assert.*
import java.io.File

internal fun checkYoutubeSeparateStreams() = runBlocking {
    val runner = ExtractorInstrumentationRunner.active
    val context = runner.targetContext
    val native = context.applicationInfo.nativeLibraryDir
    val folder = File(context.cacheDir, "youtube-stream-test").apply { mkdirs() }
    try {
        ExtractorRuntime.python(context, listOf("-c", """
            import subprocess, sys, os
            ffmpeg, folder = sys.argv[1:]
            for height, width in [(240, 320), (360, 640), (480, 854)]:
                webm = height == 480
                subprocess.check_call([ffmpeg, '-y', '-f', 'lavfi', '-i', f'color=c=blue:s={width}x{height}:d=1:r=5', '-an', '-c:v', 'libvpx-vp9' if webm else 'libx264', os.path.join(folder, f'video{height}.' + ('webm' if webm else 'mp4'))])
            for codec, ext in [('aac', 'm4a'), ('libopus', 'webm')]:
                subprocess.check_call([ffmpeg, '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-vn', '-c:a', codec, os.path.join(folder, 'audio.' + ext)])
        """.trimIndent(), "$native/libffmpeg.so", folder.absolutePath))
        val script = File(folder, "youtube_download_check.py")
        runner.context.assets.open(script.name).use { input -> script.outputStream().use { input.copyTo(it) } }
        val repository = YtDlpRepositoryImpl(context)
        FixtureServer(folder).use { server ->
            for (height in listOf(null, 240, 360, 480)) {
                val template = File(folder, "result-${height ?: "best"}.%(ext)s").absolutePath
                val arguments = repository.downloadArguments(null, "https://www.youtube.com/watch?v=synthetic-video", height, template)
                val config = File(folder, "arguments.json").apply { writeText(JSONArray(arguments).toString()) }
                val output = ExtractorRuntime.python(context, listOf(script.absolutePath, ExtractorRuntime.engineFile(context).absolutePath,
                    "http://127.0.0.1:${server.port}", config.absolutePath))
                // A newer audio intermediate must never replace the final merged video.
                File(folder, "audio.webm").setLastModified(System.currentTimeMillis() + 60_000)
                val result = repository.completedDownload(output, template)
                assertEquals(height ?: 480, result.height)
                assertEquals("mp4", result.file.extension)
                val streams = ExtractorRuntime.python(context, listOf("-c", """
                    import subprocess, sys
                    print(subprocess.check_output([sys.argv[1], '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', sys.argv[2]], text=True))
                """.trimIndent(), "$native/libffprobe.so", result.file.absolutePath))
                assertTrue(streams.contains("video") && streams.contains("audio"))
            }
            val audio = File(folder, "audio.webm")
            val error = runCatching { repository.completedDownload("VIDFETCH_FILE:${JSONArray().put(audio.absolutePath).toString().removePrefix("[").removeSuffix("]")}", File(folder, "invalid.%(ext)s").absolutePath) }.exceptionOrNull()
            assertTrue(error?.message.orEmpty().contains("no video stream"))
            for (backend in ExtractorBackend.entries) {
                val template = File(folder, "audio-${backend.name}.%(ext)s").absolutePath
                val arguments = repository.downloadArguments(null, "https://www.youtube.com/watch?v=synthetic-video", 240, template, audioOnly = true)
                assertFalse(arguments.contains("--remux-video"))
                assertFalse(arguments.contains("--merge-output-format"))
                assertFalse(arguments.any { it.contains("height=") })
                val config = File(folder, "audio-arguments.json").apply { writeText(JSONArray(arguments).toString()) }
                val output = ExtractorRuntime.python(context, listOf(script.absolutePath, ExtractorRuntime.engineFile(context).absolutePath,
                    "http://127.0.0.1:${server.port}", config.absolutePath), backend)
                val result = repository.completedDownload(output, template, audioOnly = true)
                assertNull(result.height)
                assertEquals("m4a", result.file.extension)
                val probe = ExtractorRuntime.media(context, "ffprobe", listOf("-v", "error", "-show_entries", "stream=codec_type,codec_name", "-of", "csv=p=0", result.file.absolutePath))
                assertTrue(probe.contains("aac") && probe.contains("audio"))
                assertFalse(probe.contains("video"))
            }
            // A misleading extension must never make a silent/video file valid audio.
            val silent = File(folder, "silent.m4a")
            File(folder, "video240.mp4").copyTo(silent, overwrite = true)
            val invalidAudio = runCatching { repository.completedDownload("VIDFETCH_FILE:${org.json.JSONObject.quote(silent.absolutePath)}", silent.absolutePath, audioOnly = true) }.exceptionOrNull()
            assertTrue(invalidAudio?.message.orEmpty().contains("no audio stream"))
        }
    } finally { folder.deleteRecursively() }
}

internal fun checkDownloadsFolderContents() = runBlocking {
    val runner = ExtractorInstrumentationRunner.active
    val context = runner.targetContext
    fun shell(command: String) { android.os.ParcelFileDescriptor.AutoCloseInputStream(runner.uiAutomation.executeShellCommand(command)).use { it.readBytes() } }
    if (Build.VERSION.SDK_INT <= 28) {
        shell("pm grant ${context.packageName} ${Manifest.permission.READ_EXTERNAL_STORAGE}")
        shell("pm grant ${context.packageName} ${Manifest.permission.WRITE_EXTERNAL_STORAGE}")
    }
    val name = "folder-fixture-${java.util.UUID.randomUUID()}"
    val source = File(context.cacheDir, "$name.mp4")
    val directory = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "VidFetch")
    val original = File(directory, source.name)
    val copied = File(directory, "$name-copy.mp4")
    val outside = File(directory.parentFile, "$name-outside.mp4")
    val renamed = File(directory, "$name-renamed.mp4")
    val media = DownloadedMediaRepository(context)
    var activity: android.app.Activity? = null
    try {
        ExtractorRuntime.python(context, listOf("-c", """
            import subprocess, sys
            subprocess.check_call([sys.argv[1], '-y', '-f', 'lavfi', '-i', 'color=c=blue:s=320x240:d=1', '-c:v', 'libx264', sys.argv[2]])
        """.trimIndent(), "${context.applicationInfo.nativeLibraryDir}/libffmpeg.so", source.absolutePath))
        media.publish(source)
        shell("cp ${original.absolutePath} ${copied.absolutePath}")
        if (Build.VERSION.SDK_INT >= 29) {
            activity = runner.startActivitySync(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            clickText("Downloads")
            clickText("Allow folder access")
            clickText("Use this folder")
            clickText("Allow")
            val deadline = SystemClock.uptimeMillis() + 10_000
            while (!media.hasFolderAccess() && SystemClock.uptimeMillis() < deadline) SystemClock.sleep(100)
            assertTrue("Persistent folder permission was not saved", media.hasFolderAccess())
            assertTrue(DownloadedMediaRepository(context).hasFolderAccess())
        }
        assertTrue(media.list().any { it.title == copied.name })
        shell("mv ${copied.absolutePath} ${outside.absolutePath}")
        assertFalse(media.list().any { it.title == copied.name })
        shell("mv ${outside.absolutePath} ${copied.absolutePath}")
        assertTrue(media.list().any { it.title == copied.name })
        assertTrue(media.rename(media.list().single { it.title == copied.name }, renamed.name))
        assertFalse(media.list().any { it.title == copied.name })
        assertTrue(media.delete(media.list().single { it.title == renamed.name }))
        assertFalse(media.list().any { it.title == renamed.name })
        shell("rm ${original.absolutePath}")
        assertFalse(media.list().any { it.title == original.name })
    } finally {
        activity?.let { active -> runner.runOnMainSync { active.finish() } }
        source.delete()
        for (file in listOf(original, copied, outside, renamed)) shell("rm -f ${file.absolutePath}")
    }
}

internal fun clickText(text: String, scroll: Boolean = false) {
    val runner = ExtractorInstrumentationRunner.active
    val deadline = SystemClock.uptimeMillis() + 15_000
    var visible = emptyList<String>()
    while (SystemClock.uptimeMillis() < deadline) {
        val nodes = mutableListOf<AccessibilityNodeInfo>()
        fun visit(node: AccessibilityNodeInfo) {
            nodes += node
            for (index in 0 until node.childCount) node.getChild(index)?.let(::visit)
        }
        runner.uiAutomation.rootInActiveWindow?.let(::visit)
        visible = nodes.mapNotNull { it.text?.toString() ?: it.contentDescription?.toString() }
        for (candidate in nodes.filter { it.text?.toString()?.trim().equals(text, ignoreCase = true) || it.contentDescription?.toString()?.trim().equals(text, ignoreCase = true) }) {
            var node: AccessibilityNodeInfo? = candidate
            while (node != null && !node.isClickable) node = node.parent
            if (node?.performAction(AccessibilityNodeInfo.ACTION_CLICK) == true) { SystemClock.sleep(500); return }
        }
        if (scroll) nodes.firstOrNull { it.isScrollable }?.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)
        SystemClock.sleep(200)
    }
    error("Could not click '$text' in Android UI. Visible: $visible")
}
