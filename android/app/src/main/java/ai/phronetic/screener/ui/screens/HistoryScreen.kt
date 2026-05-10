package ai.phronetic.screener.ui.screens

import androidx.compose.animation.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import ai.phronetic.screener.data.db.ScreenedCall
import ai.phronetic.screener.ui.*
import ai.phronetic.screener.viewmodel.HistoryViewModel
import java.text.SimpleDateFormat
import java.util.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HistoryScreen(vm: HistoryViewModel = viewModel()) {
    val calls by vm.calls.collectAsStateWithLifecycle()
    var selectedTab by remember { mutableStateOf(0) }
    val tabs = listOf("All", "Spam", "Blocked")

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(BgDark)
    ) {
        TopAppBar(
            title = { Text("Call History", color = TextPrimary) },
            colors = TopAppBarDefaults.topAppBarColors(containerColor = Surface1),
            actions = {
                if (calls.isNotEmpty()) {
                    IconButton(onClick = { vm.clearAll() }) {
                        Icon(Icons.Default.Delete, contentDescription = "Clear all", tint = Rose)
                    }
                }
            }
        )

        TabRow(
            selectedTabIndex = selectedTab,
            containerColor = Surface1,
            contentColor = VioletLight,
            divider = { Divider(color = Border) }
        ) {
            tabs.forEachIndexed { index, title ->
                Tab(
                    selected = selectedTab == index,
                    onClick = { selectedTab = index },
                    text = { Text(title, fontSize = 14.sp) }
                )
            }
        }

        val filteredCalls = when (selectedTab) {
            1 -> calls.filter { it.isSpam }
            2 -> calls.filter { it.isBlocked }
            else -> calls
        }

        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp)
        ) {
            if (filteredCalls.isEmpty()) {
                EmptyState(message = "No calls in this category")
            } else {
                LazyColumn(
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    items(filteredCalls.size, key = { filteredCalls[it].id }) { index ->
                        val call = filteredCalls[index]
                        HistoryListItem(call = call, onDelete = { vm.deleteCall(call) })
                    }
                }
            }
        }
    }
}

@Composable
fun HistoryListItem(call: ScreenedCall, onDelete: () -> Unit) {
    val intentColor = when (call.intent) {
        "spam" -> Rose
        "delivery" -> Cyan
        "work" -> Violet
        "personal" -> Emerald
        "emergency" -> Amber
        else -> TextMuted
    }
    val sdf = SimpleDateFormat("dd MMM yyyy, hh:mm a", Locale.getDefault())
    val timeStr = sdf.format(Date(call.timestamp))

    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        color = Surface1,
        border = BorderStroke(1.dp, Border)
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .size(40.dp)
                        .clip(CircleShape)
                        .background(Surface2),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        call.callerName?.firstOrNull()?.toString() ?: "?",
                        fontSize = 16.sp,
                        fontWeight = FontWeight.Bold,
                        color = TextMuted
                    )
                }
                Spacer(Modifier.width(12.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(call.callerNumber, fontWeight = FontWeight.SemiBold, color = TextPrimary, fontSize = 15.sp)
                    Text(timeStr, fontSize = 12.sp, color = TextMuted)
                }
                Surface(
                    shape = RoundedCornerShape(20.dp),
                    color = intentColor.copy(alpha = 0.12f),
                    border = BorderStroke(1.dp, intentColor.copy(alpha = 0.35f))
                ) {
                    Text(
                        call.intent.replaceFirstChar { it.uppercase() },
                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
                        fontSize = 11.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = intentColor
                    )
                }
            }

            Spacer(Modifier.height(10.dp))

            val transcript = remember {
                try {
                    val json = org.json.JSONArray(call.transcriptJson)
                    val sb = StringBuilder()
                    for (i in 0 until minOf(json.length(), 3)) {
                        val obj = json.getJSONObject(i)
                        val speaker = obj.getString("speaker")
                        val text = obj.getString("text")
                        sb.append("$speaker: $text\n")
                    }
                    if (json.length() > 3) sb.append("...")
                    sb.toString().trim()
                } catch (_: Exception) {
                    call.transcriptJson
                }
            }

            if (transcript.isNotBlank()) {
                Text(
                    transcript,
                    fontSize = 13.sp,
                    color = TextMuted,
                    modifier = Modifier.padding(start = 4.dp)
                )
            }

            Spacer(Modifier.height(8.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End
            ) {
                TextButton(onClick = onDelete) {
                    Text("Delete", color = Rose, fontSize = 12.sp)
                }
            }
        }
    }
}
