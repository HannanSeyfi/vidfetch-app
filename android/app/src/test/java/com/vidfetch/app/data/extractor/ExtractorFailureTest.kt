package com.vidfetch.app.data.extractor

import org.junit.Assert.*
import org.junit.Test

class ExtractorFailureTest {
    @Test fun warningAndEarlierErrorsDoNotReplaceTheLastFailure() {
        assertEquals("ERROR: [Reddit] HTTP Error 403: Forbidden\nDetails", extractorFailureDetail("""
            WARNING: Your yt-dlp version is older than 90 days!
                     Update recommended.
            ERROR: Earlier failure
            WARNING: Retrying
            ERROR: [Reddit] HTTP Error 403: Forbidden
            Details
        """.trimIndent(), 1))
        assertEquals("ERROR: No video formats found", extractorFailureDetail("\u001B[0;31mERROR:\u001B[0m No video formats found", 1))
    }

    @Test fun pythonFailuresAndEmptyStderrRemainUseful() {
        val trace = "Traceback (most recent call last):\nImportError: missing dependency"
        assertEquals(trace, extractorFailureDetail(trace, 1))
        assertEquals("Extraction failed (exit 2)", extractorFailureDetail("", 2))
    }
}
