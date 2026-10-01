package com.vidfetch.app

import android.content.ClipboardManager
import android.content.Intent
import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Build
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.vidfetch.app.data.extractor.YtDlpRepositoryImpl
import com.vidfetch.app.data.storage.DownloadedMedia
import com.vidfetch.app.data.storage.DownloadedMediaRepository
import com.vidfetch.app.notification.DownloadNotifier
import com.vidfetch.app.domain.*
import kotlinx.coroutines.launch
import java.io.File
import java.util.regex.Pattern

class MainActivity : ComponentActivity() {
    private val notificationPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        val incomingUrl = sharedUrl(intent)
        setContent { VidFetchApp(incomingUrl) }
    }
    private fun sharedUrl(intent: Intent?): String = if (intent?.action == Intent.ACTION_SEND) URL.matcher(intent.getStringExtra(Intent.EXTRA_TEXT).orEmpty()).let { if (it.find()) it.group() else "" } else ""
    companion object { private val URL = Pattern.compile("https?://[^\\s]+") }
}

@Composable private fun VidFetchApp(initialUrl: String) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val preferences = remember { context.getSharedPreferences("vidfetch_settings", 0) }
    val systemDarkTheme = isSystemInDarkTheme()
    var darkTheme by remember { mutableStateOf(preferences.getBoolean("dark_theme", systemDarkTheme)) }
    MaterialTheme(colorScheme = if (darkTheme) darkColorScheme() else lightColorScheme()) {
        VidFetchScreen(initialUrl, darkTheme) { enabled -> darkTheme = enabled; preferences.edit().putBoolean("dark_theme", enabled).apply() }
    }
}

@Composable private fun VidFetchScreen(initialUrl: String, darkTheme: Boolean, onDarkThemeChange: (Boolean) -> Unit) {
    val scope = rememberCoroutineScope(); val context = androidx.compose.ui.platform.LocalContext.current
    val extractor = remember { YtDlpRepositoryImpl(context.applicationContext) }; val media = remember { DownloadedMediaRepository(context.applicationContext) }; val notifier = remember { DownloadNotifier(context.applicationContext) }
    var url by remember { mutableStateOf(initialUrl) }; var info by remember { mutableStateOf<VideoInfo?>(null) }; var selected by remember { mutableStateOf<VideoQuality?>(null) }
    var loading by remember { mutableStateOf(false) }; var message by remember { mutableStateOf<String?>(null) }; var tab by remember { mutableIntStateOf(0) }; var downloads by remember { mutableStateOf(emptyList<DownloadedMedia>()) }
    LaunchedEffect(tab) { if (tab == 1) downloads = media.list() }
    Scaffold(bottomBar = { NavigationBar { listOf("Home", "Downloads", "Settings").forEachIndexed { index, label -> NavigationBarItem(selected = index == tab, onClick = { tab = index }, icon = {}, label = { Text(label) }) } } }) { padding ->
        when (tab) {
            0 -> HomeScreen(Modifier.padding(padding), url, { url = it }, {
                url = context.getSystemService(ClipboardManager::class.java)?.primaryClip?.getItemAt(0)?.coerceToText(context)?.toString().orEmpty()
            }, info, selected, loading, message, { selected = it }, {
                if (!url.startsWith("http://") && !url.startsWith("https://")) message = "Enter a valid http or https URL." else scope.launch {
                    loading = true; message = null; try { info = extractor.analyze(url); selected = qualities(info!!.formats).firstOrNull() } catch (error: Exception) {
                        if ("older than 90 days" in error.message.orEmpty()) { extractor.updateExtractor(); info = extractor.analyze(url); selected = qualities(info!!.formats).firstOrNull() } else message = friendlyError(error)
                    } finally { loading = false }
                }
            }) { video -> scope.launch {
                loading = true; message = null; val before = media.existingPaths()
                try { extractor.download(video.webpageUrl, selected?.height, File(media.outputDirectory(), "%(title)s.%(ext)s").absolutePath) { progress -> message = "Downloading… $progress%"; notifier.progress(video.title, progress) }; media.scanNewFiles(before); downloads = media.list(); notifier.complete(video.title); message = "Download complete in Downloads/VidFetch." }
                catch (error: Exception) { notifier.failed(video.title); message = friendlyError(error) } finally { loading = false }
            } }
            1 -> DownloadsScreen(Modifier.padding(padding), downloads, { downloads = media.list() }, media::open, media::share, { item -> media.delete(item); downloads = media.list() }, { item, name -> media.rename(item, name); downloads = media.list() })
            else -> SettingsScreen(Modifier.padding(padding), darkTheme, onDarkThemeChange, loading, { scope.launch { loading = true; message = null; try { message = "Extractor update: ${extractor.updateExtractor()}" } catch (error: Exception) { message = "Could not update the extractor: ${error.message ?: "unknown error"}" } finally { loading = false } } }, message)
        }
    }
}

@Composable private fun HomeScreen(modifier: Modifier, url: String, onUrlChange: (String) -> Unit, onPaste: () -> Unit, info: VideoInfo?, selected: VideoQuality?, loading: Boolean, message: String?, onSelect: (VideoQuality) -> Unit, onAnalyze: () -> Unit, onDownload: (VideoInfo) -> Unit) {
    Column(modifier.padding(20.dp).fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text("VidFetch", style = MaterialTheme.typography.headlineMedium)
        OutlinedTextField(value = url, onValueChange = onUrlChange, label = { Text("Paste video URL") }, modifier = Modifier.fillMaxWidth(), singleLine = true, trailingIcon = { if (url.isNotEmpty()) IconButton(onClick = { onUrlChange("") }) { Icon(Icons.Default.Clear, contentDescription = "Clear link") } })
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) { OutlinedButton(onClick = onPaste) { Text("Paste") }; Button(enabled = !loading, onClick = onAnalyze) { Text("Analyze") } }
        if (loading) { LinearProgressIndicator(Modifier.fillMaxWidth()); Text("Working…") }
        message?.let { Text(it, color = if (it.startsWith("Download complete") || it.startsWith("Extractor update")) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error) }
        info?.let { video ->
            AsyncImage(model = video.thumbnailUrl, contentDescription = "Video thumbnail", modifier = Modifier.fillMaxWidth().height(190.dp))
            Text(video.title, style = MaterialTheme.typography.titleLarge); Text(listOfNotNull(video.uploader, formatDuration(video.durationSeconds)).joinToString(" · "))
            Text("Quality", style = MaterialTheme.typography.titleMedium)
            qualities(video.formats).forEach { quality -> Row(Modifier.fillMaxWidth().selectable(selected = selected == quality, onClick = { onSelect(quality) }).padding(vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) { RadioButton(selected = selected == quality, onClick = null); Column(Modifier.padding(start = 12.dp)) { Text(quality.label); Text(formatBytes(quality.estimatedBytes), style = MaterialTheme.typography.bodySmall) } } }
            Button(enabled = !loading, onClick = { onDownload(video) }, modifier = Modifier.fillMaxWidth()) { Text("Download video") }
        }
    }
}

@Composable private fun DownloadsScreen(modifier: Modifier, downloads: List<DownloadedMedia>, refresh: () -> Unit, open: (DownloadedMedia) -> Unit, share: (DownloadedMedia) -> Unit, delete: (DownloadedMedia) -> Unit, rename: (DownloadedMedia, String) -> Unit) {
    var menuItem by remember { mutableStateOf<DownloadedMedia?>(null) }
    var renameItem by remember { mutableStateOf<DownloadedMedia?>(null) }
    var renameText by remember { mutableStateOf("") }
    Column(modifier.padding(20.dp).fillMaxSize(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) { Text("Downloads", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.weight(1f)); TextButton(onClick = refresh) { Text("Refresh") } }
        if (downloads.isEmpty()) Text("No VidFetch downloads found in Downloads/VidFetch. Tap Refresh after a download.")
        downloads.forEach { item ->
            Card(Modifier.fillMaxWidth().selectable(selected = false, onClick = { open(item) })) {
                Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    AsyncImage(model = item.file, contentDescription = "Thumbnail for ${item.title}", modifier = Modifier.size(width = 112.dp, height = 64.dp))
                    Column(Modifier.padding(start = 12.dp).weight(1f)) { Text(item.title, style = MaterialTheme.typography.titleMedium); Text(item.size, style = MaterialTheme.typography.bodySmall) }
                    Box { IconButton(onClick = { menuItem = item }) { Icon(Icons.Default.MoreVert, contentDescription = "More actions") }
                        DropdownMenu(expanded = menuItem == item, onDismissRequest = { menuItem = null }) {
                            DropdownMenuItem(text = { Text("Rename") }, onClick = { renameText = item.file.nameWithoutExtension; renameItem = item; menuItem = null })
                            DropdownMenuItem(text = { Text("Share") }, onClick = { share(item); menuItem = null })
                            DropdownMenuItem(text = { Text("Delete") }, onClick = { delete(item); menuItem = null })
                        }
                    }
                }
            }
        }
    }
    renameItem?.let { item -> AlertDialog(onDismissRequest = { renameItem = null }, title = { Text("Rename video") }, text = { OutlinedTextField(value = renameText, onValueChange = { renameText = it }, singleLine = true, label = { Text("File name") }) }, confirmButton = { TextButton(onClick = { rename(item, renameText); renameItem = null }) { Text("Save") } }, dismissButton = { TextButton(onClick = { renameItem = null }) { Text("Cancel") } }) }
}

@Composable private fun SettingsScreen(modifier: Modifier, darkTheme: Boolean, onDarkThemeChange: (Boolean) -> Unit, loading: Boolean, onUpdate: () -> Unit, message: String?) {
    Column(modifier.padding(20.dp).fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("Settings", style = MaterialTheme.typography.headlineMedium)
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) { Column(Modifier.weight(1f)) { Text("Dark theme"); Text("Use a dark appearance", style = MaterialTheme.typography.bodySmall) }; Switch(checked = darkTheme, onCheckedChange = onDarkThemeChange) }
        HorizontalDivider(); Text("Extractor", style = MaterialTheme.typography.titleMedium); Text("Check for a newer yt-dlp release when websites change. Updating does not bypass website access controls.")
        OutlinedButton(enabled = !loading, onClick = onUpdate) { Text("Update extractor") }
        message?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        HorizontalDivider(); Text("Downloads are saved in Downloads/VidFetch."); Text("Download content only when you have permission to do so and in accordance with the applicable website's terms and local law.")
    }
}

private fun friendlyError(error: Exception): String {
    val detail = error.message.orEmpty()
    return when {
        "HTTP Error 403" in detail || "Forbidden" in detail -> "This website rejected the request (HTTP 403). Update the extractor in Settings; if it continues, the site may require your authorized browser cookies or disallow this download."
        "older than 90 days" in detail -> "The bundled extractor is outdated. Open Settings and choose Update extractor, then try again."
        else -> "Could not complete this request: ${detail.ifBlank { "extractor error" }}"
    }
}
