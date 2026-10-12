package com.vidfetch.app.data.extractor

import android.app.Activity
import android.app.Instrumentation
import android.os.Bundle
import org.junit.runner.Description
import org.junit.runner.JUnitCore
import org.junit.runner.Request
import org.junit.runner.notification.Failure
import org.junit.runner.notification.RunListener
import java.io.PrintWriter
import java.io.StringWriter

/** JUnit on native Android instrumentation, using the standard am instrument status protocol. */
class ExtractorInstrumentationRunner : Instrumentation() {
    lateinit var arguments: Bundle
        private set

    override fun onCreate(arguments: Bundle?) {
        this.arguments = arguments ?: Bundle()
        active = this
        start()
    }

    override fun onStart() {
        val core = JUnitCore()
        var current = 0
        var total = 0
        var failure: Failure? = null
        fun status(description: Description, stream: String) = Bundle().apply {
            putString("id", "VidFetch")
            putString("class", description.className)
            putString("test", description.methodName)
            putInt("current", current)
            putInt("numtests", total)
            putString("stream", stream)
        }
        core.addListener(object : RunListener() {
            override fun testRunStarted(description: Description) { total = description.testCount() }
            override fun testStarted(description: Description) {
                current++
                failure = null
                sendStatus(1, status(description, "\n${description.className}:"))
            }
            override fun testFailure(value: Failure) { failure = value }
            override fun testFinished(description: Description) {
                val failed = failure
                val stream = if (failed == null) "." else "\n${failed.trace}\n"
                val bundle = status(description, stream)
                if (failed != null) bundle.putString("stack", failed.trace)
                sendStatus(if (failed == null) 0 else -2, bundle)
            }
        })
        try {
            val method = arguments.getString("class")?.substringAfter('#', "")?.takeIf { it.isNotBlank() }
            val request = if (method == null) Request.aClass(ExtractorRuntimeTest::class.java) else Request.method(ExtractorRuntimeTest::class.java, method)
            val result = core.run(request)
            val stream = if (result.wasSuccessful()) "\nOK (${result.runCount} tests)\n" else "\nFAILURES!!! Tests run: ${result.runCount}, Failures: ${result.failureCount}\n"
            finish(Activity.RESULT_OK, Bundle().apply { putString("stream", stream) })
        } catch (error: Throwable) {
            val trace = StringWriter().also { error.printStackTrace(PrintWriter(it)) }.toString()
            finish(Activity.RESULT_CANCELED, Bundle().apply { putString("shortMsg", error.toString()); putString("stream", trace) })
        }
    }

    companion object { lateinit var active: ExtractorInstrumentationRunner }
}
