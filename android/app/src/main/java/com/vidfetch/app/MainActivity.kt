package com.vidfetch.app

import android.content.ClipDescription
import android.content.ClipboardManager
import android.content.Intent
import android.os.Bundle
import android.os.Environment
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.vidfetch.app.data.extractor.YtDlpRepositoryImpl
import com.vidfetch.app.domain.*
import kotlinx.coroutines.launch
import java.util.regex.Pattern

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) { super.onCreate(savedInstanceState); setContent { MaterialTheme(colorScheme = if (isSystemInDarkTheme()) darkColorScheme() else lightColorScheme()) { VidFetchScreen(sharedUrl(intent)) } } }
    private fun sharedUrl(intent: Intent?): String = if (intent?.action == Intent.ACTION_SEND) URL.matcher(intent.getStringExtra(Intent.EXTRA_TEXT).orEmpty()).let { if (it.find()) it.group() else "" } else ""
    companion object { private val URL = Pattern.compile("https?://[^\\s]+") }
}

@Composable private fun VidFetchScreen(initialUrl: String) {
    val scope = rememberCoroutineScope(); val context = androidx.compose.ui.platform.LocalContext.current; val repo = remember { YtDlpRepositoryImpl(context.applicationContext) }
    var url by remember { mutableStateOf(initialUrl) }; var info by remember { mutableStateOf<VideoInfo?>(null) }; var selected by remember { mutableStateOf<VideoQuality?>(null) }; var loading by remember { mutableStateOf(false) }; var message by remember { mutableStateOf<String?>(null) }; var tab by remember { mutableIntStateOf(0) }
    Scaffold(bottomBar = { NavigationBar { listOf("Home", "Downloads", "Settings").forEachIndexed { i, label -> NavigationBarItem(selected = i == tab, onClick = { tab = i }, icon = {}, label = { Text(label) }) } } }) { pad ->
        when (tab) {
            0 -> Column(Modifier.padding(pad).padding(20.dp).fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                Text("VidFetch", style = MaterialTheme.typography.headlineMedium)
                OutlinedTextField(value = url, onValueChange = { url = it }, label = { Text("Paste video URL") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedButton(onClick = { val clipboard = context.getSystemService(ClipboardManager::class.java); url = clipboard?.primaryClip?.getItemAt(0)?.coerceToText(context)?.toString().orEmpty() }) { Text("Paste") }
                    Button(enabled = !loading, onClick = { if (!url.startsWith("http://") && !url.startsWith("https://")) message = "Enter a valid http or https URL." else scope.launch { loading = true; message = null; try { info = repo.analyze(url); selected = qualities(info!!.formats).firstOrNull() } catch (e: Exception) { message = "Could not analyze this link: ${e.message ?: "extractor error"}" } finally { loading = false } } }) { Text("Analyze") }
                }
                if (loading) { LinearProgressIndicator(Modifier.fillMaxWidth()); Text("Analyzing video…") }
                message?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                info?.let { video ->
                    AsyncImage(model = video.thumbnailUrl, contentDescription = "Video thumbnail", modifier = Modifier.fillMaxWidth().height(190.dp))
                    Text(video.title, style = MaterialTheme.typography.titleLarge); Text(listOfNotNull(video.uploader, formatDuration(video.durationSeconds)).joinToString(" · "))
                    Text("Quality", style = MaterialTheme.typography.titleMedium)
                    qualities(video.formats).forEach { quality -> Row(Modifier.fillMaxWidth().selectable(selected = selected == quality, onClick = { selected = quality }).padding(vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) { RadioButton(selected = selected == quality, onClick = null); Column(Modifier.padding(start = 12.dp)) { Text(quality.label); Text(formatBytes(quality.estimatedBytes), style = MaterialTheme.typography.bodySmall) } }
                    }
                    Button(onClick = { scope.launch { try { loading = true; val output = java.io.File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "VidFetch").apply { mkdirs() }; repo.download(video.webpageUrl, selected?.height, java.io.File(output, "%(title)s.%(ext)s").absolutePath) { percent -> message = "Downloading… $percent%" }; message = "Download complete in Downloads/VidFetch." } catch (e: Exception) { message = "Download failed: ${e.message ?: "unknown error"}" } finally { loading = false } } }, modifier = Modifier.fillMaxWidth()) { Text("Download video") }
                }
            }
            1 -> Column(Modifier.padding(pad).padding(20.dp)) { Text("Downloads", style = MaterialTheme.typography.headlineMedium); Text("Your active and completed downloads will appear here.") }
            else -> Column(Modifier.padding(pad).padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) { Text("Settings", style = MaterialTheme.typography.headlineMedium); Text("Downloads are published to Downloads/VidFetch."); Text("Download content only when you have permission to do so and in accordance with the applicable website's terms and local law.") }
        }
    }
}
