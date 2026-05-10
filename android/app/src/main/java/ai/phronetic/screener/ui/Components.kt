package ai.phronetic.screener.ui

import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.*
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ai.phronetic.screener.ScreeningMode
import kotlinx.coroutines.delay

// ── Ambient background glows ──────────────────────────────────────────────────

@Composable
fun AmbientGlow() {
    val anim = rememberInfiniteTransition(label = "ambient")
    val shift by anim.animateFloat(
        initialValue  = 0f,
        targetValue   = 1f,
        animationSpec = infiniteRepeatable(tween(8000, easing = LinearEasing)),
        label         = "shift",
    )
    Canvas(modifier = Modifier.fillMaxSize()) {
        val w = size.width; val h = size.height
        drawCircle(
            brush  = Brush.radialGradient(
                colors  = listOf(Violet.copy(alpha = 0.12f), Color.Transparent),
                center  = Offset(w * 0.2f, h * 0.15f + shift * 60),
                radius  = w * 0.6f,
            ),
            radius = w * 0.6f,
            center = Offset(w * 0.2f, h * 0.15f + shift * 60),
        )
        drawCircle(
            brush  = Brush.radialGradient(
                colors  = listOf(Cyan.copy(alpha = 0.07f), Color.Transparent),
                center  = Offset(w * 0.85f, h * 0.6f - shift * 40),
                radius  = w * 0.5f,
            ),
            radius = w * 0.5f,
            center = Offset(w * 0.85f, h * 0.6f - shift * 40),
        )
    }
}

// ── Header ────────────────────────────────────────────────────────────────────

@Composable
fun AppHeader(mode: ScreeningMode, active: Boolean) {
    val pulse = rememberInfiniteTransition(label = "pulse")
    val glowAlpha by pulse.animateFloat(
        initialValue    = 0.3f,
        targetValue     = 0.7f,
        animationSpec   = infiniteRepeatable(tween(2000), RepeatMode.Reverse),
        label           = "glow",
    )

    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Box(contentAlignment = Alignment.Center) {
            if (active) {
                Box(
                    modifier = Modifier
                        .size(88.dp)
                        .clip(CircleShape)
                        .background(Violet.copy(alpha = glowAlpha * 0.4f))
                        .blur(20.dp)
                )
            }
            Box(
                modifier = Modifier
                    .size(64.dp)
                    .clip(CircleShape)
                    .background(
                        Brush.radialGradient(listOf(VioletLight, Violet))
                    ),
                contentAlignment = Alignment.Center,
            ) {
                Text("✦", fontSize = 26.sp, color = Color.White)
            }
        }

        Spacer(Modifier.height(20.dp))

        Text(
            "Pickr",
            fontSize   = 36.sp,
            fontWeight = FontWeight.Bold,
            color      = TextPrimary,
            letterSpacing = (-1).sp,
        )
        Spacer(Modifier.height(6.dp))

        val badgeColor by animateColorAsState(
            targetValue   = if (mode == ScreeningMode.LLM) Violet else Surface2,
            animationSpec = tween(600),
            label         = "badge",
        )
        Surface(
            shape = RoundedCornerShape(20.dp),
            color = badgeColor,
            border = BorderStroke(1.dp, Border),
        ) {
            Text(
                text = if (mode == ScreeningMode.LLM) "Claude AI  ·  Online" else "Offline  ·  On-device",
                modifier  = Modifier.padding(horizontal = 14.dp, vertical = 5.dp),
                fontSize  = 12.sp,
                color     = if (mode == ScreeningMode.LLM) VioletLight else TextMuted,
                fontWeight = FontWeight.Medium,
            )
        }
    }
}

// ── Staggered entrance ────────────────────────────────────────────────────────

@Composable
fun StaggeredStep(delayMs: Int, content: @Composable () -> Unit) {
    var visible by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        delay(delayMs.toLong())
        visible = true
    }
    AnimatedVisibility(
        visible = visible,
        enter   = fadeIn(tween(400)) + slideInVertically(tween(400)) { it / 3 },
    ) {
        content()
    }
}

// ── Step card ─────────────────────────────────────────────────────────────────

@Composable
fun StepCard(
    index: Int,
    title: String,
    description: String,
    done: Boolean,
    actionLabel: String,
    onAction: () -> Unit,
    enabled: Boolean = true,
) {
    val borderColor by animateColorAsState(
        targetValue   = if (done) Emerald.copy(alpha = 0.5f) else Border,
        animationSpec = tween(500),
        label         = "border",
    )
    val bgColor by animateColorAsState(
        targetValue   = if (done) Emerald.copy(alpha = 0.05f) else Surface1,
        animationSpec = tween(500),
        label         = "bg",
    )

    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape    = RoundedCornerShape(16.dp),
        color    = bgColor,
        border   = BorderStroke(1.dp, borderColor),
    ) {
        Row(
            modifier            = Modifier.padding(16.dp),
            verticalAlignment   = Alignment.CenterVertically,
        ) {
            StepIndicator(index = index, done = done)
            Spacer(Modifier.width(16.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(title, fontWeight = FontWeight.SemiBold, color = TextPrimary, fontSize = 15.sp)
                Text(description, fontSize = 13.sp, color = TextMuted)
            }
            if (!done) {
                Spacer(Modifier.width(12.dp))
                Button(
                    onClick = onAction,
                    enabled = enabled,
                    shape   = RoundedCornerShape(10.dp),
                    colors  = ButtonDefaults.buttonColors(containerColor = Violet),
                    contentPadding = PaddingValues(horizontal = 18.dp, vertical = 8.dp),
                ) { Text(actionLabel, fontSize = 13.sp) }
            }
        }
    }
}

@Composable
fun StepIndicator(index: Int, done: Boolean) {
    val scale by animateFloatAsState(
        targetValue   = if (done) 1.15f else 1f,
        animationSpec = spring(dampingRatio = Spring.DampingRatioMediumBouncy),
        label         = "scale",
    )
    val bgColor by animateColorAsState(
        targetValue   = if (done) Emerald else Surface2,
        animationSpec = tween(400),
        label         = "bg",
    )
    Box(
        modifier = Modifier
            .scale(scale)
            .size(36.dp)
            .clip(CircleShape)
            .background(bgColor)
            .border(1.dp, Border, CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        Crossfade(targetState = done, animationSpec = tween(300), label = "icon") { isDone ->
            Text(
                text      = if (isDone) "✓" else "$index",
                fontSize  = 15.sp,
                fontWeight = FontWeight.Bold,
                color     = if (isDone) Color.White else TextMuted,
            )
        }
    }
}

// ── API key card ──────────────────────────────────────────────────────────────

@Composable
fun ApiKeyCard(
    label: String,
    hint: String,
    savedKey: String,
    onSave: (String) -> Unit,
    stepIndex: Int,
) {
    var input   by remember { mutableStateOf(savedKey) }
    var visible by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf(false) }

    val hasKey = savedKey.isNotBlank()
    val borderColor by animateColorAsState(
        targetValue   = if (hasKey) Violet.copy(alpha = 0.5f) else Border,
        animationSpec = tween(500), label = "border",
    )
    val bgColor by animateColorAsState(
        targetValue   = if (hasKey) Violet.copy(alpha = 0.06f) else Surface1,
        animationSpec = tween(500), label = "bg",
    )

    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape    = RoundedCornerShape(16.dp),
        color    = bgColor,
        border   = BorderStroke(1.dp, borderColor),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier         = Modifier
                        .size(36.dp)
                        .clip(CircleShape)
                        .background(if (hasKey) Violet.copy(0.2f) else Surface2)
                        .border(1.dp, Border, CircleShape),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        if (hasKey) "⚡" else "$stepIndex",
                        fontSize   = 15.sp,
                        fontWeight = FontWeight.Bold,
                        color      = if (hasKey) VioletLight else TextMuted,
                    )
                }
                Spacer(Modifier.width(16.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(label, fontWeight = FontWeight.SemiBold, color = TextPrimary, fontSize = 15.sp)
                    Text(
                        if (hasKey) "Key saved" else "Required for AI conversation",
                        fontSize = 13.sp,
                        color    = if (hasKey) VioletLight else TextMuted,
                    )
                }
                if (!editing) {
                    TextButton(onClick = { editing = true; input = savedKey }) {
                        Text(if (hasKey) "Edit" else "Add",
                            color = if (hasKey) VioletLight else TextMuted, fontSize = 13.sp)
                    }
                }
            }

            AnimatedVisibility(visible = editing, enter = fadeIn() + expandVertically(),
                exit = fadeOut() + shrinkVertically()) {
                Column {
                    Spacer(Modifier.height(16.dp))
                    OutlinedTextField(
                        value    = input,
                        onValueChange = { input = it },
                        placeholder   = { Text(hint, color = TextMuted, fontSize = 13.sp) },
                        singleLine    = true,
                        visualTransformation = if (visible) VisualTransformation.None
                                              else PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        trailingIcon = {
                            TextButton(onClick = { visible = !visible }) {
                                Text(if (visible) "Hide" else "Show", color = TextMuted, fontSize = 12.sp)
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                        shape    = RoundedCornerShape(12.dp),
                        colors   = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor   = Violet,
                            unfocusedBorderColor = Border,
                            focusedTextColor     = TextPrimary,
                            unfocusedTextColor   = TextPrimary,
                            cursorColor          = VioletLight,
                        ),
                    )
                    Spacer(Modifier.height(12.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(
                            onClick  = { onSave(""); input = ""; editing = false },
                            modifier = Modifier.weight(1f),
                            shape    = RoundedCornerShape(10.dp),
                            border   = BorderStroke(1.dp, Border),
                        ) { Text("Clear", color = TextMuted, fontSize = 13.sp) }
                        Button(
                            onClick  = { onSave(input); editing = false },
                            enabled  = input.isNotBlank(),
                            modifier = Modifier.weight(1f),
                            shape    = RoundedCornerShape(10.dp),
                            colors   = ButtonDefaults.buttonColors(containerColor = Violet),
                        ) { Text("Save", fontSize = 13.sp) }
                    }
                }
            }
        }
    }
}

// ── Empty state ───────────────────────────────────────────────────────────────

@Composable
fun EmptyState(message: String) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(120.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(message, fontSize = 14.sp, color = TextMuted)
    }
}
