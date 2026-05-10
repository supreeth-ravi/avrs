package ai.phronetic.screener.ui.screens

import android.Manifest
import android.app.role.RoleManager
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import ai.phronetic.screener.Config
import ai.phronetic.screener.ui.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

// ── Onboarding state machine ────────────────────────────────────────────────

private enum class Step {
    PERMISSIONS, SCREENER_ROLE, OVERLAY,
    PHONE, OTP, FORWARDING, PROFILE, DONE
}

@Composable
fun OnboardingScreen(onComplete: () -> Unit) {
    val context = LocalContext.current
    val roleManager = context.getSystemService(RoleManager::class.java)
    val scope = rememberCoroutineScope()

    var step by remember { mutableStateOf(Step.PERMISSIONS) }
    var permissionsGranted by remember { mutableStateOf(false) }
    var roleGranted by remember { mutableStateOf(false) }
    var overlayGranted by remember { mutableStateOf(false) }

    // Phone / OTP state
    var phoneNumber by remember { mutableStateOf("") }
    var otpValue by remember { mutableStateOf("") }
    var otpSent by remember { mutableStateOf(false) }
    var otpCountdown by remember { mutableIntStateOf(0) }
    var isLoading by remember { mutableStateOf(false) }
    var errorMsg by remember { mutableStateOf<String?>(null) }

    // Profile
    var userName by remember { mutableStateOf("") }
    var userGreeting by remember { mutableStateOf("") }

    val permissionsLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { results ->
        permissionsGranted = REQUIRED_PERMISSIONS.all {
            ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED
        }
    }

    val roleLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) {
        roleGranted = roleManager?.isRoleHeld(RoleManager.ROLE_CALL_SCREENING) == true
    }

    LaunchedEffect(Unit) {
        permissionsGranted = REQUIRED_PERMISSIONS.all {
            ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED
        }
        roleGranted = roleManager?.isRoleHeld(RoleManager.ROLE_CALL_SCREENING) == true
        overlayGranted = Settings.canDrawOverlays(context)
    }

    LaunchedEffect(otpCountdown) {
        if (otpCountdown > 0) { delay(1000); otpCountdown -= 1 }
    }

    fun apiUrl(path: String) = "${Config.SERVER_URL.trimEnd('/')}$path"

    fun requestOtp() {
        if (phoneNumber.length < 10) { errorMsg = "Enter a valid phone number"; return }
        errorMsg = null; isLoading = true
        scope.launch(Dispatchers.IO) {
            try {
                val client = OkHttpClient()
                val json = JSONObject().put("phone_number", phoneNumber)
                val body = json.toString().toRequestBody("application/json".toMediaType())
                val resp = client.newCall(
                    Request.Builder().url(apiUrl("/v1/auth/otp/request")).post(body).build()
                ).execute()
                withContext(Dispatchers.Main) {
                    isLoading = false
                    if (resp.isSuccessful) {
                        otpSent = true; otpCountdown = 60; errorMsg = null
                    } else {
                        errorMsg = "Failed to send OTP. Try again."
                    }
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) { isLoading = false; errorMsg = "Network error" }
            }
        }
    }

    fun verifyOtp() {
        if (otpValue.length < 4) { errorMsg = "Enter the OTP"; return }
        errorMsg = null; isLoading = true
        scope.launch(Dispatchers.IO) {
            try {
                val client = OkHttpClient()
                val json = JSONObject().apply {
                    put("phone_number", phoneNumber)
                    put("otp", otpValue)
                    put("name", "")
                }
                val body = json.toString().toRequestBody("application/json".toMediaType())
                val resp = client.newCall(
                    Request.Builder().url(apiUrl("/v1/auth/otp/verify")).post(body).build()
                ).execute()
                val respBody = resp.body?.string() ?: ""
                withContext(Dispatchers.Main) {
                    isLoading = false
                    if (resp.isSuccessful) {
                        val obj = JSONObject(respBody)
                        val token = obj.getString("auth_token")
                        val num = obj.optString("assigned_exotel_number", "")
                        Config.setAuthToken(context, token)
                        if (num.isNotBlank()) Config.setAssignedNumber(context, num)
                        step = Step.FORWARDING
                        errorMsg = null
                    } else {
                        val detail = try { JSONObject(respBody).optString("detail", "Invalid OTP") }
                        catch (_: Exception) { "Invalid OTP" }
                        errorMsg = detail
                    }
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) { isLoading = false; errorMsg = "Network error" }
            }
        }
    }

    fun saveProfile() {
        val token = Config.getAuthToken(context)
        if (token.isBlank()) { step = Step.DONE; return }
        isLoading = true
        scope.launch(Dispatchers.IO) {
            try {
                val client = OkHttpClient()
                val json = JSONObject().apply {
                    if (userName.isNotBlank()) put("name", userName)
                    if (userGreeting.isNotBlank()) put("greeting", userGreeting)
                }
                val body = json.toString().toRequestBody("application/json".toMediaType())
                client.newCall(
                    Request.Builder()
                        .url(apiUrl("/v1/auth/me?token=$token"))
                        .patch(body)
                        .build()
                ).execute()
                withContext(Dispatchers.Main) { isLoading = false; step = Step.DONE }
            } catch (_: Exception) {
                withContext(Dispatchers.Main) { isLoading = false; step = Step.DONE }
            }
        }
    }

    Box(modifier = Modifier.fillMaxSize().background(BgDark)) {
        AmbientGlow()
        AnimatedContent(
            targetState = step,
            transitionSpec = {
                (fadeIn(tween(400)) + slideInHorizontally { it / 4 }) togetherWith
                (fadeOut(tween(300)) + slideOutHorizontally { -it / 4 })
            },
            label = "step"
        ) { currentStep ->
            when (currentStep) {
                Step.PERMISSIONS -> PermissionStep(
                    granted = permissionsGranted,
                    onGrant = { permissionsLauncher.launch(REQUIRED_PERMISSIONS) },
                    onNext = { step = Step.SCREENER_ROLE }
                )
                Step.SCREENER_ROLE -> ScreenerRoleStep(
                    granted = roleGranted,
                    onRequest = {
                        roleLauncher.launch(roleManager.createRequestRoleIntent(RoleManager.ROLE_CALL_SCREENING))
                    },
                    onNext = { step = Step.OVERLAY },
                    onSkip = { step = Step.OVERLAY }
                )
                Step.OVERLAY -> OverlayStep(
                    granted = overlayGranted,
                    onRequest = {
                        context.startActivity(
                            Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION)
                                .setData(Uri.parse("package:${context.packageName}"))
                        )
                    },
                    onNext = { step = Step.PHONE }
                )
                Step.PHONE -> PhoneStep(
                    phone = phoneNumber,
                    onPhoneChange = { phoneNumber = it.filter { c -> c.isDigit() || c == '+' } },
                    onRequestOtp = { requestOtp() },
                    otpSent = otpSent,
                    countdown = otpCountdown,
                    isLoading = isLoading,
                    error = errorMsg,
                    onNext = { step = Step.OTP }
                )
                Step.OTP -> OtpStep(
                    otp = otpValue,
                    onOtpChange = { otpValue = it.filter { c -> c.isDigit() } },
                    onVerify = { verifyOtp() },
                    onResend = { requestOtp() },
                    countdown = otpCountdown,
                    isLoading = isLoading,
                    error = errorMsg
                )
                Step.FORWARDING -> ForwardingStep(
                    onActivate = {
                        val num = Config.getAssignedNumber(context)
                        if (num.isNotBlank() && ContextCompat.checkSelfPermission(context, Manifest.permission.CALL_PHONE) == PackageManager.PERMISSION_GRANTED) {
                            val ussd = Uri.encode("**21*$num#")
                            context.startActivity(
                                Intent(Intent.ACTION_CALL, Uri.parse("tel:$ussd"))
                                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            )
                        }
                    },
                    onDone = { step = Step.PROFILE }
                )
                Step.PROFILE -> ProfileSetupStep(
                    name = userName,
                    onNameChange = { userName = it },
                    greeting = userGreeting,
                    onGreetingChange = { userGreeting = it },
                    onSave = { saveProfile() },
                    isLoading = isLoading
                )
                Step.DONE -> DoneStep(onFinish = onComplete)
            }
        }
    }
}

private val REQUIRED_PERMISSIONS = arrayOf(
    Manifest.permission.READ_PHONE_STATE,
    Manifest.permission.READ_CONTACTS,
    Manifest.permission.POST_NOTIFICATIONS,
    Manifest.permission.CALL_PHONE,
)

// ── Step: Permissions ───────────────────────────────────────────────────────

@Composable
fun PermissionStep(granted: Boolean, onGrant: () -> Unit, onNext: () -> Unit) {
    OnboardingStepLayout(
        title = "Permissions",
        subtitle = "Pickr needs a few permissions to screen your calls",
        stepNumber = 1,
        totalSteps = 6
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            PermissionRow(
                icon = Icons.Default.Call,
                title = "Phone state",
                desc = "Detect incoming calls",
                granted = granted,
                color = Violet
            )
            PermissionRow(
                icon = Icons.Default.Person,
                title = "Contacts",
                desc = "Whitelist / blocklist",
                granted = granted,
                color = Cyan
            )
            PermissionRow(
                icon = Icons.Default.Notifications,
                title = "Notifications",
                desc = "Persistent screening notification",
                granted = granted,
                color = Emerald
            )
            PermissionRow(
                icon = Icons.Default.Phone,
                title = "Call phone",
                desc = "Activate carrier forwarding",
                granted = granted,
                color = Amber
            )
            Spacer(Modifier.height(16.dp))
            if (!granted) {
                Button(
                    onClick = onGrant,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Violet)
                ) {
                    Text("Allow Permissions", modifier = Modifier.padding(vertical = 6.dp), color = Color.White)
                }
            } else {
                Button(
                    onClick = onNext,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Emerald)
                ) {
                    Text("Continue", modifier = Modifier.padding(vertical = 6.dp), color = Color.White)
                }
            }
        }
    }
}

@Composable
fun PermissionRow(icon: ImageVector, title: String, desc: String, granted: Boolean, color: Color) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        color = if (granted) color.copy(alpha = 0.08f) else Surface1,
        border = BorderStroke(1.dp, if (granted) color.copy(alpha = 0.35f) else Border)
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            Box(
                modifier = Modifier.size(44.dp).clip(CircleShape).background(color.copy(alpha = 0.15f)),
                contentAlignment = Alignment.Center
            ) {
                Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(22.dp))
            }
            Column(modifier = Modifier.weight(1f)) {
                Text(title, fontWeight = FontWeight.SemiBold, color = TextPrimary, fontSize = 15.sp)
                Text(desc, fontSize = 13.sp, color = TextMuted)
            }
            if (granted) {
                Icon(Icons.Default.CheckCircle, contentDescription = "Granted", tint = Emerald, modifier = Modifier.size(24.dp))
            }
        }
    }
}

// ── Step: Screener Role ─────────────────────────────────────────────────────

@Composable
fun ScreenerRoleStep(granted: Boolean, onRequest: () -> Unit, onNext: () -> Unit, onSkip: () -> Unit) {
    OnboardingStepLayout(
        title = "Set as Call Screener",
        subtitle = "Let Pickr intercept unknown calls before your phone rings",
        stepNumber = 2,
        totalSteps = 6
    ) {
        Column {
            Surface(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(16.dp),
                color = Surface1,
                border = BorderStroke(1.dp, Border)
            ) {
                Column(modifier = Modifier.padding(20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(Icons.Default.Lock, contentDescription = null, tint = VioletLight, modifier = Modifier.size(56.dp))
                    Spacer(Modifier.height(12.dp))
                    Text(
                        if (granted) "You're the default screener" else "Not set as default screener",
                        fontWeight = FontWeight.SemiBold, color = TextPrimary, fontSize = 16.sp
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "This lets Pickr see who's calling and decide whether to let it through or send it to AI screening.",
                        fontSize = 13.sp, color = TextMuted, textAlign = TextAlign.Center
                    )
                }
            }
            Spacer(Modifier.height(20.dp))
            if (!granted) {
                Button(
                    onClick = onRequest,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Violet)
                ) {
                    Text("Set as Default Screener", color = Color.White, modifier = Modifier.padding(vertical = 6.dp))
                }
                Spacer(Modifier.height(8.dp))
                TextButton(onClick = onSkip, modifier = Modifier.fillMaxWidth()) {
                    Text("Skip for now", color = TextMuted, fontSize = 14.sp)
                }
            } else {
                Button(
                    onClick = onNext,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Emerald)
                ) {
                    Text("Continue", color = Color.White, modifier = Modifier.padding(vertical = 6.dp))
                }
            }
        }
    }
}

// ── Step: Overlay ───────────────────────────────────────────────────────────

@Composable
fun OverlayStep(granted: Boolean, onRequest: () -> Unit, onNext: () -> Unit) {
    OnboardingStepLayout(
        title = "Display Over Apps",
        subtitle = "Show the live screening overlay during calls",
        stepNumber = 3,
        totalSteps = 6
    ) {
        Column {
            Surface(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(16.dp),
                color = Surface1,
                border = BorderStroke(1.dp, Border)
            ) {
                Column(modifier = Modifier.padding(20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(Icons.Default.Menu, contentDescription = null, tint = Cyan, modifier = Modifier.size(56.dp))
                    Spacer(Modifier.height(12.dp))
                    Text(
                        if (granted) "Overlay permission granted" else "Overlay permission needed",
                        fontWeight = FontWeight.SemiBold, color = TextPrimary, fontSize = 16.sp
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "You'll see a live transcript and Join/Block buttons while the AI is talking to the caller.",
                        fontSize = 13.sp, color = TextMuted, textAlign = TextAlign.Center
                    )
                }
            }
            Spacer(Modifier.height(20.dp))
            if (!granted) {
                Button(
                    onClick = onRequest,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Violet)
                ) {
                    Text("Allow Overlay", color = Color.White, modifier = Modifier.padding(vertical = 6.dp))
                }
            } else {
                Button(
                    onClick = onNext,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Emerald)
                ) {
                    Text("Continue", color = Color.White, modifier = Modifier.padding(vertical = 6.dp))
                }
            }
        }
    }
}

// ── Step: Phone ─────────────────────────────────────────────────────────────

@Composable
fun PhoneStep(
    phone: String,
    onPhoneChange: (String) -> Unit,
    onRequestOtp: () -> Unit,
    otpSent: Boolean,
    countdown: Int,
    isLoading: Boolean,
    error: String?,
    onNext: () -> Unit,
) {
    OnboardingStepLayout(
        title = "Your Phone Number",
        subtitle = "We'll send a one-time password to verify it's you",
        stepNumber = 4,
        totalSteps = 6
    ) {
        Column {
            OutlinedTextField(
                value = phone,
                onValueChange = onPhoneChange,
                placeholder = { Text("+91 98765 43210", color = TextMuted, fontSize = 13.sp) },
                label = { Text("Phone number", color = TextMuted) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(12.dp),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = Violet,
                    unfocusedBorderColor = Border,
                    focusedTextColor = TextPrimary,
                    unfocusedTextColor = TextPrimary,
                    cursorColor = VioletLight,
                ),
            )
            if (error != null) {
                Spacer(Modifier.height(8.dp))
                Text(error, color = Rose, fontSize = 13.sp)
            }
            Spacer(Modifier.height(20.dp))
            if (!otpSent) {
                Button(
                    onClick = onRequestOtp,
                    enabled = phone.length >= 10 && !isLoading,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Violet)
                ) {
                    if (isLoading) {
                        CircularProgressIndicator(modifier = Modifier.size(18.dp), color = Color.White, strokeWidth = 2.dp)
                    } else {
                        Text("Get OTP", color = Color.White, modifier = Modifier.padding(vertical = 6.dp))
                    }
                }
            } else {
                Button(
                    onClick = onNext,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Emerald)
                ) {
                    Text("Enter OTP →", color = Color.White, modifier = Modifier.padding(vertical = 6.dp))
                }
                if (countdown > 0) {
                    Spacer(Modifier.height(8.dp))
                    Text("Resend in ${countdown}s", color = TextMuted, fontSize = 13.sp, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
                } else {
                    Spacer(Modifier.height(8.dp))
                    TextButton(onClick = onRequestOtp, modifier = Modifier.fillMaxWidth()) {
                        Text("Resend OTP", color = VioletLight, fontSize = 14.sp)
                    }
                }
            }
        }
    }
}

// ── Step: OTP ───────────────────────────────────────────────────────────────

@Composable
fun OtpStep(
    otp: String,
    onOtpChange: (String) -> Unit,
    onVerify: () -> Unit,
    onResend: () -> Unit,
    countdown: Int,
    isLoading: Boolean,
    error: String?,
) {
    OnboardingStepLayout(
        title = "Verify OTP",
        subtitle = "Enter the 6-digit code we sent",
        stepNumber = 4,
        totalSteps = 6
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            OutlinedTextField(
                value = otp,
                onValueChange = { onOtpChange(it.take(6)) },
                placeholder = { Text("000000", color = TextMuted, fontSize = 20.sp) },
                singleLine = true,
                textStyle = androidx.compose.ui.text.TextStyle(fontSize = 24.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(12.dp),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = Violet,
                    unfocusedBorderColor = Border,
                    focusedTextColor = TextPrimary,
                    unfocusedTextColor = TextPrimary,
                    cursorColor = VioletLight,
                ),
            )
            if (error != null) {
                Spacer(Modifier.height(8.dp))
                Text(error, color = Rose, fontSize = 13.sp)
            }
            Spacer(Modifier.height(20.dp))
            Button(
                onClick = onVerify,
                enabled = otp.length >= 4 && !isLoading,
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Violet)
            ) {
                if (isLoading) {
                    CircularProgressIndicator(modifier = Modifier.size(18.dp), color = Color.White, strokeWidth = 2.dp)
                } else {
                    Text("Verify & Activate", color = Color.White, modifier = Modifier.padding(vertical = 6.dp))
                }
            }
            Spacer(Modifier.height(8.dp))
            if (countdown > 0) {
                Text("Resend in ${countdown}s", color = TextMuted, fontSize = 13.sp)
            } else {
                TextButton(onClick = onResend) {
                    Text("Resend OTP", color = VioletLight, fontSize = 14.sp)
                }
            }
        }
    }
}

// ── Step: Forwarding ────────────────────────────────────────────────────────

@Composable
fun ForwardingStep(onActivate: () -> Unit, onDone: () -> Unit) {
    var activating by remember { mutableStateOf(false) }
    var activated by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    val rotation by rememberInfiniteTransition(label = "spin").animateFloat(
        initialValue = 0f, targetValue = 360f,
        animationSpec = infiniteRepeatable(tween(1200, easing = LinearEasing), RepeatMode.Restart),
        label = "spin"
    )

    OnboardingStepLayout(
        title = "Activating Pickr",
        subtitle = "We're setting up call forwarding with your carrier",
        stepNumber = 5,
        totalSteps = 6
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            if (!activating && !activated) {
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(16.dp),
                    color = Surface1,
                    border = BorderStroke(1.dp, Border)
                ) {
                    Column(modifier = Modifier.padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                        Icon(Icons.Default.Call, contentDescription = null, tint = Cyan, modifier = Modifier.size(48.dp))
                        Spacer(Modifier.height(16.dp))
                        Text("One-tap activation", fontWeight = FontWeight.SemiBold, color = TextPrimary, fontSize = 16.sp)
                        Spacer(Modifier.height(8.dp))
                        Text(
                            "Pickr will dial your carrier's forwarding code automatically. This takes a few seconds.",
                            fontSize = 13.sp, color = TextMuted, textAlign = TextAlign.Center
                        )
                    }
                }
                Spacer(Modifier.height(24.dp))
                Button(
                    onClick = {
                        activating = true
                        onActivate()
                        scope.launch {
                            delay(6000)
                            activating = false
                            activated = true
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Cyan)
                ) {
                    Icon(Icons.Default.Phone, contentDescription = null, tint = Color.White, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(8.dp))
                    Text("Activate Forwarding", color = Color.White, modifier = Modifier.padding(vertical = 6.dp))
                }
            } else if (activating) {
                Box(
                    modifier = Modifier.size(80.dp),
                    contentAlignment = Alignment.Center
                ) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(80.dp),
                        color = Cyan,
                        strokeWidth = 4.dp,
                        trackColor = Surface2
                    )
                    Icon(Icons.Default.Call, contentDescription = null, tint = Cyan, modifier = Modifier.size(32.dp))
                }
                Spacer(Modifier.height(24.dp))
                Text("Dialing carrier...", fontSize = 18.sp, fontWeight = FontWeight.SemiBold, color = TextPrimary)
                Spacer(Modifier.height(8.dp))
                Text("Please wait while we set up call forwarding.", fontSize = 13.sp, color = TextMuted, textAlign = TextAlign.Center)
            } else {
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(16.dp),
                    color = Emerald.copy(alpha = 0.08f),
                    border = BorderStroke(1.dp, Emerald.copy(alpha = 0.35f))
                ) {
                    Column(
                        modifier = Modifier.padding(28.dp),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Icon(Icons.Default.CheckCircle, contentDescription = null, tint = Emerald, modifier = Modifier.size(56.dp))
                        Spacer(Modifier.height(16.dp))
                        Text("Forwarding active!", fontWeight = FontWeight.Bold, color = TextPrimary, fontSize = 20.sp)
                        Spacer(Modifier.height(8.dp))
                        Text(
                            "All your calls are now routed through Pickr's AI screening.",
                            fontSize = 13.sp, color = TextMuted, textAlign = TextAlign.Center
                        )
                    }
                }
                Spacer(Modifier.height(24.dp))
                Button(
                    onClick = onDone,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Emerald)
                ) {
                    Text("Continue", color = Color.White, modifier = Modifier.padding(vertical = 6.dp))
                }
            }
        }
    }
}

// ── Step: Profile Setup ─────────────────────────────────────────────────────

@Composable
fun ProfileSetupStep(
    name: String,
    onNameChange: (String) -> Unit,
    greeting: String,
    onGreetingChange: (String) -> Unit,
    onSave: () -> Unit,
    isLoading: Boolean,
) {
    OnboardingStepLayout(
        title = "Your Profile",
        subtitle = "Personalize how the AI greets your callers",
        stepNumber = 6,
        totalSteps = 6
    ) {
        Column {
            OutlinedTextField(
                value = name,
                onValueChange = onNameChange,
                label = { Text("Your name", color = TextMuted) },
                placeholder = { Text("e.g. Rahul Sharma", color = TextMuted, fontSize = 13.sp) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(12.dp),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = Violet,
                    unfocusedBorderColor = Border,
                    focusedTextColor = TextPrimary,
                    unfocusedTextColor = TextPrimary,
                ),
            )
            Spacer(Modifier.height(16.dp))
            OutlinedTextField(
                value = greeting,
                onValueChange = onGreetingChange,
                label = { Text("AI greeting (optional)", color = TextMuted) },
                placeholder = { Text("Hello, this is Pickr. Who may I say is calling?", color = TextMuted, fontSize = 13.sp) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(12.dp),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = Violet,
                    unfocusedBorderColor = Border,
                    focusedTextColor = TextPrimary,
                    unfocusedTextColor = TextPrimary,
                ),
            )
            Spacer(Modifier.height(8.dp))
            Text("The AI will say this when answering calls on your behalf.", fontSize = 12.sp, color = TextMuted)
            Spacer(Modifier.height(24.dp))
            Button(
                onClick = onSave,
                enabled = !isLoading,
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Violet)
            ) {
                if (isLoading) {
                    CircularProgressIndicator(modifier = Modifier.size(18.dp), color = Color.White, strokeWidth = 2.dp)
                } else {
                    Text("Finish Setup", color = Color.White, modifier = Modifier.padding(vertical = 6.dp))
                }
            }
        }
    }
}

// ── Step: Done ──────────────────────────────────────────────────────────────

@Composable
fun DoneStep(onFinish: () -> Unit) {
    val scale by rememberInfiniteTransition(label = "bounce").animateFloat(
        initialValue = 0.95f, targetValue = 1.05f,
        animationSpec = infiniteRepeatable(tween(1500, easing = EaseInOutQuad), RepeatMode.Reverse),
        label = "bounce"
    )

    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.padding(24.dp)) {
            Box(
                modifier = Modifier.size(100.dp).scale(scale).clip(CircleShape).background(Emerald.copy(alpha = 0.15f)),
                contentAlignment = Alignment.Center
            ) {
                Icon(Icons.Default.CheckCircle, contentDescription = null, tint = Emerald, modifier = Modifier.size(56.dp))
            }
            Spacer(Modifier.height(32.dp))
            Text("You're all set!", fontSize = 28.sp, fontWeight = FontWeight.Bold, color = TextPrimary)
            Spacer(Modifier.height(12.dp))
            Text(
                "Pickr will now screen every call that comes to your virtual number. You'll get live transcripts and can join or block anytime.",
                fontSize = 14.sp, color = TextMuted, textAlign = TextAlign.Center
            )
            Spacer(Modifier.height(40.dp))
            Button(
                onClick = onFinish,
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(16.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Violet)
            ) {
                Text("Go to Dashboard", color = Color.White, modifier = Modifier.padding(vertical = 8.dp))
            }
        }
    }
}

// ── Shared layout ───────────────────────────────────────────────────────────

@Composable
fun OnboardingStepLayout(
    title: String,
    subtitle: String,
    stepNumber: Int,
    totalSteps: Int,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp, vertical = 40.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            for (i in 1..totalSteps) {
                Box(
                    modifier = Modifier
                        .width(if (i == stepNumber) 24.dp else 8.dp)
                        .height(8.dp)
                        .clip(RoundedCornerShape(4.dp))
                        .background(if (i <= stepNumber) Violet else Surface2)
                )
            }
        }
        Spacer(Modifier.height(32.dp))
        Text(title, fontSize = 26.sp, fontWeight = FontWeight.Bold, color = TextPrimary)
        Spacer(Modifier.height(6.dp))
        Text(subtitle, fontSize = 14.sp, color = TextMuted, textAlign = TextAlign.Center)
        Spacer(Modifier.height(32.dp))
        content()
    }
}
