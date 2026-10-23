package com.vidfetch.app.data.extractor

import android.Manifest
import android.content.ContextWrapper
import android.content.Intent
import android.os.Build
import android.os.SystemClock
import com.vidfetch.app.MainActivity
import com.vidfetch.app.data.storage.DownloadedMediaRepository
import com.vidfetch.app.service.DownloadState
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import java.io.File

/** Shared link -> quality radio button -> foreground service -> playable audio in Downloads. */
internal fun checkSharedLinkAudioDownload() = runBlocking {
    val runner = ExtractorInstrumentationRunner.active
    val context = runner.targetContext
    fun shell(command: String) {
        android.os.ParcelFileDescriptor.AutoCloseInputStream(runner.uiAutomation.executeShellCommand(command)).use { it.readBytes() }
    }
    if (Build.VERSION.SDK_INT <= 28) {
        shell("pm grant ${context.packageName} ${Manifest.permission.READ_EXTERNAL_STORAGE}")
        shell("pm grant ${context.packageName} ${Manifest.permission.WRITE_EXTERNAL_STORAGE}")
    }
    if (Build.VERSION.SDK_INT >= 33) shell("pm grant ${context.packageName} ${Manifest.permission.POST_NOTIFICATIONS}")
    val name = "audio-flow-${java.util.UUID.randomUUID()}"
    val folder = File(context.cacheDir, name).apply { mkdirs() }
    val source = File(folder, "$name.mp4")
    val media = DownloadedMediaRepository(context)
    var activity: android.app.Activity? = null
    try {
        ExtractorRuntime.media(context, "ffmpeg", listOf("-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:v", "libx264", "-c:a", "aac", "-shortest", source.absolutePath))
        FixtureServer(folder).use { server ->
            val intent = Intent(context, MainActivity::class.java).setAction(Intent.ACTION_SEND).setType("text/plain")
                .putExtra(Intent.EXTRA_TEXT, "http://127.0.0.1:${server.port}/${source.name}")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            activity = runner.startActivitySync(intent)
            clickText("Analyze")
            clickText("Audio only · M4A", scroll = true)
            val completion = DownloadState.progress.value.completion
            clickText("Download audio", scroll = true)
            val deadline = SystemClock.uptimeMillis() + 60_000
            while (DownloadState.progress.value.completion == completion && SystemClock.uptimeMillis() < deadline) {
                SystemClock.sleep(100)
            }
            assertTrue("Audio download failed: ${DownloadState.progress.value}", DownloadState.progress.value.completion > completion)
            assertTrue(DownloadState.progress.value.message.orEmpty().contains("Audio only"))
        }
        val saved = media.list().single { it.title.startsWith(name) }
        assertTrue(saved.isAudio)
        assertTrue(saved.title.endsWith(".m4a"))
        // Older FileProvider MIME tables label .m4a as audio/mpeg. The app's
        // actual playback/sharing intents must still advertise the M4A container.
        assertTrue(context.contentResolver.getType(saved.uri).orEmpty().startsWith("audio/"))
        var launched: Intent? = null
        val actions = DownloadedMediaRepository(object : ContextWrapper(context) {
            override fun startActivity(intent: Intent) { launched = intent }
        })
        actions.open(saved)
        assertEquals(Intent.ACTION_VIEW, launched!!.action)
        assertEquals("audio/mp4", launched!!.type)
        assertEquals(saved.uri, launched!!.data)
        assertTrue(launched!!.flags and Intent.FLAG_GRANT_READ_URI_PERMISSION != 0)
        actions.share(saved)
        assertEquals(Intent.ACTION_CHOOSER, launched!!.action)
        @Suppress("DEPRECATION")
        val send = launched!!.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)!!
        assertEquals(Intent.ACTION_SEND, send.action)
        assertEquals("audio/mp4", send.type)
        assertEquals(saved.uri, send.clipData!!.getItemAt(0).uri)
        assertTrue(send.flags and Intent.FLAG_GRANT_READ_URI_PERMISSION != 0)
        val verification = File(folder, "verify.m4a")
        context.contentResolver.openInputStream(saved.uri)!!.use { input -> verification.outputStream().use { input.copyTo(it) } }
        val streams = ExtractorRuntime.media(context, "ffprobe", listOf("-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", verification.absolutePath))
        assertTrue(streams.contains("audio"))
        assertFalse(streams.contains("video"))
        assertTrue(media.rename(saved, "$name-renamed"))
        val renamed = media.list().single { it.title == "$name-renamed.m4a" }
        assertTrue(renamed.isAudio)
        assertTrue(media.delete(renamed))
        assertFalse(media.list().any { it.title.startsWith(name) })
    } finally {
        activity?.let { active -> runner.runOnMainSync { active.finish() } }
        media.list().filter { it.title.startsWith(name) }.forEach { media.delete(it) }
        folder.deleteRecursively()
    }
}
