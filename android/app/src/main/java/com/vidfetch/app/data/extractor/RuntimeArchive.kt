package com.vidfetch.app.data.extractor

import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** java.util.zip omits Unix mode bits; read them from the ZIP central directory. */
internal fun runtimeArchiveLinks(archive: File): Set<String> = RandomAccessFile(archive, "r").use { input ->
    require(input.length() >= 22) { "Invalid runtime archive" }
    val tailSize = minOf(input.length(), 65557L).toInt()
    val tail = ByteArray(tailSize)
    input.seek(input.length() - tailSize)
    input.readFully(tail)
    val end = (tailSize - 22 downTo 0).firstOrNull { index ->
        tail[index] == 0x50.toByte() && tail[index + 1] == 0x4b.toByte() && tail[index + 2] == 0x05.toByte() && tail[index + 3] == 0x06.toByte() &&
            index + 22 + (ByteBuffer.wrap(tail, index + 20, 2).order(ByteOrder.LITTLE_ENDIAN).short.toInt() and 0xffff) == tailSize
    } ?: error("Invalid runtime ZIP directory")
    val footer = ByteBuffer.wrap(tail, end, 22).slice().order(ByteOrder.LITTLE_ENDIAN)
    val count = footer.getShort(10).toInt() and 0xffff
    val offset = footer.getInt(16).toLong() and 0xffffffffL
    require(count != 65535 && offset < input.length()) { "Unsupported runtime ZIP directory" }
    input.seek(offset)
    buildSet {
        repeat(count) {
            val bytes = ByteArray(46)
            input.readFully(bytes)
            val header = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
            require(header.getInt(0) == 0x02014b50) { "Invalid runtime ZIP entry" }
            val nameSize = header.getShort(28).toInt() and 0xffff
            val extraSize = header.getShort(30).toInt() and 0xffff
            val commentSize = header.getShort(32).toInt() and 0xffff
            val mode = header.getInt(38) ushr 16
            val name = ByteArray(nameSize).also { input.readFully(it) }.toString(Charsets.UTF_8)
            if ((mode and 0xf000) == 0xa000) add(name)
            input.seek(input.filePointer + extraSize + commentSize)
        }
    }
}
