# Pickr — End-to-End Setup Guide

This document walks through running the complete Pickr stack: backend, Exotel, and Android app.

---

## Architecture Overview

```
Caller dials user's Exotel virtual number
         │
         ▼
   ┌─────────────┐
   │   Exotel    │ ← SIP / PSTN
   │   (India)   │
   └──────┬──────┘
          │ WebSocket
          ▼
   ┌─────────────┐     WebSocket      ┌─────────────┐
   │ AVRS Backend│ ◄────────────────► │  Android    │
   │  /ws/exotel │     /ws/screen     │    App      │
   │  (FastAPI)  │                    │   (Pickr)   │
   └─────────────┘                    └─────────────┘
```

---

## 1. Backend Setup

### 1.1 Prerequisites

- Python 3.10+
- `ffmpeg` installed (for audio processing)
- A server with a public IP / domain (Exotel cannot reach `localhost`)

### 1.2 Environment Variables

Create `.env` in the project root:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Required — Anthropic API key for Claude LLM
ANTHROPIC_API_KEY=sk-ant-...

# Optional — Deepgram API key for fast cloud STT (~200ms)
# Leave unset to use local Whisper (offline, slower on CPU)
DEEPGRAM_API_KEY=dg-...

# TTS engine: kokoro | mock  (default: kokoro)
# Use mock for dev/testing without model files
AVRS_TTS_MODEL=kokoro

# Optional — API key to protect admin endpoints
# Leave empty for local dev; set in production
AVRS_API_KEY=pickr_prod_key_2025
```

### 1.3 Install Dependencies

```bash
cd /path/to/avrs
python -m venv .venv
source .venv/bin/activate

# Core dependencies
pip install -e "."

# TTS engine (pick one)
pip install -e ".[kokoro]"      # recommended — fast, local
# OR
pip install -e ".[chatterbox]"  # alternative

# Dev dependencies (optional)
pip install -e ".[dev]"
```

### 1.4 Verify TTS Model

Kokoro models should be in `models/kokoro/`:

```
models/kokoro/
├── kokoro-v1.0.onnx
└── voices-v1.0.bin
```

If missing, download them:

```bash
# Kokoro v1.0 models
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v1.0.onnx -P models/kokoro/
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/voices-v1.0.bin -P models/kokoro/
```

### 1.5 Run the Server

```bash
source .venv/bin/activate

# Development (with auto-reload)
uvicorn avrs.voice_api:app --host 0.0.0.0 --port 8000 --reload

# Production
uvicorn avrs.voice_api:app --host 0.0.0.0 --port 8000 --workers 2
```

Verify it's running:

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "ok",
  "tts_model": "kokoro",
  "stt_available": true,
  "active_sessions": 0,
  "agents": ["insurance", "banking", "payments", "screener"],
  "users": 0,
  "available_numbers": 0
}
```

### 1.6 Expose to Internet (for Exotel)

Exotel needs to reach your backend. Options:

**Option A: ngrok (for testing)**
```bash
ngrok http 8000
# Use the https URL: https://abc123.ngrok.io
```

**Option B: Deploy to cloud**
Deploy to AWS/GCP/DigitalOcean with a public IP and domain.

**Option C: Self-hosted with reverse proxy**
```bash
# Using Caddy (auto HTTPS)
caddy reverse-proxy --from yourdomain.com --to :8000
```

Your WebSocket URL for Exotel will be:
```
wss://your-domain.com/ws/exotel
```

---

## 2. Seed Virtual Number Pool

Before users can sign up, you must add virtual numbers to the pool:

```bash
# Add numbers you purchased from Exotel
curl -X POST https://your-domain.com/v1/admin/numbers \
  -H "X-API-Key: pickr_prod_key_2025" \
  -H "Content-Type: application/json" \
  -d '{
    "numbers": ["+912261234567", "+912261234568", "+912261234569"],
    "region": "IN"
  }'
```

Verify pool:
```bash
curl https://your-domain.com/v1/admin/numbers \
  -H "X-API-Key: pickr_prod_key_2025"
```

---

## 3. Exotel Configuration

### 3.1 Exotel Account Requirements

- Exotel account with Voicebot feature enabled
- At least one **Exophone** (virtual number) purchased
- The Exophone numbers should match what you added to the Pickr pool

### 3.2 Create a Voicebot Applet

1. Log in to [Exotel Dashboard](https://my.exotel.com/)
2. Go to **Apps** → **Create New**
3. Add a **Voicebot** widget to your applet
4. Configure the Voicebot:
   - **WebSocket URL**: `wss://your-domain.com/ws/exotel`
   - **API Key** (optional): `pickr_prod_key_2025` (matches `AVRS_API_KEY`)
5. Save and connect your Exophone to this applet

### 3.3 Important: Exotel WebSocket Protocol

Exotel sends these events to `/ws/exotel`:

```json
// 1. Start event (when call begins)
{
  "event": "start",
  "start": {
    "callSid": "EXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "from": "+919876543210",
    "to": "+912261234567",
    "streamSid": "MXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  }
}

// 2. Media events (8kHz PCM audio from caller)
{
  "event": "media",
  "media": {
    "payload": "<base64-encoded 8kHz 16-bit mono PCM>"
  }
}

// 3. Stop event (when call ends)
{ "event": "stop" }
```

Your server responds with:
```json
{
  "event": "media",
  "media": {
    "payload": "<base64-encoded 8kHz 16-bit mono PCM>"
  }
}
```

### 3.4 Test Exotel Connectivity

You can test the WebSocket endpoint independently:

```bash
# Using wscat
npm install -g wscat
wscat -c "wss://your-domain.com/ws/exotel?api_key=pickr_prod_key_2025"

# Send a start event
> {"event":"start","start":{"callSid":"test123","from":"+919876543210","to":"+912261234567"}}
```

If the backend logs show `[exotel] call started: test123`, the connection works.

---

## 4. Android App Setup

### 4.1 Update Server URL (if needed)

The app uses a hardcoded server URL in `Config.kt`:

```kotlin
const val SERVER_URL = "https://pickr.phronetic.ai"
```

Change this to your actual backend domain before building:

```kotlin
// For production
const val SERVER_URL = "https://your-domain.com"

// For testing with ngrok
const val SERVER_URL = "https://abc123.ngrok.io"
```

### 4.2 Build the APK

```bash
cd android
./gradlew :app:assembleDebug
```

APK location:
```
android/app/build/outputs/apk/debug/app-debug.apk
```

### 4.3 Install on Device

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Or transfer the APK to your phone and install manually (enable "Install from unknown sources").

---

## 5. End-to-End Flow Test

### Step 1: User Onboarding

1. Open Pickr app on phone
2. **Permissions** → Grant phone, contacts, notifications, call phone
3. **Call Screener Role** → Set Pickr as default call screener
4. **Overlay** → Allow display over other apps
5. **Phone Number** → Enter your real mobile number (e.g., `+919876543210`)
6. **OTP** → Enter the OTP (in dev mode, OTP is shown in backend response; in production, SMS is sent)
7. **Activating Pickr** → App auto-dials carrier forwarding code `**21*<assigned_number>#`
8. **Profile** → Enter your name and custom AI greeting (optional)
9. **Done** → Dashboard opens

### Step 2: Verify Backend State

```bash
# Check user was created
curl https://your-domain.com/v1/admin/users \
  -H "X-API-Key: pickr_prod_key_2025"

# Check number was assigned
curl https://your-domain.com/v1/admin/numbers \
  -H "X-API-Key: pickr_prod_key_2025"
```

### Step 3: Test a Call

1. From a **different phone**, call the user's assigned Exotel number
   (e.g., dial `+912261234567`)
2. The caller hears the AI greeting: *"Hello, this is Pickr. Who may I say is calling?"*
3. The Pickr app on the user's phone shows:
   - Live transcript of the conversation
   - Intent badge (spam, delivery, work, personal)
   - Join / Block / Message buttons
4. The user can:
   - **Join** → AI says "Please hold, connecting you now"
   - **Block** → AI says "Not available. Goodbye."
   - **Type a message** → AI speaks it to the caller

### Step 4: Verify Call History

```bash
curl https://your-domain.com/v1/admin/users \
  -H "X-API-Key: pickr_prod_key_2025"
```

The user object should show:
```json
{
  "call_history": [
    {
      "caller": "+919999999999",
      "callee": "+912261234567",
      "status": "ended",
      "duration_sec": 45.2,
      "timestamp": 1715000000.0
    }
  ],
  "monthly_minutes_used": 0.75
}
```

---

## 6. Provider Admin Operations

### Change User Tier
```bash
curl -X POST "https://your-domain.com/v1/admin/users/usr_xxx/tier?tier=pro" \
  -H "X-API-Key: pickr_prod_key_2025"
```

### Disable a User
```bash
curl -X POST "https://your-domain.com/v1/admin/users/usr_xxx/disable" \
  -H "X-API-Key: pickr_prod_key_2025"
```

### View Analytics
```bash
curl "https://your-domain.com/v1/admin/analytics" \
  -H "X-API-Key: pickr_prod_key_2025"
```

---

## 7. Troubleshooting

### Backend won't start
- Check `.env` has `ANTHROPIC_API_KEY` set
- Verify `kokoro-v1.0.onnx` exists in `models/kokoro/`
- Check port 8000 is not in use: `lsof -i :8000`

### Exotel can't connect
- Ensure server is publicly accessible (not localhost)
- Verify WebSocket URL uses `wss://` (not `ws://`) in production
- Check `AVRS_API_KEY` matches between backend and Exotel config
- Check firewall rules: port 443/80/8000 must be open

### App says "Network error"
- Verify `Config.SERVER_URL` points to your actual backend
- Check phone has internet connectivity
- Verify backend `/health` endpoint responds

### Call forwarding didn't activate
- Ensure `CALL_PHONE` permission is granted
- Some carriers block `ACTION_CALL` with USSD. Try manually dialing `**21*<number>#`
- Check if the assigned number is correct in backend logs

### STT not working
- If using local Whisper (no Deepgram key), first transcription is slow (~4-8s on CPU)
- For production, set `DEEPGRAM_API_KEY` for ~200ms STT

### TTS is silent
- Check `AVRS_TTS_MODEL` is set to `kokoro` (not `mock`)
- Verify Kokoro model files exist in `models/kokoro/`
- Check backend logs for TTS errors

---

## 8. Production Checklist

- [ ] Backend deployed to cloud with public domain
- [ ] HTTPS / WSS enabled (Let's Encrypt or commercial cert)
- [ ] `AVRS_API_KEY` set to a strong random string
- [ ] `ANTHROPIC_API_KEY` has sufficient quota
- [ ] `DEEPGRAM_API_KEY` set for production STT speed
- [ ] Kokoro models downloaded to `models/kokoro/`
- [ ] Virtual number pool seeded via `/v1/admin/numbers`
- [ ] Exotel Voicebot Applet pointed to `wss://your-domain.com/ws/exotel`
- [ ] Exophone connected to Voicebot Applet
- [ ] Android `Config.SERVER_URL` updated to production domain
- [ ] APK signed for release (not debug)
- [ ] FCM push notifications configured (optional, for wake-up when app killed)

---

## Quick Reference: Key URLs

| Endpoint | URL |
|----------|-----|
| Health | `GET /health` |
| OTP Request | `POST /v1/auth/otp/request` |
| OTP Verify | `POST /v1/auth/otp/verify` |
| User Profile | `GET /v1/auth/me?token=...` |
| Update Profile | `PATCH /v1/auth/me?token=...` |
| Exotel WebSocket | `WS /ws/exotel` |
| App WebSocket | `WS /ws/screen?token=...` |
| Admin: Add Numbers | `POST /v1/admin/numbers` |
| Admin: List Users | `GET /v1/admin/users` |
| Admin: Analytics | `GET /v1/admin/analytics` |
