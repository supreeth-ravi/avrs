"""
AVRS Voice Agent API — production-grade, ElevenLabs/Sarvam-style.

Run:
  uvicorn avrs.voice_api:app --host 0.0.0.0 --port 8000 --reload

Endpoints:
  POST   /v1/auth/otp/request              request OTP for phone
  POST   /v1/auth/otp/verify               verify OTP + create account + auto-assign number
  GET    /v1/auth/me                       token → full user profile
  PATCH  /v1/auth/me                       update profile (name, greeting, etc.)
  POST   /v1/speak                         AVRS text → WAV
  POST   /v1/transcribe                    audio WAV/PCM → transcript
  POST   /v1/agent/sessions                start conversation session
  POST   /v1/agent/sessions/{id}/turn      conversation turn → WAV + metrics
  DELETE /v1/agent/sessions/{id}           end session
  GET    /v1/agents                        list available agent personas
  GET    /v1/voices                        list available voices
  POST   /v1/corpus/{agent}/build          trigger corpus pre-build
  GET    /v1/corpus/{agent}/status         corpus status
  WS     /v1/stream                        real-time streaming conversation
  GET    /v1/metrics                       system metrics
  GET    /health                           health check
  WS     /ws/exotel                        Exotel Voicebot Applet
  WS     /ws/screen                        Android app monitor (auth-token based)

Admin (protected by X-API-Key):
  POST   /v1/admin/numbers                 add numbers to pool
  DELETE /v1/admin/numbers/{number}        remove number from pool
  GET    /v1/admin/numbers                 list pool
  POST   /v1/admin/users/{id}/tier         set user pricing tier
  POST   /v1/admin/users/{id}/enable       enable user
  POST   /v1/admin/users/{id}/disable      disable user
  GET    /v1/admin/users                   list all users
  GET    /v1/admin/users/{id}              get single user
  DELETE /v1/admin/users/{id}              delete user
  GET    /v1/admin/analytics               usage analytics
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
import time
import uuid
from collections import Counter, deque
from dataclasses import asdict, dataclass
from typing import Annotated

log = logging.getLogger("avrs")

import numpy as np
import soundfile as sf
from dotenv import load_dotenv
from fastapi import (
    Depends, FastAPI, Header, HTTPException, Query,
    UploadFile, WebSocket, WebSocketDisconnect, status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from avrs.agent import AGENTS, AgentSession, BFSIAgent, get_store
from avrs import exotel as exotel_mod
from avrs import plivo as plivo_mod
from avrs import users as users_mod

# Anchor all relative paths to the project root (where pyproject.toml lives)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_PROJECT_ROOT)
from avrs.config import RenderConfig
from avrs import metrics as metrics_mod
from avrs.router import RenderRouter
from avrs.stt import get_stt
from avrs.utils import save_audio

load_dotenv()

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AVRS Voice Agent API",
    description=(
        "Adaptive Voice Rendering System — hybrid TTS routing for cost-sensitive "
        "BFSI voice agents. Phronetic AI / MIT Research."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

_STATIC_DIR = os.path.join(_PROJECT_ROOT, "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

@app.get("/", include_in_schema=False)
async def frontend() -> FileResponse:
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

_API_KEY = os.getenv("AVRS_API_KEY", "")


def _verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if _API_KEY and x_api_key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


Auth = Annotated[None, Depends(_verify_api_key)]


def _get_user_from_token(token: str | None) -> users_mod.User | None:
    if not token:
        return None
    return users_mod.get_user_by_token(token)


# ---------------------------------------------------------------------------
# /v1/auth  —  OTP + subscriber auth
# ---------------------------------------------------------------------------

class OtpRequest(BaseModel):
    phone_number: str = Field(..., description="User's real mobile number (e.g. +919876543210)")


class OtpRequestResponse(BaseModel):
    message: str
    expires_in: int
    # In dev mode we return the OTP so you can test without SMS
    dev_otp: str | None = None


@app.post("/v1/auth/otp/request", response_model=OtpRequestResponse, tags=["Auth"])
async def auth_otp_request(req: OtpRequest) -> OtpRequestResponse:
    """Request an OTP. In production this sends an SMS. For MVP the OTP is returned."""
    try:
        otp, expires = users_mod.generate_otp(req.phone_number)
    except ValueError as e:
        raise HTTPException(status_code=429, detail=str(e))

    # TODO: integrate Twilio / Exotel SMS here
    # For MVP we return the OTP in the response so testing works without SMS
    return OtpRequestResponse(
        message="OTP sent to your phone number",
        expires_in=users_mod.OTP_EXPIRY_SECONDS,
        dev_otp=otp,
    )


class OtpVerifyRequest(BaseModel):
    phone_number: str
    otp: str
    name: str = Field(default="", description="Display name (optional)")


class OtpVerifyResponse(BaseModel):
    user_id: str
    auth_token: str
    phone_number: str
    assigned_exotel_number: str | None = None
    onboarding_step: str
    message: str


@app.post("/v1/auth/otp/verify", response_model=OtpVerifyResponse, tags=["Auth"])
async def auth_otp_verify(req: OtpVerifyRequest) -> OtpVerifyResponse:
    """Verify OTP, create account, and auto-assign a virtual number from the pool."""
    if not users_mod.verify_otp(req.phone_number, req.otp):
        raise HTTPException(status_code=401, detail="Invalid or expired OTP")

    # Check if user already exists
    existing = users_mod.get_user_by_phone(req.phone_number)
    if existing:
        return OtpVerifyResponse(
            user_id=existing.user_id,
            auth_token=existing.auth_token,
            phone_number=existing.phone_number,
            assigned_exotel_number=existing.assigned_exotel_number,
            onboarding_step=existing.onboarding_step,
            message="Welcome back!",
        )

    # Create new user
    try:
        user = users_mod.create_user(req.phone_number, req.name)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Auto-assign virtual number from pool
    assigned: str | None = None
    try:
        assigned = users_mod.auto_assign_number(user.user_id, region="IN")
    except ValueError as e:
        log.warning("No virtual numbers available for new user %s: %s", user.user_id, e)

    return OtpVerifyResponse(
        user_id=user.user_id,
        auth_token=user.auth_token,
        phone_number=user.phone_number,
        assigned_exotel_number=assigned,
        onboarding_step=user.onboarding_step,
        message="Welcome to Pickr! Your virtual number is ready." if assigned else "Welcome to Pickr! A virtual number will be assigned shortly.",
    )


class MeResponse(BaseModel):
    user_id: str
    phone_number: str
    name: str
    email: str | None = None
    assigned_exotel_number: str | None = None
    greeting: str
    persona: str
    screening_mode: str
    enabled: bool
    pricing_tier: str
    monthly_minutes_limit: int
    monthly_minutes_used: float
    onboarding_complete: bool
    onboarding_step: str
    settings: dict


@app.get("/v1/auth/me", response_model=MeResponse, tags=["Auth"])
async def auth_me(token: str = Query(..., description="Auth token")) -> MeResponse:
    user = _get_user_from_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return MeResponse(
        user_id=user.user_id,
        phone_number=user.phone_number,
        name=user.name,
        email=user.email,
        assigned_exotel_number=user.assigned_exotel_number,
        greeting=user.greeting,
        persona=user.persona,
        screening_mode=user.screening_mode,
        enabled=user.enabled,
        pricing_tier=user.pricing_tier,
        monthly_minutes_limit=user.monthly_minutes_limit,
        monthly_minutes_used=round(user.monthly_minutes_used, 1),
        onboarding_complete=user.onboarding_complete,
        onboarding_step=user.onboarding_step,
        settings=user.settings,
    )


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    email: str | None = None
    greeting: str | None = None
    screening_mode: str | None = None
    persona: str | None = None
    language: str | None = None
    timezone: str | None = None
    settings: dict | None = None


@app.patch("/v1/auth/me", tags=["Auth"])
async def auth_update_me(token: str = Query(...), req: UpdateProfileRequest = ...) -> dict:
    user = _get_user_from_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")

    fields = {}
    for field in ["name", "email", "greeting", "screening_mode", "persona", "language", "timezone", "settings"]:
        val = getattr(req, field, None)
        if val is not None:
            fields[field] = val

    if fields:
        users_mod.update_user(user.user_id, **fields)
    return {"status": "updated", "fields": list(fields.keys())}


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

_render_metrics: deque[metrics_mod.UtteranceMetrics] = deque(maxlen=500)
_corpus_status: dict[str, str] = {}

_tts_phrase_log: dict[str, Counter] = {}

_DYNAMIC_RE = re.compile(
    r'\b\d{4,}\b'
    r'|\b[A-Z]{2,}-\d+'
    r'|\b\+\d{7,}'
    r'|\brupees?\s+\d+'
    r'|\b\d+\s*(?:lakh|crore|percent|%)',
    re.IGNORECASE,
)


def _make_config(
    agent_type: str = "insurance",
    voice_id: str | None = None,
    model: str = "mock",
    ref: str | None = None,
) -> RenderConfig:
    persona = AGENTS.get(agent_type, AGENTS["insurance"])
    return RenderConfig(
        corpus_dir=persona["corpus_dir"],
        cache_dir=f"cache/{agent_type}/",
        tts_model=os.getenv("AVRS_TTS_MODEL", model),
        speaker_ref=ref or os.getenv("AVRS_SPEAKER_REF"),
        voice_id=voice_id or persona["voice_id"],
    )


def _header_safe(value: str) -> str:
    value = " ".join(value.splitlines())
    for old, new in [
        ("—", "--"), ("–", "-"),
        ("‘", "'"), ("'", "'"),
        (""", '"'), (""", '"'),
        ("₹", "Rs."),
    ]:
        value = value.replace(old, new)
    return value.encode("latin-1", errors="replace").decode("latin-1")


def _render_to_wav_bytes(text: str, slots: dict, config: RenderConfig) -> tuple[bytes, metrics_mod.UtteranceMetrics]:
    router = RenderRouter(config)
    merged, rendered = router.render(text, slots or None)
    m = metrics_mod.compute_metrics(text, rendered, merged, config)
    _render_metrics.append(m)

    buf = io.BytesIO()
    sf.write(buf, merged.audio, merged.sr, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return buf.read(), m


# ---------------------------------------------------------------------------
# /v1/speak
# ---------------------------------------------------------------------------

class SpeakRequest(BaseModel):
    text: str = Field(..., description="Text to synthesise. Use {slot_key} for dynamic values.")
    slots: dict = Field(default={}, description="Slot values for {slot_key} placeholders")
    agent: str = Field(default="insurance", description="Agent persona (insurance|banking|payments)")
    voice_id: str | None = None
    model: str = Field(default="mock", description="TTS model (mock|chatterbox|kokoro)")
    speaker_ref: str | None = Field(default=None, description="Path to speaker reference WAV")


@app.post("/v1/speak", summary="AVRS text-to-speech", tags=["Speech"])
async def speak(req: SpeakRequest, _: Auth) -> StreamingResponse:
    config = _make_config(req.agent, req.voice_id, req.model, req.speaker_ref)
    wav_bytes, m = await asyncio.to_thread(_render_to_wav_bytes, req.text, req.slots, config)

    return StreamingResponse(
        io.BytesIO(wav_bytes),
        media_type="audio/wav",
        headers={
            "X-AVRS-Cost-Reduction-Pct": str(m.cost_reduction_pct),
            "X-AVRS-TTS-Chars-Pct": str(m.tts_chars_pct),
            "X-AVRS-Latency-Ms": str(m.latency_total_ms),
            "X-AVRS-Segments": str(m.segments),
            "X-AVRS-Metrics": json.dumps(asdict(m), default=str),
        },
    )


# ---------------------------------------------------------------------------
# /v1/transcribe
# ---------------------------------------------------------------------------

@app.post("/v1/transcribe", summary="Audio to text (Whisper)", tags=["Speech"])
async def transcribe(
    _: Auth,
    file: UploadFile | None = None,
    sample_rate: int = Query(default=16000),
) -> dict:
    stt = get_stt()
    if file:
        data = await file.read()
        transcript = await asyncio.to_thread(stt.transcribe_wav_bytes, data)
    else:
        raise HTTPException(status_code=400, detail="Provide audio file via multipart upload")
    return {"transcript": transcript, "model": "faster-whisper-base"}


# ---------------------------------------------------------------------------
# /v1/agents
# ---------------------------------------------------------------------------

@app.get("/v1/agents", summary="List agent personas", tags=["Agents"])
async def list_agents(_: Auth) -> list[dict]:
    return [
        {
            "id": agent_id,
            "name": cfg["name"],
            "company": cfg["company"],
            "domain": cfg["domain"],
            "voice_id": cfg["voice_id"],
        }
        for agent_id, cfg in AGENTS.items()
    ]


@app.get("/v1/voices", summary="List available voices", tags=["Agents"])
async def list_voices(_: Auth) -> list[dict]:
    voices = []
    for agent_id, cfg in AGENTS.items():
        voices.append({
            "voice_id": cfg["voice_id"],
            "name": cfg["name"],
            "agent": agent_id,
            "corpus_ready": _corpus_status.get(agent_id, "not_built"),
        })
    return voices


# ---------------------------------------------------------------------------
# /v1/agent/sessions
# ---------------------------------------------------------------------------

class StartSessionRequest(BaseModel):
    agent: str = Field(default="insurance", description="Agent persona")
    voice_id: str | None = None
    model: str = Field(default="mock")


class StartSessionResponse(BaseModel):
    session_id: str
    agent: str
    persona_name: str
    company: str
    ws_url: str


@app.post("/v1/agent/sessions", response_model=StartSessionResponse, tags=["Agent Sessions"])
async def start_session(req: StartSessionRequest, _: Auth) -> StartSessionResponse:
    if req.agent not in AGENTS:
        raise HTTPException(status_code=400, detail=f"Unknown agent: {req.agent!r}")

    store = get_store()
    session = store.create(req.agent)
    persona = AGENTS[req.agent]

    return StartSessionResponse(
        session_id=session.session_id,
        agent=req.agent,
        persona_name=persona["name"],
        company=persona["company"],
        ws_url=f"ws://localhost:8000/v1/stream?session_id={session.session_id}",
    )


class TurnRequest(BaseModel):
    text: str | None = Field(default=None, description="User text (alternative to audio upload)")
    model: str = Field(default="mock")
    speaker_ref: str | None = None


@app.post("/v1/agent/sessions/{session_id}/turn", tags=["Agent Sessions"])
async def agent_turn(
    session_id: str,
    _: Auth,
    text: str | None = None,
    model: str = "kokoro",
    speaker_ref: str | None = None,
    audio: UploadFile | None = None,
) -> StreamingResponse:
    store = get_store()
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")

    user_text: str | None = text
    stt_transcript: str = ""

    if audio is not None:
        stt = get_stt()
        if not stt.available:
            raise HTTPException(status_code=503, detail="STT unavailable — install faster-whisper")
        audio_bytes = await audio.read()
        log.info("[turn] STT: received %d bytes audio", len(audio_bytes))
        t_stt = time.perf_counter()
        stt_transcript = await asyncio.to_thread(stt.transcribe_wav_bytes, audio_bytes)
        stt_ms = (time.perf_counter() - t_stt) * 1000
        log.info("[turn] STT: %.0fms → %r", stt_ms, stt_transcript)
        if not stt_transcript:
            raise HTTPException(status_code=422, detail="STT returned empty transcript — is there speech in the audio?")
        user_text = stt_transcript

    if not user_text:
        raise HTTPException(status_code=400, detail="Provide 'text' param or upload 'audio' file")

    log.info("[turn] session=%s user=%r", session_id, user_text)

    try:
        agent = BFSIAgent(session.agent_type)
    except EnvironmentError as e:
        raise HTTPException(status_code=503, detail=str(e))

    t_agent = time.perf_counter()
    text_template, slots = await asyncio.to_thread(agent.respond, session, user_text)
    agent_ms = (time.perf_counter() - t_agent) * 1000
    log.info("[turn] agent=%.0fms template=%r slots=%s", agent_ms, text_template[:80], slots)

    config = _make_config(session.agent_type, model=model, ref=speaker_ref)

    t_render = time.perf_counter()
    wav_bytes, m = await asyncio.to_thread(_render_to_wav_bytes, text_template, slots, config)
    render_ms = (time.perf_counter() - t_render) * 1000
    log.info(
        "[turn] render=%.0fms segments=%d prerecorded=%.0f%% cached=%.0f%% tts=%.0f%% cost_reduction=%.1f%%",
        render_ms, m.segments, m.prerecorded_pct, m.cached_pct, m.tts_chars_pct, m.cost_reduction_pct,
    )

    filled_response = text_template
    for key, val in (slots or {}).items():
        filled_response = filled_response.replace(f"{{{key}}}", str(val))

    return StreamingResponse(
        io.BytesIO(wav_bytes),
        media_type="audio/wav",
        headers={
            "X-Session-Id": session_id,
            "X-Transcript": _header_safe(user_text),
            "X-STT-Used": "true" if audio is not None else "false",
            "X-Agent-Response": _header_safe(filled_response),
            "X-Agent-Template": _header_safe(text_template),
            "X-AVRS-Cost-Reduction-Pct": str(m.cost_reduction_pct),
            "X-AVRS-Latency-Ms": str(m.latency_total_ms),
            "X-AVRS-Metrics": json.dumps(asdict(m), default=str),
        },
    )


@app.delete("/v1/agent/sessions/{session_id}", tags=["Agent Sessions"])
async def end_session(session_id: str, _: Auth) -> dict:
    store = get_store()
    deleted = store.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return {"session_id": session_id, "status": "ended"}


# ---------------------------------------------------------------------------
# /v1/corpus
# ---------------------------------------------------------------------------

@app.post("/v1/corpus/{agent}/build", tags=["Corpus"])
async def build_corpus(
    agent: str,
    _: Auth,
    model: str = Query(default="mock"),
    speaker_ref: str | None = Query(default=None),
) -> dict:
    if agent not in AGENTS:
        raise HTTPException(status_code=400, detail=f"Unknown agent: {agent!r}")

    phrases_file = f"corpus_data/{agent}_phrases.txt"
    if not os.path.exists(phrases_file):
        raise HTTPException(status_code=404, detail=f"Phrases file not found: {phrases_file}")

    async def _build() -> None:
        _corpus_status[agent] = "building"
        try:
            from avrs.tts import get_engine
            from avrs.corpus import Corpus
            from avrs.utils import load_audio

            engine = get_engine(model)
            config = _make_config(agent, model=model, ref=speaker_ref)
            os.makedirs(config.corpus_dir, exist_ok=True)

            with open(phrases_file) as f:
                phrases = [line.strip() for line in f if line.strip() and not line.startswith("#")]

            ref_audio = None
            if speaker_ref and os.path.exists(speaker_ref):
                ref_audio, _ = await asyncio.to_thread(load_audio, speaker_ref, config.sr)

            corpus = Corpus(config.corpus_dir, engine, config.voice_id)
            await asyncio.to_thread(corpus.build_from_phrases, phrases, ref_audio, config.sr)
            _corpus_status[agent] = f"ready ({len(phrases)} phrases)"
        except Exception as e:
            _corpus_status[agent] = f"error: {e}"

    asyncio.create_task(_build())
    return {"agent": agent, "status": "build_started", "phrases_file": phrases_file, "model": model}


@app.get("/v1/corpus/{agent}/status", tags=["Corpus"])
async def corpus_status(agent: str, _: Auth) -> dict:
    return {"agent": agent, "status": _corpus_status.get(agent, "not_built")}


@app.get("/v1/corpus/{agent}/recommendations", tags=["Corpus"])
async def corpus_recommendations(agent: str, _: Auth) -> dict:
    if agent not in AGENTS:
        raise HTTPException(status_code=400, detail=f"Unknown agent: {agent!r}")

    phrase_log = _tts_phrase_log.get(agent, Counter())
    if not phrase_log:
        return {"agent": agent, "total_tts_phrases_seen": 0, "recommendations": []}

    config = _make_config(agent)
    from avrs.corpus import Corpus
    from avrs.tts import get_engine
    corpus = Corpus(config.corpus_dir, get_engine("mock"), config.voice_id)

    recs = []
    for phrase, freq in phrase_log.most_common(60):
        if corpus.lookup(phrase, threshold=0.90):
            continue
        best_ratio, best_match = 0.0, ""
        import difflib
        for key in corpus._index:
            r = difflib.SequenceMatcher(None, phrase.lower(), key).ratio()
            if r > best_ratio:
                best_ratio, best_match = r, corpus._index[key]["text"]
        recs.append({
            "text": phrase,
            "frequency": freq,
            "char_count": len(phrase),
            "impact_score": freq * len(phrase),
            "nearest_corpus": best_match if best_ratio >= 0.40 else None,
            "nearest_ratio": round(best_ratio, 2),
        })

    recs.sort(key=lambda x: -x["impact_score"])
    return {"agent": agent, "total_tts_phrases_seen": sum(phrase_log.values()),
            "unique_tts_phrases": len(phrase_log), "recommendations": recs[:12]}


class AddPhrasesRequest(BaseModel):
    phrases: list[str] = Field(..., description="Phrases to synthesise and add to corpus")
    model: str = Field(default="kokoro")


@app.post("/v1/corpus/{agent}/add_phrases", tags=["Corpus"])
async def add_phrases_to_corpus(agent: str, req: AddPhrasesRequest, _: Auth) -> dict:
    if agent not in AGENTS:
        raise HTTPException(status_code=400, detail=f"Unknown agent: {agent!r}")
    if not req.phrases:
        raise HTTPException(status_code=400, detail="No phrases provided")

    config = _make_config(agent, model=req.model)

    async def _build() -> None:
        from avrs.corpus import Corpus
        from avrs.tts import get_engine
        engine = get_engine(req.model)
        corpus = Corpus(config.corpus_dir, engine, config.voice_id)
        await asyncio.to_thread(corpus.build_from_phrases, req.phrases, None, config.sr)
        phrase_log = _tts_phrase_log.get(agent, Counter())
        for p in req.phrases:
            phrase_log.pop(p, None)

    await _build()
    log.info("Corpus add_phrases: agent=%s added=%d", agent, len(req.phrases))
    return {"agent": agent, "added": len(req.phrases), "phrases": req.phrases}


# ---------------------------------------------------------------------------
# /v1/metrics & /health
# ---------------------------------------------------------------------------

@app.get("/v1/metrics", tags=["Metrics"])
async def get_metrics(_: Auth) -> dict:
    items = [asdict(m) for m in _render_metrics]
    if not items:
        return {"count": 0, "items": [], "summary": {}}

    avg_reduction = sum(m["cost_reduction_pct"] for m in items) / len(items)
    avg_latency = sum(m["latency_total_ms"] for m in items) / len(items)

    return {
        "count": len(items),
        "summary": {
            "avg_cost_reduction_pct": round(avg_reduction, 2),
            "avg_latency_ms": round(avg_latency, 2),
        },
        "items": items[-50:],
    }


@app.get("/health", tags=["System"])
async def health() -> dict:
    stt = get_stt()
    return {
        "status": "ok",
        "tts_model": os.getenv("AVRS_TTS_MODEL", "mock"),
        "stt_available": stt.available,
        "active_sessions": len(get_store().list_sessions()),
        "agents": list(AGENTS.keys()),
        "users": len(users_mod.list_users()),
        "available_numbers": len(users_mod.list_available_numbers()),
    }


# ---------------------------------------------------------------------------
# /v1/stream — WebSocket real-time conversation
# ---------------------------------------------------------------------------

async def _stream_avrs_response(
    ws: WebSocket,
    text_template: str,
    slots: dict,
    config: RenderConfig,
    router: "RenderRouter",
    agent_type: str = "insurance",
) -> "list":
    import avrs.parser as _parser

    segs = _parser.parse_utterance(text_template)
    if slots:
        segs = _parser.fill_slots(segs, slots)

    full_text = "".join(s.text for s in segs).strip()
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', full_text) if s.strip()]
    if not sentences:
        sentences = [full_text] if full_text else []

    ref_audio = await asyncio.to_thread(router._load_ref)
    rendered: list = []
    for idx, sentence in enumerate(sentences):
        seg = await asyncio.to_thread(router._render_unit, sentence, ref_audio)
        rendered.append(seg)

        if seg.mode == "tts":
            phrase = sentence.strip()
            if (15 <= len(phrase) <= 160 and not _DYNAMIC_RE.search(phrase)):
                log_entry = _tts_phrase_log.setdefault(agent_type, Counter())
                log_entry[phrase] += 1

        buf = io.BytesIO()
        sf.write(buf, seg.audio, seg.sr, format="WAV", subtype="PCM_16")
        await ws.send_json({
            "type": "response.audio.delta",
            "data": base64.b64encode(buf.getvalue()).decode(),
            "segment_idx": idx,
            "mode": seg.mode,
            "text": seg.text,
        })

    return rendered


async def _send_metrics(
    ws: WebSocket,
    text_template: str,
    rendered: list,
    config: RenderConfig,
    timing: dict | None = None,
) -> None:
    from avrs.merger import merge_segments
    merged = await asyncio.to_thread(merge_segments, rendered, config.sr)
    m = metrics_mod.compute_metrics(text_template, rendered, merged, config)
    _render_metrics.append(m)

    t = timing or {}
    await ws.send_json({
        "type": "response.done",
        "metrics": {
            "cost_reduction_pct": m.cost_reduction_pct,
            "tts_chars_pct": m.tts_chars_pct,
            "latency_total_ms": m.latency_total_ms,
            "segments": m.segments,
            "prerecorded_pct": m.prerecorded_pct,
            "cached_pct": m.cached_pct,
            "total_chars": m.total_chars,
            "tts_chars": m.tts_chars,
            "cost_full_tts_usd": m.cost_full_tts_usd,
            "cost_hybrid_usd": m.cost_hybrid_usd,
            "stt_ms": round(t.get("stt_ms", 0), 1),
            "llm_ms": round(t.get("llm_ms", 0), 1),
            "tts_ms": round(t.get("tts_ms", m.latency_total_ms), 1),
            "ttfb_ms": round(t.get("ttfb_ms", m.latency_total_ms), 1),
        },
    })


@app.on_event("startup")
async def _preload_greeting_corpus() -> None:
    model = os.getenv("AVRS_TTS_MODEL", "mock")
    if model == "mock":
        return
    for agent_type, persona in AGENTS.items():
        phrases = persona.get("greeting_corpus_phrases", [])
        if not phrases:
            continue
        config = _make_config(agent_type, model=model)
        try:
            from avrs.corpus import Corpus
            from avrs.tts import get_engine
            engine = get_engine(model)
            corpus = Corpus(config.corpus_dir, engine, config.voice_id)
            missing = [p for p in phrases if p.strip().lower() not in corpus._index]
            if missing:
                await asyncio.to_thread(corpus.build_from_phrases, missing, None, config.sr)
                log.info("Greeting corpus: added %d phrases for %s", len(missing), agent_type)
        except Exception as exc:
            log.warning("Greeting corpus skipped for %s: %s", agent_type, exc)


@app.websocket("/v1/stream")
async def stream(ws: WebSocket, agent: str = "insurance",
                 session_id: str | None = None,
                 api_key: str | None = None,
                 model: str = "kokoro") -> None:
    model = os.getenv("AVRS_TTS_MODEL", model)
    if _API_KEY and api_key != _API_KEY:
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws.accept()

    store = get_store()
    if session_id:
        session = store.get(session_id)
        if not session:
            await ws.send_json({"type": "error", "code": "session_not_found",
                                "message": f"Session {session_id!r} not found"})
            await ws.close()
            return
    else:
        session = store.create(agent)

    persona = AGENTS.get(session.agent_type, AGENTS["insurance"])

    await ws.send_json({
        "type": "session.created",
        "session_id": session.session_id,
        "agent": session.agent_type,
        "persona": persona["name"],
        "company": persona["company"],
    })

    if persona.get("greeting"):
        from avrs.agent import _MOCK_DB
        customer_name = _MOCK_DB["customers"]["default"]["name"]
        greeting_slots = {"customer_name": customer_name}
        config = _make_config(session.agent_type, model=model)
        router = RenderRouter(config)
        await ws.send_json({"type": "response.creating"})
        rendered = await _stream_avrs_response(
            ws, persona["greeting"], greeting_slots, config, router,
            agent_type=session.agent_type,
        )
        await _send_metrics(ws, persona["greeting"], rendered, config)

    audio_buffer = bytearray()
    is_speaking = False

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "code": "invalid_json",
                                    "message": "Expected JSON message"})
                continue

            msg_type = msg.get("type", "")

            if msg_type == "ping":
                await ws.send_json({"type": "pong"})

            elif msg_type == "config":
                agent = msg.get("agent", agent)
                model = msg.get("model", model)
                await ws.send_json({"type": "config.accepted", "agent": agent, "model": model})

            elif msg_type == "input_audio_buffer.append":
                if not is_speaking:
                    is_speaking = True
                    await ws.send_json({"type": "input_audio_buffer.speech_started"})
                audio_data = base64.b64decode(msg.get("audio", ""))
                audio_buffer.extend(audio_data)

            elif msg_type in ("input_audio_buffer.commit", "input_text"):
                is_speaking = False
                await ws.send_json({"type": "input_audio_buffer.speech_stopped"})

                t_commit = time.perf_counter()
                stt_ms = 0.0

                if msg_type == "input_text":
                    user_text = msg.get("text", "").strip()
                elif audio_buffer:
                    pcm_bytes = bytes(audio_buffer)
                    audio_buffer.clear()
                    stt = get_stt()
                    t0 = time.perf_counter()
                    user_text = await asyncio.to_thread(stt.transcribe_bytes, pcm_bytes, 16000)
                    stt_ms = (time.perf_counter() - t0) * 1000
                    log.info("[ws] stt=%.0fms → %r", stt_ms, user_text)
                else:
                    continue

                if not user_text:
                    continue

                await ws.send_json({
                    "type": "conversation.item.input_audio_transcription.completed",
                    "transcript": user_text,
                })
                await ws.send_json({"type": "response.creating"})

                try:
                    bfsi_agent = BFSIAgent(session.agent_type)
                    t0 = time.perf_counter()
                    text_template, slots = await asyncio.to_thread(
                        bfsi_agent.respond, session, user_text,
                    )
                    llm_ms = (time.perf_counter() - t0) * 1000
                    log.info("[ws] llm=%.0fms", llm_ms)
                except EnvironmentError as e:
                    await ws.send_json({"type": "error", "code": "agent_unavailable",
                                        "message": str(e)})
                    continue

                await ws.send_json({"type": "response.text.delta", "text": text_template})

                config = _make_config(session.agent_type, model=model)
                router = RenderRouter(config)
                t0 = time.perf_counter()
                rendered = await _stream_avrs_response(
                    ws, text_template, slots, config, router,
                    agent_type=session.agent_type,
                )
                tts_ms = (time.perf_counter() - t0) * 1000

                first_seg_ms = rendered[0].latency_ms if rendered else 0.0
                ttfb_ms = stt_ms + llm_ms + first_seg_ms
                log.info("[ws] tts=%.0fms ttfb=%.0fms", tts_ms, ttfb_ms)

                await _send_metrics(ws, text_template, rendered, config, {
                    "stt_ms": stt_ms, "llm_ms": llm_ms, "tts_ms": tts_ms, "ttfb_ms": ttfb_ms,
                })

            else:
                await ws.send_json({"type": "error", "code": "unknown_message_type",
                                    "message": f"Unknown type: {msg_type!r}"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "code": "internal_error", "message": str(e)})
        except Exception:
            pass


# ---------------------------------------------------------------------------
# /ws/exotel — Exotel Voicebot Applet
# ---------------------------------------------------------------------------

@app.websocket("/ws/exotel")
async def ws_exotel(ws: WebSocket, api_key: str | None = None) -> None:
    if _API_KEY and api_key != _API_KEY:
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws.accept()
    log.info("[exotel] WebSocket connected")

    call_sid = None
    session: exotel_mod.ExotelSession | None = None

    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if not message.get("text"):
                continue

            msg = json.loads(message["text"])
            event = msg.get("event", "")

            if event == "start":
                start = msg.get("start", {})
                call_sid = start.get("callSid", f"call_{uuid.uuid4().hex[:8]}")
                caller = start.get("from", "unknown")
                callee = start.get("to", "unknown")
                log.info("[exotel] call started: %s from %s to %s", call_sid, caller, callee)

                user = users_mod.get_user_by_exotel(callee)
                if not user:
                    log.warning("[exotel] no user found for callee %s — rejecting call", callee)
                    await ws.close(code=4004, reason="Unknown subscriber")
                    return

                if not user.enabled:
                    log.warning("[exotel] user %s disabled — rejecting call", user.user_id)
                    await ws.close(code=4004, reason="Subscriber disabled")
                    return

                if users_mod.is_blocked(user.user_id, caller):
                    log.info("[exotel] caller %s is blocked for user %s", caller, user.user_id)
                    await ws.send_json({"event": "media", "media": {"payload": ""}})
                    await ws.close(code=1000, reason="blocked")
                    return

                session = exotel_mod.ExotelSession(
                    call_sid=call_sid,
                    caller=caller,
                    callee=callee,
                    exotel_ws=ws,
                    user=user,
                )
                exotel_mod.register_session(session)

                await exotel_mod._broadcast_to_user(user.user_id, {
                    "type": "call.started",
                    "caller": caller,
                    "callee": callee,
                    "call_sid": call_sid,
                })

                asyncio.create_task(session.run())
                break

            elif event == "media":
                pass

    except WebSocketDisconnect:
        log.info("[exotel] disconnected before start")
    except Exception as e:
        log.exception("[exotel] pre-start error: %s", e)
    finally:
        if session and call_sid:
            exotel_mod.remove_session(call_sid)
        try:
            await ws.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# /ws/plivo — Plivo AudioStream
# ---------------------------------------------------------------------------

@app.websocket("/ws/plivo")
async def ws_plivo(ws: WebSocket, api_key: str | None = None) -> None:
    """Plivo AudioStream — bidirectional audio over WebSocket.

    Plivo connects here when a caller dials a Plivo number.
    Audio flows: Plivo → decode → STT → LLM → TTS → encode → Plivo.
    """
    if _API_KEY and api_key != _API_KEY:
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws.accept()
    log.info("[plivo] WebSocket connected")

    call_id = None
    session: plivo_mod.PlivoSession | None = None

    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if not message.get("text"):
                continue

            msg = json.loads(message["text"])
            event = msg.get("event", "")

            if event == "start":
                start = msg.get("start", {})
                call_id = start.get("callId", f"plv_{uuid.uuid4().hex[:8]}")
                stream_id = start.get("streamId", call_id)
                caller = start.get("from", "unknown")
                callee = start.get("to", "unknown")
                media_fmt = start.get("mediaFormat", {})
                encoding = media_fmt.get("encoding", "PCMU")
                log.info("[plivo] call started: %s from %s to %s (encoding=%s)", call_id, caller, callee, encoding)

                user = users_mod.get_user_by_exotel(callee)
                if not user:
                    log.warning("[plivo] no user found for callee %s — rejecting call", callee)
                    await ws.close(code=4004, reason="Unknown subscriber")
                    return

                if not user.enabled:
                    log.warning("[plivo] user %s disabled — rejecting call", user.user_id)
                    await ws.close(code=4004, reason="Subscriber disabled")
                    return

                if users_mod.is_blocked(user.user_id, caller):
                    log.info("[plivo] caller %s is blocked for user %s", caller, user.user_id)
                    await ws.close(code=1000, reason="blocked")
                    return

                session = plivo_mod.PlivoSession(
                    call_id=call_id,
                    stream_id=stream_id,
                    caller=caller,
                    callee=callee,
                    plivo_ws=ws,
                    user=user,
                    encoding=encoding,
                )
                plivo_mod.register_plivo_session(session)

                await exotel_mod._broadcast_to_user(user.user_id, {
                    "type": "call.started",
                    "caller": caller,
                    "callee": callee,
                    "call_sid": call_id,
                })

                asyncio.create_task(session.run())
                break

            elif event == "media":
                pass

    except WebSocketDisconnect:
        log.info("[plivo] disconnected before start")
    except Exception as e:
        log.exception("[plivo] pre-start error: %s", e)
    finally:
        if session and call_id:
            plivo_mod.remove_plivo_session(call_id)
        try:
            await ws.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# /v1/plivo/answer — Plivo XML answer URL
# ---------------------------------------------------------------------------

from fastapi.responses import PlainTextResponse


@app.post("/v1/plivo/answer", response_class=PlainTextResponse, tags=["Plivo"])
@app.get("/v1/plivo/answer", response_class=PlainTextResponse, tags=["Plivo"])
async def plivo_answer(
    From: str | None = None,          # noqa: N803
    To: str | None = None,            # noqa: N803
    CallUUID: str | None = None,      # noqa: N803
) -> str:
    """Return Plivo XML to start a bidirectional AudioStream.

    Configure this as the Answer URL in your Plivo dashboard:
      POST https://your-domain.com/v1/plivo/answer
    """
    # Build the WebSocket URL with API key for auth
    ws_url = f"wss://pickr.phronetic.ai/ws/plivo?api_key={_API_KEY}"

    # Plivo XML with bidirectional stream
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Stream streamUrl="{ws_url}"
          bidirectional="true"
          audioTrack="both"
          statusCallback="https://pickr.phronetic.ai/v1/plivo/status" />
</Response>"""
    return xml


@app.post("/v1/plivo/status", tags=["Plivo"])
@app.get("/v1/plivo/status", tags=["Plivo"])
async def plivo_status(
    CallUUID: str | None = None,      # noqa: N803
    CallStatus: str | None = None,    # noqa: N803
    From: str | None = None,          # noqa: N803
    To: str | None = None,            # noqa: N803
) -> dict:
    """Receive Plivo stream status callbacks (started, stopped, etc.)."""
    log.info("[plivo] status callback: call=%s status=%s from=%s to=%s",
             CallUUID, CallStatus, From, To)
    return {"status": "received"}


# ---------------------------------------------------------------------------
# /ws/screen — Android app monitor / control channel
# ---------------------------------------------------------------------------

@app.websocket("/ws/screen")
async def ws_screen(ws: WebSocket, token: str | None = None, api_key: str | None = None) -> None:
    user: users_mod.User | None = None
    if _API_KEY and api_key == _API_KEY:
        pass
    elif token:
        user = users_mod.get_user_by_token(token)
        if not user:
            await ws.close(code=4001, reason="Invalid token")
            return
    else:
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws.accept()

    user_id = user.user_id if user else "admin"
    exotel_mod.register_app_screen(user_id, ws)
    log.info("[screen] app connected user=%s", user_id)

    await ws.send_json({"type": "ready", "agent": user.persona if user else "screener"})

    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if not message.get("text"):
                continue

            try:
                msg = json.loads(message["text"])
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")

            if msg_type == "action":
                action = msg.get("action")
                call_sid = msg.get("call_sid", "")
                text = msg.get("text")
                ok = await exotel_mod.route_app_action(user_id, call_sid, action, text)
                if not ok:
                    ok = await plivo_mod.route_plivo_app_action(user_id, call_sid, action, text)
                await ws.send_json({"type": "action.ack", "action": action, "call_sid": call_sid, "ok": ok})

            elif msg_type == "ping":
                await ws.send_json({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.error("[screen] error: %s", e)
    finally:
        exotel_mod.unregister_app_screen(user_id, ws)
        log.info("[screen] app disconnected user=%s", user_id)


# ---------------------------------------------------------------------------
# Admin endpoints (protected by X-API-Key)
# ---------------------------------------------------------------------------

class AddNumbersRequest(BaseModel):
    numbers: list[str] = Field(..., description="Virtual numbers to add to pool")
    region: str = Field(default="IN")


@app.post("/v1/admin/numbers", tags=["Admin"], dependencies=[Depends(_verify_api_key)])
async def admin_add_numbers(req: AddNumbersRequest) -> dict:
    for num in req.numbers:
        users_mod.add_number_to_pool(num, req.region)
    return {"added": len(req.numbers), "region": req.region}


@app.delete("/v1/admin/numbers/{number}", tags=["Admin"], dependencies=[Depends(_verify_api_key)])
async def admin_remove_number(number: str) -> dict:
    users_mod.remove_number_from_pool(number)
    return {"removed": number}


@app.get("/v1/admin/numbers", tags=["Admin"], dependencies=[Depends(_verify_api_key)])
async def admin_list_numbers() -> dict:
    pool = users_mod.list_pool()
    available = [n for n, m in pool.items() if m.get("status") == "available"]
    assigned = [n for n, m in pool.items() if m.get("status") == "assigned"]
    return {"total": len(pool), "available": available, "assigned": assigned, "pool": pool}


@app.post("/v1/admin/users/{user_id}/tier", tags=["Admin"], dependencies=[Depends(_verify_api_key)])
async def admin_set_tier(user_id: str, tier: str = Query(...)) -> dict:
    try:
        user = users_mod.set_user_tier(user_id, tier)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"user_id": user_id, "tier": tier, "monthly_minutes_limit": user.monthly_minutes_limit}


@app.post("/v1/admin/users/{user_id}/enable", tags=["Admin"], dependencies=[Depends(_verify_api_key)])
async def admin_enable_user(user_id: str) -> dict:
    user = users_mod.update_user(user_id, enabled=True)
    return {"user_id": user_id, "enabled": user.enabled}


@app.post("/v1/admin/users/{user_id}/disable", tags=["Admin"], dependencies=[Depends(_verify_api_key)])
async def admin_disable_user(user_id: str) -> dict:
    user = users_mod.update_user(user_id, enabled=False)
    return {"user_id": user_id, "enabled": user.enabled}


@app.get("/v1/admin/users", tags=["Admin"], dependencies=[Depends(_verify_api_key)])
async def admin_list_users() -> list[dict]:
    return [u.to_dict() for u in users_mod.list_users()]


@app.get("/v1/admin/users/{user_id}", tags=["Admin"], dependencies=[Depends(_verify_api_key)])
async def admin_get_user(user_id: str) -> dict:
    user = users_mod.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user.to_dict()


@app.delete("/v1/admin/users/{user_id}", tags=["Admin"], dependencies=[Depends(_verify_api_key)])
async def admin_delete_user(user_id: str) -> dict:
    ok = users_mod.delete_user(user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": user_id, "deleted": True}


@app.get("/v1/admin/analytics", tags=["Admin"], dependencies=[Depends(_verify_api_key)])
async def admin_analytics() -> dict:
    users = users_mod.list_users()
    total_users = len(users)
    total_calls = sum(len(u.call_history) for u in users)
    total_minutes = sum(u.monthly_minutes_used for u in users)
    tier_counts = {}
    for u in users:
        tier_counts[u.pricing_tier] = tier_counts.get(u.pricing_tier, 0) + 1

    return {
        "total_users": total_users,
        "total_calls": total_calls,
        "total_minutes_used": round(total_minutes, 1),
        "tier_distribution": tier_counts,
        "available_numbers": len(users_mod.list_available_numbers()),
        "active_sessions": len(get_store().list_sessions()),
    }
