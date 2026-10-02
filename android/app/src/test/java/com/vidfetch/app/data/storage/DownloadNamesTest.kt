package com.vidfetch.app.data.storage

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.io.File
import java.nio.file.Files

class DownloadNamesTest {
    @Test fun unsafeOrEmptyRenameIsHandled() {
        assertEquals("bad_name_", cleanName(" bad:name? "))
        assertNull(cleanName("  ...  "))
    }

    @Test fun existingDownloadGetsAUniqueName() {
        val directory = Files.createTempDirectory("vidfetch-names").toFile()
        try {
            File(directory, "clip.mp4").createNewFile()
            assertEquals("clip (2).mp4", uniqueFile(directory, "clip.mp4").name)
            File(directory, "clip (2).mp4").createNewFile()
            assertEquals("clip (3).mp4", uniqueFile(directory, "clip.mp4").name)
        } finally {
            directory.deleteRecursively()
        }
    }

    @Test fun mediaStoreNameDoesNotCollide() {
        assertEquals("clip (3).mp4", uniqueName("clip.mp4", setOf("clip.mp4", "clip (2).mp4")))
    }
}
