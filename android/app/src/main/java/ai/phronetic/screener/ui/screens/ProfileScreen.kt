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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ai.phronetic.screener.Config
import ai.phronetic.screener.ui.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProfileScreen() {
    val context = androidx.compose.ui.platform.LocalContext.current
    val scope = rememberCoroutineScope()
    val token = remember { Config.getAuthToken(context) }
    val serverUrl = remember { Config.SERVER_URL }

    var isLoading by remember { mutableStateOf(true) }
    var isSaving by remember { mutableStateOf(false) }
    var saveMsg by remember { mutableStateOf<String?>(null) }

    // Profile fields
    var name by remember { mutableStateOf("") }
    var email by remember { mutableStateOf("") }
    var greeting by remember { mutableStateOf("") }
    var screeningMode by remember { mutableStateOf("ai") }

    // Read-only from backend
    var phone by remember { mutableStateOf("") }
    var tier by remember { mutableStateOf("free") }
    var minutesUsed by remember { mutableFloatStateOf(0f) }
    var minutesLimit by remember { mutableIntStateOf(0) }
    var enabled by remember { mutableStateOf(true) }

    LaunchedEffect(Unit) {
        if (token.isBlank()) { isLoading = false; return@LaunchedEffect }
        withContext(Dispatchers.IO) {
            try {
                val client = OkHttpClient()
                val resp = client.newCall(
                    Request.Builder()
                        .url("$serverUrl/v1/auth/me?token=$token")
                        .build()
                ).execute()
                if (resp.isSuccessful) {
                    val obj = JSONObject(resp.body?.string() ?: "")
                    withContext(Dispatchers.Main) {
                        name = obj.optString("name", "")
                        email = obj.optString("email", "")
                        greeting = obj.optString("greeting", "")
                        screeningMode = obj.optString("screening_mode", "ai")
                        phone = obj.optString("phone_number", "")
                        tier = obj.optString("pricing_tier", "free")
                        minutesUsed = obj.optDouble("monthly_minutes_used", 0.0).toFloat()
                        minutesLimit = obj.optInt("monthly_minutes_limit", 0)
                        enabled = obj.optBoolean("enabled", true)
                        isLoading = false
                    }
                } else {
                    withContext(Dispatchers.Main) { isLoading = false }
                }
            } catch (_: Exception) {
                withContext(Dispatchers.Main) { isLoading = false }
            }
        }
    }

    fun saveChanges() {
        if (token.isBlank()) return
        isSaving = true; saveMsg = null
        scope.launch(Dispatchers.IO) {
            try {
                val client = OkHttpClient()
                val json = JSONObject().apply {
                    if (name.isNotBlank()) put("name", name)
                    if (email.isNotBlank()) put("email", email)
                    if (greeting.isNotBlank()) put("greeting", greeting)
                    put("screening_mode", screeningMode)
                }
                val body = json.toString().toRequestBody("application/json".toMediaType())
                val resp = client.newCall(
                    Request.Builder()
                        .url("$serverUrl/v1/auth/me?token=$token")
                        .patch(body)
                        .build()
                ).execute()
                withContext(Dispatchers.Main) {
                    isSaving = false
                    saveMsg = if (resp.isSuccessful) "Saved" else "Failed to save"
                }
            } catch (_: Exception) {
                withContext(Dispatchers.Main) { isSaving = false; saveMsg = "Network error" }
            }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(BgDark)
            .verticalScroll(rememberScrollState())
    ) {
        TopAppBar(
            title = { Text("Profile & Controls", color = TextPrimary) },
            colors = TopAppBarDefaults.topAppBarColors(containerColor = Surface1)
        )

        if (isLoading) {
            Box(modifier = Modifier.fillMaxWidth().height(200.dp), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = VioletLight)
            }
        } else {
            Column(modifier = Modifier.padding(16.dp)) {

                // ── Usage ───────────────────────────────────────────────────────
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(16.dp),
                    color = Surface1,
                    border = BorderStroke(1.dp, Border)
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Default.Info, contentDescription = null, tint = Cyan, modifier = Modifier.size(22.dp))
                            Spacer(Modifier.width(12.dp))
                            Text("Usage", fontWeight = FontWeight.SemiBold, color = TextPrimary, fontSize = 15.sp)
                        }
                        Spacer(Modifier.height(12.dp))
                        val pct = if (minutesLimit > 0) (minutesUsed / minutesLimit).coerceIn(0f, 1f) else 0f
                        val barColor = when {
                            pct > 0.9f -> Rose
                            pct > 0.7f -> Amber
                            else -> Emerald
                        }
                        Box(
                            modifier = Modifier.fillMaxWidth().height(8.dp).clip(RoundedCornerShape(4.dp)).background(Surface2)
                        ) {
                            Box(modifier = Modifier.fillMaxHeight().fillMaxWidth(pct).clip(RoundedCornerShape(4.dp)).background(barColor))
                        }
                        Spacer(Modifier.height(8.dp))
                        Text(
                            "${String.format("%.1f", minutesUsed)} / ${if (minutesLimit > 0) "$minutesLimit min" else "Unlimited"} this month",
                            fontSize = 13.sp, color = TextMuted
                        )
                        Spacer(Modifier.height(4.dp))
                        Text(
                            "Tier: ${tier.replaceFirstChar { it.uppercase() }}",
                            fontSize = 13.sp, color = Cyan, fontWeight = FontWeight.Medium
                        )
                    }
                }
                Spacer(Modifier.height(20.dp))

                // ── Profile Fields ──────────────────────────────────────────────
                Text("Profile", fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = TextPrimary)
                Spacer(Modifier.height(12.dp))

                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text("Name", color = TextMuted) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(12.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = Violet,
                        unfocusedBorderColor = Border,
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary
                    ),
                )
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = email,
                    onValueChange = { email = it },
                    label = { Text("Email", color = TextMuted) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(12.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = Violet,
                        unfocusedBorderColor = Border,
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary
                    ),
                )
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = greeting,
                    onValueChange = { greeting = it },
                    label = { Text("AI Greeting", color = TextMuted) },
                    placeholder = { Text("Hello, this is Pickr...", color = TextMuted.copy(alpha = 0.5f)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(12.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = Violet,
                        unfocusedBorderColor = Border,
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary
                    ),
                )
                Spacer(Modifier.height(20.dp))

                // ── Screening Mode ──────────────────────────────────────────────
                Text("Screening Mode", fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = TextPrimary)
                Spacer(Modifier.height(12.dp))

                val modes = listOf(
                    Triple("ai", "AI Screen", "Full AI conversation with transcript and controls") to Violet,
                    Triple("silent", "Silent Log", "Let all calls through but log them silently") to Cyan,
                    Triple("block_all", "Block All", "Block every unknown caller automatically") to Rose,
                    Triple("allow_all", "Allow All", "Allow every call through without screening") to Emerald,
                )

                modes.forEach { (data, color) ->
                    val (key, label, desc) = data
                    val selected = screeningMode == key
                    Surface(
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp),
                        color = if (selected) color.copy(alpha = 0.08f) else Surface1,
                        border = BorderStroke(1.dp, if (selected) color.copy(alpha = 0.4f) else Border),
                        onClick = { screeningMode = key }
                    ) {
                        Row(
                            modifier = Modifier.padding(14.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(12.dp)
                        ) {
                            Box(
                                modifier = Modifier.size(20.dp).clip(CircleShape)
                                    .background(if (selected) color else Surface2)
                                    .border(2.dp, if (selected) color else Border, CircleShape),
                                contentAlignment = Alignment.Center
                            ) {
                                if (selected) Box(modifier = Modifier.size(8.dp).clip(CircleShape).background(Color.White))
                            }
                            Column(modifier = Modifier.weight(1f)) {
                                Text(label, fontWeight = FontWeight.SemiBold, color = TextPrimary, fontSize = 14.sp)
                                Text(desc, fontSize = 12.sp, color = TextMuted)
                            }
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                }

                Spacer(Modifier.height(20.dp))
                Button(
                    onClick = { saveChanges() },
                    enabled = !isSaving,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Violet)
                ) {
                    if (isSaving) {
                        CircularProgressIndicator(modifier = Modifier.size(18.dp), color = Color.White, strokeWidth = 2.dp)
                    } else {
                        Text("Save Changes", color = Color.White)
                    }
                }
                if (saveMsg != null) {
                    Spacer(Modifier.height(8.dp))
                    Text(saveMsg!!, color = if (saveMsg == "Saved") Emerald else Rose, fontSize = 13.sp, textAlign = androidx.compose.ui.text.style.TextAlign.Center, modifier = Modifier.fillMaxWidth())
                }

                Spacer(Modifier.height(24.dp))

                // ── About ───────────────────────────────────────────────────────
                Text("About", fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = TextPrimary)
                Spacer(Modifier.height(12.dp))
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(12.dp),
                    color = Surface1,
                    border = BorderStroke(1.dp, Border)
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text("Pickr — AI Call Screener", fontWeight = FontWeight.SemiBold, color = TextPrimary, fontSize = 15.sp)
                        Spacer(Modifier.height(4.dp))
                        Text("Version 1.0", fontSize = 13.sp, color = TextMuted)
                        Text("Powered by Phronetic AI", fontSize = 13.sp, color = TextMuted)
                    }
                }
            }
        }
    }
}
