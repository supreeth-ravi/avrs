package ai.phronetic.screener.ui.screens

import androidx.compose.animation.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import ai.phronetic.screener.Config
import ai.phronetic.screener.data.db.ScreenedCall
import ai.phronetic.screener.ui.*
import ai.phronetic.screener.viewmodel.DashboardStats
import ai.phronetic.screener.viewmodel.DashboardViewModel
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun DashboardScreen(vm: DashboardViewModel = viewModel()) {
    val context = androidx.compose.ui.platform.LocalContext.current
    var enabled by remember { mutableStateOf(Config.isEnabled(context)) }
    val stats by vm.stats.collectAsStateWithLifecycle()
    val recentCalls by vm.recentCalls.collectAsStateWithLifecycle()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(BgDark)
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
    ) {
        // Header
        Text("Dashboard", fontSize = 28.sp, fontWeight = FontWeight.Bold, color = TextPrimary)
        Spacer(Modifier.height(4.dp))
        Text("AI call screener overview", fontSize = 14.sp, color = TextMuted)
        Spacer(Modifier.height(24.dp))

        // Enable/Disable toggle card
        EnableToggleCard(
            enabled = enabled,
            onToggle = {
                enabled = it
                Config.setEnabled(context, it)
            }
        )

        Spacer(Modifier.height(20.dp))

        // Stats grid
        StatsGrid(stats)

        Spacer(Modifier.height(24.dp))

        // Recent calls
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text("Recent Calls", fontSize = 18.sp, fontWeight = FontWeight.SemiBold, color = TextPrimary)
            if (recentCalls.isNotEmpty()) {
                TextButton(onClick = { vm.clearHistory() }) {
                    Text("Clear", color = Rose, fontSize = 13.sp)
                }
            }
        }
        Spacer(Modifier.height(12.dp))

        if (recentCalls.isEmpty()) {
            EmptyState(message = "No screened calls yet")
        } else {
            recentCalls.take(5).forEach { call ->
                CallListItem(call = call)
                Spacer(Modifier.height(8.dp))
            }
        }
    }
}

@Composable
fun EnableToggleCard(enabled: Boolean, onToggle: (Boolean) -> Unit) {
    val bgColor = if (enabled) Emerald.copy(alpha = 0.08f) else Surface1
    val borderColor = if (enabled) Emerald.copy(alpha = 0.4f) else Border
    val dotColor = if (enabled) Emerald else Amber

    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        color = bgColor,
        border = BorderStroke(1.dp, borderColor),
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier
                    .size(12.dp)
                    .clip(CircleShape)
                    .background(dotColor)
            )
            Spacer(Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    if (enabled) "Screener is active" else "Screener is paused",
                    fontWeight = FontWeight.SemiBold,
                    color = TextPrimary,
                    fontSize = 15.sp
                )
                Text(
                    if (enabled) "Unknown calls will be screened by AI" else "All calls will ring normally",
                    fontSize = 13.sp,
                    color = TextMuted
                )
            }
            Switch(
                checked = enabled,
                onCheckedChange = onToggle,
                colors = SwitchDefaults.colors(
                    checkedThumbColor = Emerald,
                    checkedTrackColor = Emerald.copy(alpha = 0.4f),
                    uncheckedThumbColor = TextMuted,
                    uncheckedTrackColor = Surface2
                )
            )
        }
    }
}

@Composable
fun StatsGrid(stats: ai.phronetic.screener.viewmodel.DashboardStats) {
    val items = listOf(
        Triple("Calls", stats.totalCalls.toString(), Cyan),
        Triple("Spam", stats.spamBlocked.toString(), Rose),
        Triple("Allowed", stats.whitelisted.toString(), Emerald),
        Triple("Blocked", stats.blocklisted.toString(), Amber),
    )

    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        items.forEach { (label, value, color) ->
            Surface(
                modifier = Modifier.weight(1f),
                shape = RoundedCornerShape(16.dp),
                color = Surface1,
                border = BorderStroke(1.dp, Border)
            ) {
                Column(
                    modifier = Modifier.padding(vertical = 16.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Text(value, fontSize = 22.sp, fontWeight = FontWeight.Bold, color = color)
                    Spacer(Modifier.height(4.dp))
                    Text(label, fontSize = 12.sp, color = TextMuted)
                }
            }
        }
    }
}

@Composable
fun CallListItem(call: ScreenedCall) {
    val intentColor = when (call.intent) {
        "spam" -> Rose
        "delivery" -> Cyan
        "work" -> Violet
        "personal" -> Emerald
        "emergency" -> Amber
        else -> TextMuted
    }
    val sdf = SimpleDateFormat("dd MMM, hh:mm a", Locale.getDefault())
    val timeStr = sdf.format(Date(call.timestamp))

    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        color = Surface1,
        border = BorderStroke(1.dp, Border)
    ) {
        Row(
            modifier = Modifier.padding(14.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier
                    .size(44.dp)
                    .clip(CircleShape)
                    .background(Surface2),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    call.callerName?.firstOrNull()?.toString() ?: "?",
                    fontSize = 18.sp,
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
    }
}
