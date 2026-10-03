package com.vidfetch.app

import android.Manifest
import android.content.ActivityNotFoundException
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Videocam
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import coil.compose.SubcomposeAsyncImage
import coil.request.ImageRequest
import coil.decode.VideoFrameDecoder
import coil.request.videoFrameMillis
import com.vidfetch.app.data.storage.DownloadedMedia
import com.vidfetch.app.domain.VideoInfo
import com.vidfetch.app.domain.VideoQuality
import com.vidfetch.app.domain.formatDuration
import com.vidfetch.app.domain.formatBytes
import com.vidfetch.app.domain.qualities
import com.vidfetch.app.service.DownloadProgress
import com.vidfetch.app.service.DownloadService
import com.vidfetch.app.service.DownloadState
import java.util.regex.Pattern

class MainActivity : ComponentActivity() {
    private data class PendingDownload(val url: String, val title: String, val height: Int?)
    private var pendingDownload: PendingDownload? = null
    private val sharedLink = mutableStateOf("")
    private val storagePermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        val pending = pendingDownload
        pendingDownload = null
        if (granted && pending != null) startDownload(pending)
        else if (!granted) Toast.makeText(this, "Storage access is needed to save videos on this Android version.", Toast.LENGTH_LONG).show()
    }
    private val notificationPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        sharedLink.value = sharedUrl(intent)
        setContent { VidFetchApp(sharedLink.value, ::beginDownload) }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        sharedLink.value = sharedUrl(intent)
    }

    private fun beginDownload(video: VideoInfo, height: Int?) {
        if (DownloadState.progress.value.active) return
        val pending = PendingDownload(video.webpageUrl, video.title, height)
        if (Build.VERSION.SDK_INT <= 28 && ContextCompat.checkSelfPermission(this, Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
            pendingDownload = pending
            storagePermission.launch(Manifest.permission.WRITE_EXTERNAL_STORAGE)
        } else startDownload(pending)
    }

    private fun startDownload(download: PendingDownload) {
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        val intent = Intent(this, DownloadService::class.java)
            .putExtra(DownloadService.EXTRA_URL, download.url)
            .putExtra(DownloadService.EXTRA_TITLE, download.title)
            .putExtra(DownloadService.EXTRA_HEIGHT, download.height ?: 0)
        try {
            ContextCompat.startForegroundService(this, intent)
        } catch (error: Exception) {
            Toast.makeText(this, error.message ?: "Could not start the download.", Toast.LENGTH_LONG).show()
        }
    }

    private fun sharedUrl(intent: Intent?): String {
        if (intent?.action != Intent.ACTION_SEND) return ""
        val matcher = URL.matcher(intent.getStringExtra(Intent.EXTRA_TEXT).orEmpty())
        return if (matcher.find()) matcher.group() else ""
    }

    companion object { private val URL = Pattern.compile("https?://[^\\s]+") }
}

@Composable private fun VidFetchApp(sharedUrl: String, startDownload: (VideoInfo, Int?) -> Unit) {
    val context = LocalContext.current
    val preferences = remember { context.getSharedPreferences("vidfetch_settings", 0) }
    val systemDark = isSystemInDarkTheme()
    var darkTheme by rememberSaveable { mutableStateOf(preferences.getBoolean("dark_theme", systemDark)) }
    val colors = when {
        Build.VERSION.SDK_INT >= 31 && darkTheme -> dynamicDarkColorScheme(context)
        Build.VERSION.SDK_INT >= 31 -> dynamicLightColorScheme(context)
        darkTheme -> darkColorScheme()
        else -> lightColorScheme()
    }
    MaterialTheme(colorScheme = colors) {
        val model: VidFetchViewModel = viewModel()
        val state by model.state.collectAsState()
        val progress by DownloadState.progress.collectAsState()
        var tab by rememberSaveable { mutableIntStateOf(0) }
        val legacyReadPermission = androidx.activity.compose.rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { model.refreshDownloads() }
        LaunchedEffect(sharedUrl) { model.acceptSharedUrl(sharedUrl) }
        Scaffold(bottomBar = {
            NavigationBar {
                listOf(Triple("Home", Icons.Default.Home, 0), Triple("Downloads", Icons.Default.Download, 1), Triple("Settings", Icons.Default.Settings, 2)).forEach { (label, icon, index) ->
                    NavigationBarItem(selected = tab == index, onClick = {
                        tab = index
                        if (index == 1) {
                            if (Build.VERSION.SDK_INT <= 28 && ContextCompat.checkSelfPermission(context, Manifest.permission.READ_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
                                legacyReadPermission.launch(Manifest.permission.READ_EXTERNAL_STORAGE)
                            } else model.refreshDownloads()
                        }
                    }, icon = { Icon(icon, contentDescription = null) }, label = { Text(label) })
                }
            }
        }) { padding ->
            when (tab) {
                0 -> HomeScreen(Modifier.padding(padding), state, progress, model::setUrl, model::setSelected, model::analyze, startDownload)
                1 -> DownloadsScreen(Modifier.padding(padding), state, model::refreshDownloads, model::open, model::share, model::delete, model::rename)
                else -> SettingsScreen(Modifier.padding(padding), darkTheme, { darkTheme = it; preferences.edit().putBoolean("dark_theme", it).apply() }, state, progress, model::updateExtractor)
            }
        }
    }
}

@Composable private fun HomeScreen(
    modifier: Modifier,
    state: VidFetchUiState,
    progress: DownloadProgress,
    setUrl: (String) -> Unit,
    select: (VideoQuality) -> Unit,
    analyze: () -> Unit,
    download: (VideoInfo, Int?) -> Unit,
) {
    val context = LocalContext.current
    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Column {
            Text("VidFetch", style = MaterialTheme.typography.headlineLarge)
            Text("Save videos to your device", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        OutlinedTextField(
            value = state.url,
            onValueChange = setUrl,
            label = { Text("Video link") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            trailingIcon = { if (state.url.isNotEmpty()) IconButton(onClick = { setUrl("") }) { Icon(Icons.Default.Clear, contentDescription = "Clear link") } },
        )
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedButton(onClick = {
                val clip = context.getSystemService(ClipboardManager::class.java)?.primaryClip
                setUrl(clip?.getItemAt(0)?.coerceToText(context)?.toString().orEmpty())
            }) { Text("Paste") }
            Button(onClick = analyze, enabled = !state.analyzing && !progress.active && !state.updating) { Text("Analyze") }
        }
        if (state.analyzing) { LinearProgressIndicator(Modifier.fillMaxWidth()); Text("Checking available formats…") }
        state.message?.let { MessageCard(it) }
        if (progress.active) {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Downloading ${progress.title}", style = MaterialTheme.typography.titleMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    LinearProgressIndicator(progress = { progress.percent / 100f }, modifier = Modifier.fillMaxWidth())
                    Text("${progress.percent}% · You can leave this screen while it downloads.", style = MaterialTheme.typography.bodySmall)
                }
            }
        } else progress.message?.let { MessageCard(it) }
        state.info?.let { video ->
            Card(Modifier.fillMaxWidth()) {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    AsyncImage(model = video.thumbnailUrl, contentDescription = "Preview for ${video.title}", contentScale = ContentScale.Crop, modifier = Modifier.fillMaxWidth().height(190.dp))
                    Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(video.title, style = MaterialTheme.typography.titleLarge)
                        Text(listOfNotNull(video.uploader, formatDuration(video.durationSeconds)).joinToString(" · "), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Text("Quality", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(horizontal = 16.dp))
                    qualities(video.formats).forEach { quality ->
                        Row(Modifier.fillMaxWidth().selectable(selected = state.selected == quality, onClick = { select(quality) }).padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                            RadioButton(selected = state.selected == quality, onClick = null)
                            Column(Modifier.padding(start = 12.dp)) {
                                Text(quality.label)
                                if (quality.estimatedBytes != null) Text(formatBytes(quality.estimatedBytes), style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                    Button(onClick = { download(video, state.selected?.height) }, enabled = !progress.active && !state.analyzing && !state.updating, modifier = Modifier.fillMaxWidth().padding(16.dp)) {
                        Icon(Icons.Default.Download, contentDescription = null)
                        Spacer(Modifier.size(8.dp))
                        Text("Download video")
                    }
                }
            }
        }
    }
}

@Composable private fun DownloadsScreen(
    modifier: Modifier,
    state: VidFetchUiState,
    refresh: () -> Unit,
    open: (DownloadedMedia) -> Unit,
    share: (DownloadedMedia) -> Unit,
    delete: (DownloadedMedia) -> Unit,
    rename: (DownloadedMedia, String) -> Unit,
) {
    var menuId by remember { mutableStateOf<String?>(null) }
    var renameItem by remember { mutableStateOf<DownloadedMedia?>(null) }
    var deleteItem by remember { mutableStateOf<DownloadedMedia?>(null) }
    var renameText by remember { mutableStateOf("") }
    LazyColumn(modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Downloads", style = MaterialTheme.typography.headlineLarge)
                    Text("Saved in Downloads/VidFetch", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                TextButton(onClick = refresh, enabled = !state.downloadsLoading) { Text("Refresh") }
            }
        }
        if (state.downloadsLoading) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
        state.downloadsMessage?.let { message -> item { MessageCard(message) } }
        if (!state.downloadsLoading && state.downloads.isEmpty()) item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Icon(Icons.Default.Videocam, contentDescription = null, modifier = Modifier.size(40.dp))
                    Text("No downloads yet", style = MaterialTheme.typography.titleMedium)
                    Text("Your saved videos will appear here.")
                }
            }
        }
        items(state.downloads, key = { it.id }) { item ->
            Card(Modifier.fillMaxWidth().clickable { open(item) }) {
                Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    VideoThumbnail(item)
                    Column(Modifier.padding(start = 12.dp).weight(1f)) {
                        Text(item.title, style = MaterialTheme.typography.titleSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        Text(item.size, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Box {
                        IconButton(onClick = { menuId = item.id }) { Icon(Icons.Default.MoreVert, contentDescription = "Actions for ${item.title}") }
                        DropdownMenu(expanded = menuId == item.id, onDismissRequest = { menuId = null }) {
                            DropdownMenuItem(text = { Text("Open") }, onClick = { menuId = null; open(item) })
                            DropdownMenuItem(text = { Text("Rename") }, onClick = { menuId = null; renameText = item.title.substringBeforeLast('.'); renameItem = item })
                            DropdownMenuItem(text = { Text("Share") }, onClick = { menuId = null; share(item) })
                            DropdownMenuItem(text = { Text("Delete") }, onClick = { menuId = null; deleteItem = item })
                        }
                    }
                }
            }
        }
    }
    renameItem?.let { item ->
        AlertDialog(onDismissRequest = { renameItem = null }, title = { Text("Rename video") }, text = {
            OutlinedTextField(value = renameText, onValueChange = { renameText = it }, label = { Text("File name") }, singleLine = true)
        }, confirmButton = { TextButton(onClick = { rename(item, renameText); renameItem = null }, enabled = renameText.isNotBlank()) { Text("Save") } }, dismissButton = { TextButton(onClick = { renameItem = null }) { Text("Cancel") } })
    }
    deleteItem?.let { item ->
        AlertDialog(onDismissRequest = { deleteItem = null }, title = { Text("Delete video?") }, text = { Text(item.title) }, confirmButton = {
            TextButton(onClick = { delete(item); deleteItem = null }) { Text("Delete") }
        }, dismissButton = { TextButton(onClick = { deleteItem = null }) { Text("Cancel") } })
    }
}

@Composable private fun VideoThumbnail(item: DownloadedMedia) {
    val context = LocalContext.current
    val request = remember(item.id) {
        ImageRequest.Builder(context)
            .data(item.uri)
            .videoFrameMillis(1000)
            .decoderFactory { result, options, _ -> VideoFrameDecoder(result.source, options) }
            .build()
    }
    SubcomposeAsyncImage(
        model = request,
        contentDescription = "Thumbnail for ${item.title}",
        contentScale = ContentScale.Crop,
        modifier = Modifier.size(width = 112.dp, height = 68.dp).clip(RoundedCornerShape(10.dp)),
        loading = { ThumbnailFallback(true) },
        error = { ThumbnailFallback(false) },
    )
}

@Composable private fun ThumbnailFallback(loading: Boolean) {
    Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.surfaceVariant), contentAlignment = Alignment.Center) {
        if (loading) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
        else Icon(Icons.Default.PlayArrow, contentDescription = null)
    }
}

@Composable private fun SettingsScreen(
    modifier: Modifier,
    darkTheme: Boolean,
    onDarkThemeChange: (Boolean) -> Unit,
    state: VidFetchUiState,
    progress: DownloadProgress,
    update: () -> Unit,
) {
    val context = LocalContext.current
    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(20.dp)) {
        Text("Settings", style = MaterialTheme.typography.headlineLarge)
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) { Text("Dark theme", style = MaterialTheme.typography.titleMedium); Text("Use a dark appearance", style = MaterialTheme.typography.bodySmall) }
            Switch(checked = darkTheme, onCheckedChange = onDarkThemeChange)
        }
        HorizontalDivider()
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Extractor", style = MaterialTheme.typography.titleMedium)
            Text("Update site compatibility when a video stops working.")
            OutlinedButton(onClick = update, enabled = !state.updating && !state.analyzing && !progress.active) { Text(if (state.updating) "Updating…" else "Update extractor") }
            if (state.updating) LinearProgressIndicator(Modifier.fillMaxWidth())
            state.message?.let { MessageCard(it) }
        }
        HorizontalDivider()
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Storage", style = MaterialTheme.typography.titleMedium)
            Text("Completed videos are saved in Downloads/VidFetch. Downloads in progress use temporary app storage.")
        }
        HorizontalDivider()
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("About", style = MaterialTheme.typography.titleMedium)
            AssistChip(onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://github.com/HannanSeyfi"))) }, label = { Text("Powered by Hannan") })
            Text("Download content only when you have permission and in accordance with the website's terms and local law.", style = MaterialTheme.typography.bodySmall)
        }
        HorizontalDivider()
        Row(Modifier.fillMaxWidth().clickable { openTelegramContact(context) }.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Contact me", style = MaterialTheme.typography.titleMedium)
                Text("Open Telegram", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Icon(Icons.Default.OpenInNew, contentDescription = null)
        }
    }
}

private fun openTelegramContact(context: Context) {
    try {
        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("tg://resolve?domain=Hannanlive&profile")))
    } catch (_: ActivityNotFoundException) {
        try {
            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://t.me/Hannanlive?profile")))
        } catch (_: ActivityNotFoundException) {
            Toast.makeText(context, "Telegram is unavailable on this device.", Toast.LENGTH_SHORT).show()
        }
    }
}

@Composable private fun MessageCard(message: String) {
    Surface(color = MaterialTheme.colorScheme.secondaryContainer, shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth()) {
        Text(message, modifier = Modifier.padding(12.dp), color = MaterialTheme.colorScheme.onSecondaryContainer)
    }
}
