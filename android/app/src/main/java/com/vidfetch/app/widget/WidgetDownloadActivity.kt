package com.vidfetch.app.widget

import android.content.ClipboardManager
import android.os.Bundle
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.viewmodel.compose.viewModel
import com.vidfetch.app.HomeScreen
import com.vidfetch.app.MainActivity
import com.vidfetch.app.VidFetchViewModel
import com.vidfetch.app.service.DownloadState

/** A real, focused activity is necessary for clipboard access from a launcher widget. */
class WidgetDownloadActivity : MainActivity() {
    private var pasted = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.setLayout((resources.displayMetrics.widthPixels * 0.94).toInt(), (resources.displayMetrics.heightPixels * 0.82).toInt())
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus && !pasted) {
            pasted = true
            val clip = getSystemService(ClipboardManager::class.java)?.primaryClip
            if (clip != null && clip.itemCount > 0) sharedLink.value = clip.getItemAt(0).coerceToText(this)?.toString().orEmpty()
        }
    }

    @Composable override fun Content() {
        val model: VidFetchViewModel = viewModel()
        val state by model.state.collectAsState()
        val progress by DownloadState.progress.collectAsState()
        val dark = getSharedPreferences("vidfetch_settings", 0).getBoolean("dark_theme", isSystemInDarkTheme())
        MaterialTheme(colorScheme = if (dark) darkColorScheme() else lightColorScheme()) {
            LaunchedEffect(sharedLink.value) { model.acceptSharedUrl(sharedLink.value) }
            androidx.compose.material3.Surface {
                Column(Modifier.fillMaxSize()) {
                    TextButton(onClick = ::finish) { Text("Close") }
                    HomeScreen(Modifier.weight(1f), state, progress, model::setUrl, model::setSelected, model::analyze, ::beginDownload)
                }
            }
        }
    }
}
