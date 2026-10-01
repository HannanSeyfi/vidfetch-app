package com.vidfetch.app.domain

import org.junit.Assert.*
import org.junit.Test

class FormattersTest {
    @Test fun durationIsReadable() { assertEquals("1:13:45", formatDuration(4425)); assertEquals("3:42", formatDuration(222)) }
    @Test fun qualityGroupsDuplicatesAndSorts() { val f = listOf(VideoFormat("a", 720, null, null, null, null, null, 2L, null, null, true, false), VideoFormat("b", 1080, null, null, null, null, null, 3L, null, null, true, false), VideoFormat("c", 1080, null, null, null, null, null, 4L, null, null, true, false)); assertEquals(listOf(null, 1080, 720), qualities(f).map { it.height }) }
    @Test fun exactSelectorPrefersExactHeight() { assertTrue(selectorFor(1080).contains("height=1080")); assertEquals("bestvideo*+bestaudio/best", selectorFor(null)) }
    @Test fun filenameIsSafe() { assertEquals("bad_name_.mp4", safeFilename("bad:name?")) }
}
