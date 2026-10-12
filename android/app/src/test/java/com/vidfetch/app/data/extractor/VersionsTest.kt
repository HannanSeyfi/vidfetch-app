package com.vidfetch.app.data.extractor

import org.junit.Assert.*
import org.junit.Test

class VersionsTest {
    @Test fun upgradeComparisonHandlesStableAndNightlyVersions() {
        assertTrue(compareVersions("2025.11.12", "2026.10.10.233141") < 0)
        assertTrue(compareVersions("2026.10.11.1", "2026.10.10.233141") > 0)
        assertTrue(compareVersions("2026.10.10", "2026.10.10.233141") < 0)
        assertEquals(0, compareVersions("2026.10.10.233141", "2026.10.10.233141"))
    }
}
