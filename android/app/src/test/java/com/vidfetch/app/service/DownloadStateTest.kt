package com.vidfetch.app.service

import com.vidfetch.app.domain.DownloadStatus
import org.junit.Assert.*
import org.junit.Test
import kotlin.concurrent.thread

class DownloadStateTest {
    @Test fun cancellingOneTransferLeavesTheOthersActive() {
        val tracker = DownloadTracker()
        tracker.queued("a", "First", "720p")
        tracker.queued("b", "Second", "Audio only")
        tracker.status("a", DownloadStatus.DOWNLOADING)
        tracker.advanced("a", 46)
        tracker.cancelled("a")
        tracker.advanced("a", 90)
        tracker.finished("a", "Should not be published")
        val state = tracker.progress.value
        assertEquals(DownloadStatus.CANCELLED, state.downloads[0].status)
        assertEquals(46, state.downloads[0].percent)
        assertEquals(DownloadStatus.QUEUED, state.downloads[1].status)
        assertTrue(state.active)
        assertEquals(0L, state.completion)
    }

    @Test fun concurrentProgressAndCompletionDoNotLoseOtherTransfers() {
        val tracker = DownloadTracker()
        repeat(8) { tracker.queued("$it", "Video $it", "360p") }
        (0 until 8).map { index -> thread {
            tracker.status("$index", DownloadStatus.DOWNLOADING)
            repeat(100) { tracker.advanced("$index", it) }
            tracker.finished("$index", "Saved $index")
            tracker.finished("$index", "Duplicate completion")
        } }.forEach { it.join() }
        val state = tracker.progress.value
        assertEquals(8L, state.completion)
        assertFalse(state.active)
        assertTrue(state.downloads.all { it.percent == 100 && it.status == DownloadStatus.COMPLETED })
    }
}
