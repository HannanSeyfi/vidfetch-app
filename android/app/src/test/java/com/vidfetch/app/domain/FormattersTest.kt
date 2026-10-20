package com.vidfetch.app.domain

import org.junit.Assert.*
import org.junit.Test

class FormattersTest {
    @Test fun durationIsReadable() { assertEquals("1:13:45", formatDuration(4425)); assertEquals("3:42", formatDuration(222)) }
    @Test fun qualityGroupsDuplicatesAndSorts() { val f = listOf(VideoFormat("a", 720, null, null, null, null, null, 2L, null, null, true, false), VideoFormat("b", 1080, null, null, null, null, null, 3L, null, null, true, false), VideoFormat("c", 1080, null, null, null, null, null, 4L, null, null, true, false)); assertEquals(listOf(null, 1080, 720), qualities(f).map { it.height }) }
    @Test fun exactSelectorPrefersExactHeight() { assertTrue(selectorFor(1080).contains("height=1080")); assertEquals("bestvideo*+bestaudio/best", selectorFor(null)) }
    @Test fun audioChoiceIsDistinctFromBestVideoAndHasNoMisleadingVideoSize() {
        val video = VideoFormat("combined", 720, null, null, "mp4", "h264", "aac", 1000L, null, null, true, true)
        val audio = video.copy(formatId = "audio", height = null, hasVideo = false, filesize = 100L)
        val choices = qualities(listOf(video, audio))
        assertEquals(listOf(null, 720, null), choices.map { it.height })
        assertFalse(choices.first().audioOnly)
        assertTrue(choices.last().audioOnly)
        assertEquals("Audio only · M4A", choices.last().label)
        assertNull(choices.last().estimatedBytes)
        assertNotEquals(choices.first(), choices.last())
    }
    @Test fun silentVideoHasNoAudioChoiceAndAudioLinksHaveNoVideoChoice() {
        val silent = VideoFormat("silent", 240, null, null, "mp4", "h264", "none", null, null, null, true, false)
        assertFalse(qualities(listOf(silent)).any { it.audioOnly })
        assertTrue(qualities(listOf(silent.copy(height = null, hasVideo = false, hasAudio = true))).single().audioOnly)
    }
    @Test fun audioSelectorPrefersSeparateAudioThenCombinedAudioAcrossSites() {
        for (url in listOf("https://youtu.be/example", "https://www.pornhub.com/view_video.php?viewkey=example", "https://www.reddit.com/r/videos/example", "https://example.com/video")) {
            assertEquals("bestaudio/best[acodec!=?none]", selectorFor(720, url, audioOnly = true))
        }
    }
    @Test fun filenameIsSafe() { assertEquals("bad_name_.mp4", safeFilename("bad:name?")) }
    @Test fun directMp4IsPreferredForPornhub() {
        val selector = selectorFor(720, "https://www.pornhub.com/view_video.php?viewkey=example")
        assertTrue(selector.indexOf("[protocol=https][ext=mp4]") < selector.indexOf("best[height<=720]"))
        assertFalse(selector.contains("+bestaudio"))
    }
    @Test fun exactCombinedFormatPrecedesLowerSeparateStreams() {
        val selector = selectorFor(1080, "https://example.com/video")
        assertTrue(selector.indexOf("best[height=1080]") < selector.indexOf("height<=1080"))
        assertTrue(selector.contains("bestvideo*"))
        assertFalse(selector.endsWith("/best"))
    }
    @Test fun youtubePrefersM4aAudioWithoutLosingTheChosenResolution() {
        val selector = selectorFor(720, "https://youtu.be/example")
        assertTrue(selector.startsWith("bestvideo*[height=720]+bestaudio[ext=m4a]"))
        assertTrue(selector.indexOf("best[height=720]") < selector.indexOf("height<=720"))
        assertTrue(selectorFor(null, "https://www.youtube.com/watch?v=example").startsWith("bestvideo*+bestaudio[ext=m4a]"))
    }
    @Test fun siteMatchingDoesNotAcceptLookalikeHosts() {
        assertEquals("youtube.com", siteForUrl("https://youtu.be/example"))
        assertEquals("youtube.com", siteForUrl("https://m.youtube.com/watch?v=example"))
        assertEquals("youtube.com.attacker.example", siteForUrl("https://youtube.com.attacker.example/video"))
        assertFalse(selectorFor(720, "https://pornhub.com.attacker.example/video").contains("[protocol=https]"))
        assertNull(normalizedHost("https://youtube.com@attacker.example/video"))
        assertNull(normalizedHost("file:///tmp/video"))
    }
}
