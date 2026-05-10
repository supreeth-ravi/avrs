package ai.phronetic.screener.ui

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.Bundle
import android.view.MotionEvent
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Send
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.view.WindowCompat
import ai.phronetic.screener.Config
import ai.phronetic.screener.ScreenerService
import ai.phronetic.screener.ScreeningWebSocketService
import org.json.JSONObject

class ScreeningOverlayActivity : ComponentActivity() {

    private val transcriptLines = mutableStateListOf<TranscriptLine>()
    private var intentLabel     by mutableStateOf("")
    private var agentSpeaking   by mutableStateOf(false)
    private var callSid         by mutableStateOf("")
    private var isConnected     by mutableStateOf(false)

    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            val payload = intent.getStringExtra("payload") ?: return
            when (intent.action) {
                ScreeningWebSocketService.EVENT_CONNECTED -> isConnected = true
                ScreeningWebSocketService.EVENT_DISCONNECTED -> isConnected = false
                ScreeningWebSocketService.EVENT_CALL_STARTED -> {
                    val json = JSONObject(payload)
                    callSid = json.optString("call_sid", "")
                }
                ScreeningWebSocketService.EVENT_TRANSCRIPT -> {
                    val json = JSONObject(payload)
                    val text = json.getString("text")
                    val speaker = json.optString("speaker", "caller")
                    transcriptLines.add(TranscriptLine(if (speaker == "caller") "Caller" else speaker, text))
                    agentSpeaking = false
                }
                ScreeningWebSocketService.EVENT_AGENT_SPEAKING -> {
                    val json = JSONObject(payload)
                    val text = json.getString("text")
                    transcriptLines.add(TranscriptLine("AI", text))
                    agentSpeaking = true
                }
                ScreeningWebSocketService.EVENT_INTENT -> {
                    val json = JSONObject(payload)
                    intentLabel = json.getString("intent")
                }
                ScreeningWebSocketService.EVENT_CALL_END -> finish()
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        val callerNumber = intent.getStringExtra(ScreenerService.EXTRA_CALLER) ?: "Unknown"

        // Start WebSocket service
        ScreeningWebSocketService.start(this, callerNumber)

        // Register local broadcast receiver
        val filter = IntentFilter().apply {
            addAction(ScreeningWebSocketService.EVENT_CONNECTED)
            addAction(ScreeningWebSocketService.EVENT_DISCONNECTED)
            addAction(ScreeningWebSocketService.EVENT_CALL_STARTED)
            addAction(ScreeningWebSocketService.EVENT_TRANSCRIPT)
            addAction(ScreeningWebSocketService.EVENT_AGENT_SPEAKING)
            addAction(ScreeningWebSocketService.EVENT_INTENT)
            addAction(ScreeningWebSocketService.EVENT_CALL_END)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            registerReceiver(receiver, filter)
        }

        setContent {
            MaterialTheme(
                colorScheme = darkColorScheme(
                    background = BgDark,
                    surface = Surface1,
                    primary = Violet,
                    onBackground = TextPrimary,
                    onSurface = TextPrimary,
                )
            ) {
                ScreeningOverlay(
                    callerNumber  = callerNumber,
                    transcript    = transcriptLines,
                    intentLabel   = intentLabel,
                    agentSpeaking = agentSpeaking,
                    isConnected   = isConnected,
                    onJoin    = { sendAction("join") },
                    onBlock   = { sendAction("block") },
                    onMessage = { sendAction("message") },
                    onSendText = { text -> sendTypedMessage(text) }
                )
            }
        }
    }

    private fun sendAction(action: String) {
        ScreeningWebSocketService.sendAction(this, action, callSid)
        if (action != "message") finish()
    }

    private fun sendTypedMessage(text: String) {
        ScreeningWebSocketService.sendAction(this, "typed_message", callSid, text)
        transcriptLines.add(TranscriptLine("You", text))
    }

    override fun onDestroy() {
        unregisterReceiver(receiver)
        sendBroadcast(Intent(ScreeningWebSocketService.ACTION_DISCONNECT))
        super.onDestroy()
    }

    override fun dispatchGenericMotionEvent(ev: MotionEvent): Boolean {
        if (ev.action == MotionEvent.ACTION_HOVER_ENTER ||
            ev.action == MotionEvent.ACTION_HOVER_MOVE  ||
            ev.action == MotionEvent.ACTION_HOVER_EXIT) {
            return true
        }
        return super.dispatchGenericMotionEvent(ev)
    }
}

data class TranscriptLine(val speaker: String, val text: String)

// ── Main overlay ──────────────────────────────────────────────────────────────

@Composable
fun ScreeningOverlay(
    callerNumber: String,
    transcript: List<TranscriptLine>,
    intentLabel: String,
    agentSpeaking: Boolean,
    isConnected: Boolean,
    onJoin: () -> Unit,
    onBlock: () -> Unit,
    onMessage: () -> Unit,
    onSendText: (String) -> Unit,
) {
    val listState = rememberLazyListState()
    var typedText by remember { mutableStateOf("") }

    LaunchedEffect(transcript.size) {
        if (transcript.isNotEmpty()) listState.animateScrollToItem(transcript.size - 1)
    }

    Box(
        modifier         = Modifier
            .fillMaxSize()
            .background(Color(0xBB000000)),
        contentAlignment = Alignment.BottomCenter,
    ) {
        Spacer(Modifier.fillMaxSize())

        Surface(
            modifier = Modifier.fillMaxWidth(),
            shape    = RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp),
            color    = BgDark,
            border   = BorderStroke(1.dp, Border),
        ) {
            Column(
                modifier = Modifier
                    .padding(horizontal = 20.dp)
                    .padding(top = 20.dp)
                    .navigationBarsPadding()
                    .padding(bottom = 8.dp),
            ) {
                Box(
                    modifier = Modifier
                        .align(Alignment.CenterHorizontally)
                        .width(40.dp)
                        .height(4.dp)
                        .clip(CircleShape)
                        .background(Border)
                )
                Spacer(Modifier.height(16.dp))

                OverlayHeader(
                    callerNumber  = callerNumber,
                    intentLabel   = intentLabel,
                    agentSpeaking = agentSpeaking,
                    isConnected   = isConnected,
                )

                Spacer(Modifier.height(16.dp))
                Divider(color = Border, thickness = 1.dp)
                Spacer(Modifier.height(12.dp))

                LazyColumn(
                    state             = listState,
                    modifier          = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 80.dp, max = 280.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    if (transcript.isEmpty()) {
                        item { ListeningIndicator() }
                    } else {
                        items(transcript, key = { "${it.speaker}${it.text}" }) { line ->
                            AnimatedVisibility(
                                visible = true,
                                enter   = fadeIn() + slideInHorizontally(
                                    initialOffsetX = { if (line.speaker == "AI") -80 else 80 }
                                ),
                            ) {
                                TranscriptBubble(line)
                            }
                        }
                    }
                }

                Spacer(Modifier.height(12.dp))

                // User text input to speak to caller
                OutlinedTextField(
                    value = typedText,
                    onValueChange = { typedText = it },
                    placeholder = { Text("Type a message to caller...", color = TextMuted, fontSize = 14.sp) },
                    singleLine = true,
                    shape = RoundedCornerShape(24.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = Violet,
                        unfocusedBorderColor = Border,
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary,
                        cursorColor = VioletLight
                    ),
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                    keyboardActions = KeyboardActions(
                        onSend = {
                            if (typedText.isNotBlank()) {
                                onSendText(typedText)
                                typedText = ""
                            }
                        }
                    ),
                    trailingIcon = {
                        IconButton(
                            onClick = {
                                if (typedText.isNotBlank()) {
                                    onSendText(typedText)
                                    typedText = ""
                                }
                            },
                            enabled = typedText.isNotBlank()
                        ) {
                            Icon(
                                Icons.Default.Send,
                                contentDescription = "Send",
                                tint = if (typedText.isNotBlank()) VioletLight else TextMuted
                            )
                        }
                    },
                    modifier = Modifier.fillMaxWidth()
                )

                Spacer(Modifier.height(12.dp))

                ActionButtons(onJoin = onJoin, onBlock = onBlock, onMessage = onMessage)
                Spacer(Modifier.height(8.dp))
            }
        }
    }
}

// ── Header ────────────────────────────────────────────────────────────────────

@Composable
fun OverlayHeader(callerNumber: String, intentLabel: String, agentSpeaking: Boolean, isConnected: Boolean) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            modifier         = Modifier
                .size(48.dp)
                .clip(CircleShape)
                .background(Brush.radialGradient(listOf(Surface2, Surface1))),
            contentAlignment = Alignment.Center,
        ) {
            Text("?", fontSize = 22.sp, color = TextMuted, fontWeight = FontWeight.Bold)
        }
        Spacer(Modifier.width(14.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                if (isConnected) "Screening call" else "Connecting…",
                fontSize = 12.sp,
                color = if (isConnected) Emerald else Amber
            )
            Text(callerNumber, fontWeight = FontWeight.Bold, fontSize = 18.sp, color = TextPrimary)
        }
        if (intentLabel.isNotEmpty()) {
            IntentBadge(intentLabel)
        }
    }

    AnimatedVisibility(
        visible = agentSpeaking,
        enter   = fadeIn() + expandVertically(),
        exit    = fadeOut() + shrinkVertically(),
    ) {
        Spacer(Modifier.height(12.dp))
        SpeakingWave()
    }
}

@Composable
fun SpeakingWave() {
    val anim = rememberInfiniteTransition(label = "wave")
    Row(
        modifier            = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .background(Violet.copy(alpha = 0.1f))
            .padding(horizontal = 14.dp, vertical = 10.dp),
        verticalAlignment   = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Text("AI speaking", fontSize = 12.sp, color = VioletLight)
        Spacer(Modifier.width(6.dp))
        repeat(5) { i ->
            val height by anim.animateFloat(
                initialValue  = 4f,
                targetValue   = 18f,
                animationSpec = infiniteRepeatable(
                    tween(300 + i * 80, easing = FastOutSlowInEasing),
                    RepeatMode.Reverse,
                ),
                label = "bar$i",
            )
            Box(
                modifier = Modifier
                    .width(3.dp)
                    .height(height.dp)
                    .clip(CircleShape)
                    .background(VioletLight)
            )
        }
    }
}

// ── Intent badge ──────────────────────────────────────────────────────────────

@Composable
fun IntentBadge(intent: String) {
    val (label, color) = when (intent) {
        "spam"      -> "Spam"      to Rose
        "delivery"  -> "Delivery"  to Cyan
        "work"      -> "Work"      to Violet
        "personal"  -> "Personal"  to Emerald
        "emergency" -> "Urgent!"   to Amber
        else        -> "Unknown"   to TextMuted
    }
    Surface(
        shape = RoundedCornerShape(20.dp),
        color = color.copy(alpha = 0.15f),
        border = BorderStroke(1.dp, color.copy(alpha = 0.4f)),
    ) {
        Text(
            label,
            modifier   = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
            color      = color,
            fontSize   = 12.sp,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

// ── Listening indicator ───────────────────────────────────────────────────────

@Composable
fun ListeningIndicator() {
    val anim = rememberInfiniteTransition(label = "listen")
    val alpha by anim.animateFloat(
        initialValue  = 0.3f,
        targetValue   = 1f,
        animationSpec = infiniteRepeatable(tween(800), RepeatMode.Reverse),
        label         = "alpha",
    )
    Row(
        verticalAlignment   = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Box(
            modifier = Modifier
                .size(8.dp)
                .clip(CircleShape)
                .background(Emerald.copy(alpha = alpha))
        )
        Text("Listening…", fontSize = 14.sp, color = TextMuted)
    }
}

// ── Transcript bubbles ────────────────────────────────────────────────────────

@Composable
fun TranscriptBubble(line: TranscriptLine) {
    val isAI = line.speaker == "AI"
    val isUser = line.speaker == "You"
    val bubbleColor = when {
        isAI -> Violet.copy(alpha = 0.2f)
        isUser -> Emerald.copy(alpha = 0.2f)
        else -> Surface2
    }
    val borderColor = when {
        isAI -> Violet.copy(0.3f)
        isUser -> Emerald.copy(0.3f)
        else -> Border
    }
    Row(
        modifier              = Modifier.fillMaxWidth(),
        horizontalArrangement = if (isAI || isUser) Arrangement.Start else Arrangement.End,
    ) {
        Column(horizontalAlignment = if (isAI || isUser) Alignment.Start else Alignment.End) {
            Text(
                text     = when {
                    isAI -> "AI Assistant"
                    isUser -> "You"
                    else -> "Caller"
                },
                fontSize = 11.sp,
                color    = TextMuted,
                modifier = Modifier.padding(horizontal = 4.dp, vertical = 2.dp),
            )
            Surface(
                shape  = RoundedCornerShape(
                    topStart    = if (isAI || isUser) 4.dp else 16.dp,
                    topEnd      = if (isAI || isUser) 16.dp else 4.dp,
                    bottomStart = 16.dp,
                    bottomEnd   = 16.dp,
                ),
                color  = bubbleColor,
                border = BorderStroke(1.dp, borderColor),
                modifier = Modifier.widthIn(max = 280.dp),
            ) {
                Text(
                    text     = line.text,
                    modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
                    fontSize = 14.sp,
                    color    = TextPrimary,
                )
            }
        }
    }
}

// ── Action buttons ────────────────────────────────────────────────────────────

@Composable
fun ActionButtons(onJoin: () -> Unit, onBlock: () -> Unit, onMessage: () -> Unit) {
    Row(
        modifier              = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        PremiumButton(
            label    = "Join",
            icon     = "↗",
            color    = Emerald,
            modifier = Modifier.weight(1f),
            onClick  = onJoin,
        )
        PremiumButton(
            label    = "Message",
            icon     = "✉",
            color    = Cyan,
            modifier = Modifier.weight(1f),
            onClick  = onMessage,
            outlined = true,
        )
        PremiumButton(
            label    = "Block",
            icon     = "✕",
            color    = Rose,
            modifier = Modifier.weight(1f),
            onClick  = onBlock,
        )
    }
}

@Composable
fun PremiumButton(
    label: String,
    icon: String,
    color: Color,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
    outlined: Boolean = false,
) {
    var pressed by remember { mutableStateOf(false) }
    val scale by animateFloatAsState(
        targetValue   = if (pressed) 0.93f else 1f,
        animationSpec = spring(dampingRatio = Spring.DampingRatioMediumBouncy),
        label         = "scale",
    )

    Surface(
        onClick   = onClick,
        modifier  = modifier.scale(scale),
        shape     = RoundedCornerShape(14.dp),
        color     = if (outlined) color.copy(alpha = 0.1f) else color.copy(alpha = 0.9f),
        border    = BorderStroke(1.dp, color.copy(alpha = if (outlined) 0.5f else 0f)),
    ) {
        Column(
            modifier              = Modifier.padding(vertical = 12.dp),
            horizontalAlignment   = Alignment.CenterHorizontally,
            verticalArrangement   = Arrangement.spacedBy(3.dp),
        ) {
            Text(icon, fontSize = 18.sp, color = if (outlined) color else Color.White)
            Text(label, fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
                color = if (outlined) color else Color.White)
        }
    }
}
