# Pickr + Plivo — Quick Setup Guide

This guide covers setting up Pickr with **Plivo** (recommended for Indian numbers).

---

## What Was Just Added

The backend now has a **`/ws/plivo`** endpoint that handles Plivo AudioStream WebSocket connections. It automatically:
- Decodes μ-law (PCMU) audio from Plivo
- Runs the same AI pipeline (STT → LLM → TTS)
- Encodes responses back to μ-law for Plivo
- Supports L16 (PCM) if configured in Plivo XML

---

## Step 1: Verify Backend Env

Your `.env` should have these (already added):

```env
ANTHROPIC_API_KEY=sk-ant-...
DEEPGRAM_API_KEY=dg-...
AVRS_TTS_MODEL=kokoro
AVRS_API_KEY=pickr_prod_key_2025
PLIVO_AUTH_ID=MA...
PLIVO_AUTH_TOKEN=...
```

**Start the server:**
```bash
cd /path/to/avrs
source .venv/bin/activate
uvicorn avrs.voice_api:app --host 0.0.0.0 --port 8000
```

Verify the Plivo route exists:
```bash
curl http://localhost:8000/health
# Should show: "status": "ok"
```

---

## Step 2: Buy a Plivo Indian Number

1. Go to [console.plivo.com](https://console.plivo.com/)
2. **Phone Numbers** → **Buy a Number**
3. Filter by **Country: India**
4. Buy one (e.g., `+9180460xxxxx`)

> Note: Plivo may require KYC/docs for Indian numbers. Have your business registration ready.

---

## Step 3: Create Plivo Application

1. In Plivo console, go to **Voice** → **Applications** → **Add New Application**
2. **Application Name**: `Pickr AI Screener`
3. **Application Type**: `XML Application`
4. **XML**: Paste this:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Stream streamUrl="wss://your-domain.com/ws/plivo" 
          bidirectional="true"
          audioTrack="both" />
</Response>
```

Replace `your-domain.com` with your actual domain (or ngrok URL for testing).

5. **Save**
6. Go to **Phone Numbers** → click your Indian number
7. Set **Application** to `Pickr AI Screener`

---

## Step 4: Seed the Number in Pickr Pool

```bash
curl -X POST https://your-domain.com/v1/admin/numbers \
  -H "X-API-Key: pickr_prod_key_2025" \
  -H "Content-Type: application/json" \
  -d '{"numbers":["+9180460xxxxx"],"region":"IN"}'
```

Replace `+9180460xxxxx` with your actual Plivo number.

Verify:
```bash
curl https://your-domain.com/v1/admin/numbers \
  -H "X-API-Key: pickr_prod_key_2025"
```

---

## Step 5: Build & Install Android App

```bash
cd android

# Update server URL if needed (hardcoded in Config.kt)
# const val SERVER_URL = "https://your-domain.com"

./gradlew :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

---

## Step 6: Test End-to-End

### On the Phone (Pickr App):
1. Open Pickr
2. Grant permissions (phone, contacts, notifications, call phone)
3. Set as default call screener
4. Allow overlay
5. Enter your **real** mobile number → get OTP → verify
6. App auto-assigns a Plivo virtual number
7. Tap **"Activate Forwarding"** — app dials carrier USSD code
8. Enter name/greeting → Done

### From Another Phone:
1. Call the user's **Plivo virtual number** (e.g., `+9180460xxxxx`)
2. The caller hears the AI: *"Hello, this is Pickr. Who may I say is calling?"*
3. The Pickr app shows live transcript + intent + Join/Block buttons

### Verify on Backend:
```bash
curl https://your-domain.com/v1/admin/users \
  -H "X-API-Key: pickr_prod_key_2025"
```

You should see:
- The user with `assigned_exotel_number` set
- `call_history` with the test call
- `monthly_minutes_used` incremented

---

## Troubleshooting Plivo

### "No user found for callee" in backend logs
- The Plivo number format in the pool must exactly match what Plivo sends
- Plivo typically sends `+9180460xxxxx` (with `+` and country code)
- Make sure you seeded the number with the exact same format

### Audio sounds garbled / robotic
- Plivo sends PCMU (μ-law) by default. Pickr handles this, but if you changed the XML config, verify the `audioCodec` setting.
- If you set `audioCodec="L16"` in Plivo, make sure the backend expects PCM (it does by default for L16).

### Call connects but no AI voice
- Check backend logs for TTS errors
- Verify `AVRS_TTS_MODEL=kokoro` and model files exist in `models/kokoro/`
- Check that `ANTHROPIC_API_KEY` is valid and has quota

### App says "Network error" during onboarding
- Verify `Config.SERVER_URL` in the Android app matches your backend
- Check that `/health` endpoint responds from the phone's browser

---

## Architecture: How Plivo Fits In

```
Caller (India) → dials +9180460xxxxx (Plivo)
                      │
                      ▼
              ┌───────────────┐
              │ Plivo (India) │ ← PSTN termination
              └───────┬───────┘
                      │ WebSocket
                      ▼
          ┌───────────────────────┐
          │ /ws/plivo (Pickr)     │
          │ • Decode μ-law        │
          │ • VAD → STT → LLM     │
          │ • TTS → Encode μ-law  │
          └───────┬───────────────┘
                  │ WebSocket
                  ▼
          ┌───────────────┐
          │ Android App   │ ← Live transcript + controls
          └───────────────┘
```

---

## Switching Between Exotel and Plivo

Both providers work simultaneously. The backend has:
- `/ws/exotel` — for Exotel Voicebot Applet
- `/ws/plivo` — for Plivo AudioStream

You can use whichever provider a user's number belongs to. Just make sure the number is seeded in the Pickr pool with the correct format.
