package com.vidfetch.app.data.extractor

import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

class RuntimeArchiveTest {
    @Test fun readsUnixSymlinkModeInsteadOfTreatingLinkTextAsLibrary() {
        val file = File.createTempFile("runtime-test-", ".zip")
        try {
            ZipOutputStream(file.outputStream()).use { zip ->
                zip.putNextEntry(ZipEntry("usr/lib/libz.so"))
                zip.write("libz.so.1".toByteArray())
                zip.closeEntry()
            }
            assertTrue(runtimeArchiveLinks(file).isEmpty())
            val bytes = file.readBytes()
            val central = (0 until bytes.size - 46).first { i ->
                bytes[i] == 0x50.toByte() && bytes[i + 1] == 0x4b.toByte() && bytes[i + 2] == 0x01.toByte() && bytes[i + 3] == 0x02.toByte()
            }
            ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).putInt(central + 38, 0xa1ff shl 16)
            file.writeBytes(bytes)
            assertEquals(setOf("usr/lib/libz.so"), runtimeArchiveLinks(file))
        } finally { file.delete() }
    }
}
