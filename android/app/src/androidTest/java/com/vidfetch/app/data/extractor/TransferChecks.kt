package com.vidfetch.app.data.extractor

import android.system.Os
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.*
import java.io.File

/** Real interpreter processes: cancellation must include descendants, not another job. */
internal fun checkParallelProcessesAndCancellation() = runBlocking {
    val context = ExtractorInstrumentationRunner.active.targetContext
    for (backend in ExtractorBackend.entries) {
        val folder = File(context.cacheDir, "parallel-${java.util.UUID.randomUUID()}").apply { mkdirs() }
        val pidFile = File(folder, "child.pid")
        val ready = File(folder, "second.ready")
        val first = async(Dispatchers.IO) {
            ExtractorRuntime.python(context, listOf("-c", """
                import subprocess, time
                child = subprocess.Popen(['/system/bin/sh', '-c', 'sleep 120'])
                with open('${pidFile.absolutePath}', 'w') as stream:
                    stream.write(str(child.pid))
                time.sleep(120)
            """.trimIndent()), backend)
        }
        var second: kotlinx.coroutines.Deferred<String>? = null
        try {
            withTimeout(30_000) { while (!pidFile.exists() || pidFile.length() == 0L) delay(50) }
            val child = pidFile.readText().toInt()
            val survivor = async(Dispatchers.IO) {
                ExtractorRuntime.python(context, listOf("-c", """
                    import time
                    open('${ready.absolutePath}', 'w').close()
                    time.sleep(2)
                    print('SECOND_DOWNLOAD_SURVIVED')
                """.trimIndent()), backend)
            }
            second = survivor
            // A global extraction mutex would prevent the second request from starting.
            withTimeout(15_000) { while (!ready.exists()) delay(50) }
            withTimeout(10_000) { first.cancelAndJoin() }
            assertTrue(withTimeout(15_000) { survivor.await() }.contains("SECOND_DOWNLOAD_SURVIVED"))
            withTimeout(10_000) {
                while (runCatching { Os.kill(child, 0) }.isSuccess &&
                    runCatching { File("/proc/$child/stat").readText().substringAfter(") ").first() != 'Z' }.getOrDefault(true)) delay(50)
            }
        } finally {
            first.cancelAndJoin()
            second?.cancelAndJoin()
            folder.deleteRecursively()
        }
    }
}
