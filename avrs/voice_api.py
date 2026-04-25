"""
AVRS Voice Agent API — production-grade, ElevenLabs/Sarvam-style.

Run:
  uvicorn avrs.voice_api:app --host 0.0.0.0 --port 8000 --reload

Endpoints:
  POST   /v1/speak                        AVRS text → WAV
  POST   /v1/transcribe                   audio WAV/PCM → transcript
  POST   /v1/agent/sessions               start conversation session
  POST   /v1/agent/sessions/{id}/turn     conversation turn → WAV + metrics
  DELETE /v1/agent/sessions/{id}          end session
  GET    /v1/agents                       list available agent personas
  GET    /v1/voices                       list available voices
  POST   /v1/corpus/{agent}/build         trigger corpus pre-build
  GET    /v1/corpus/{agent}/status        corpus status
  WS     /v1/stream                       real-time streaming conversation
  GET    /v1/metrics                      system metrics
  GET    /health                          health check
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
    expose_headers=["*"],   # so JS can read X-* response headers
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

_API_KEY = os.getenv("AVRS_API_KEY", "")  # empty = dev mode (no auth)


def _verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if _API_KEY and x_api_key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


Auth = Annotated[None, Depends(_verify_api_key)]

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

_render_metrics: deque[metrics_mod.UtteranceMetrics] = deque(maxlen=500)
_corpus_status: dict[str, str] = {}

# Rolling log of TTS-rendered sentences per agent (persists across calls in-process).
# Used to surface corpus addition candidates in the summary.
_tts_phrase_log: dict[str, Counter] = {}

# Regex to detect "too dynamic" phrases: contains IDs, amounts, phone numbers etc.
_DYNAMIC_RE = re.compile(
    r'\b\d{4,}\b'           # long numbers (IDs, amounts, pin codes)
    r'|\b[A-Z]{2,}-\d+'     # codes like HS-2024, CN-20241130
    r'|\b\+\d{7,}'          # phone numbers
    r'|\brupees?\s+\d+'     # monetary amounts
    r'|\b\d+\s*(?:lakh|crore|percent|%)',  # financial figures
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
    # HTTP headers must be Latin-1 single-line: collapse newlines, replace Unicode
    value = " ".join(value.splitlines())
    for old, new in [
        ("—", "--"), ("–", "-"),
        ("‘", "'"), ("’", "'"),
        ("“", '"'), ("”", '"'),
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


@app.post(
    "/v1/agent/sessions",
    response_model=StartSessionResponse,
    summary="Start a new conversation session",
    tags=["Agent Sessions"],
)
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


@app.post(
    "/v1/agent/sessions/{session_id}/turn",
    summary="Send text or audio, receive synthesised audio response",
    tags=["Agent Sessions"],
)
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

    # Resolve user text — from audio upload (STT) or direct text param
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


@app.delete(
    "/v1/agent/sessions/{session_id}",
    summary="End a conversation session",
    tags=["Agent Sessions"],
)
async def end_session(session_id: str, _: Auth) -> dict:
    store = get_store()
    deleted = store.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return {"session_id": session_id, "status": "ended"}


# ---------------------------------------------------------------------------
# /v1/corpus/{agent}/build
# ---------------------------------------------------------------------------

@app.post(
    "/v1/corpus/{agent}/build",
    summary="Pre-build the static phrase corpus for an agent",
    tags=["Corpus"],
)
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
        raise HTTPException(status_code=404,
                            detail=f"Phrases file not found: {phrases_file}")

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
                phrases = [
                    line.strip()
                    for line in f
                    if line.strip() and not line.startswith("#")
                ]

            ref_audio = None
            if speaker_ref and os.path.exists(speaker_ref):
                ref_audio, _ = await asyncio.to_thread(load_audio, speaker_ref, config.sr)

            corpus = Corpus(config.corpus_dir, engine, config.voice_id)
            await asyncio.to_thread(
                corpus.build_from_phrases, phrases, ref_audio, config.sr
            )
            _corpus_status[agent] = f"ready ({len(phrases)} phrases)"
        except Exception as e:
            _corpus_status[agent] = f"error: {e}"

    asyncio.create_task(_build())
    return {"agent": agent, "status": "build_started",
            "phrases_file": phrases_file, "model": model}


@app.get(
    "/v1/corpus/{agent}/status",
    summary="Get corpus build status for an agent",
    tags=["Corpus"],
)
async def corpus_status(agent: str, _: Auth) -> dict:
    return {"agent": agent, "status": _corpus_status.get(agent, "not_built")}


@app.get(
    "/v1/corpus/{agent}/recommendations",
    summary="Suggest phrases to add to corpus based on recent TTS usage",
    tags=["Corpus"],
)
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
        # Skip phrases already in corpus (threshold 0.90 — tight, near-exact only)
        if corpus.lookup(phrase, threshold=0.90):
            continue
        # Find closest existing corpus phrase for context
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

    return {
        "agent": agent,
        "total_tts_phrases_seen": sum(phrase_log.values()),
        "unique_tts_phrases": len(phrase_log),
        "recommendations": recs[:12],
    }


class AddPhrasesRequest(BaseModel):
    phrases: list[str] = Field(..., description="Phrases to synthesise and add to corpus")
    model: str = Field(default="kokoro")


@app.post(
    "/v1/corpus/{agent}/add_phrases",
    summary="Synthesise phrases and add them to the agent corpus",
    tags=["Corpus"],
)
async def add_phrases_to_corpus(
    agent: str, req: AddPhrasesRequest, _: Auth
) -> dict:
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
        # Remove freshly-added phrases from the TTS log so they don't re-appear
        phrase_log = _tts_phrase_log.get(agent, Counter())
        for p in req.phrases:
            phrase_log.pop(p, None)

    await _build()
    log.info("Corpus add_phrases: agent=%s added=%d", agent, len(req.phrases))
    return {"agent": agent, "added": len(req.phrases), "phrases": req.phrases}


# ---------------------------------------------------------------------------
# /v1/metrics
# ---------------------------------------------------------------------------

@app.get("/v1/metrics", summary="Recent render metrics", tags=["Metrics"])
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


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
async def health() -> dict:
    stt = get_stt()
    return {
        "status": "ok",
        "tts_model": os.getenv("AVRS_TTS_MODEL", "mock"),
        "stt_available": stt.available,
        "active_sessions": len(get_store().list_sessions()),
        "agents": list(AGENTS.keys()),
    }


# ---------------------------------------------------------------------------
# /v1/stream — WebSocket real-time conversation
# ---------------------------------------------------------------------------
#
# Protocol (OpenAI Realtime API-inspired):
#
# Client → Server:
#   {"type": "config", "agent": "insurance", "model": "mock"}
#   {"type": "input_audio_buffer.append", "audio": "<base64 PCM int16 16kHz>"}
#   {"type": "input_audio_buffer.commit"}          # end of user speech
#   {"type": "input_text", "text": "..."}          # text-only input
#   {"type": "ping"}
#
# Server → Client:
#   {"type": "session.created", "session_id": "...", "agent": "...", "persona": "..."}
#   {"type": "input_audio_buffer.speech_started"}
#   {"type": "input_audio_buffer.speech_stopped"}
#   {"type": "conversation.item.input_audio_transcription.completed", "transcript": "..."}
#   {"type": "response.creating"}
#   {"type": "response.text.delta", "text": "..."}    # streaming text
#   {"type": "response.audio.delta",                  # one per segment
#       "data": "<base64 PCM int16 22050Hz>",
#       "segment_idx": 0,
#       "mode": "prerecorded|cached|tts",
#       "text": "..."}
#   {"type": "response.done", "metrics": {...}}
#   {"type": "error", "code": "...", "message": "..."}
#   {"type": "pong"}
# ---------------------------------------------------------------------------

async def _stream_avrs_response(
    ws: WebSocket,
    text_template: str,
    slots: dict,
    config: RenderConfig,
    router: "RenderRouter",
    agent_type: str = "insurance",
) -> "list":
    """Render text+slots through AVRS and stream each sentence as audio.delta immediately."""
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

        # Log TTS sentences as corpus candidates (skip dynamic/short phrases)
        if seg.mode == "tts":
            phrase = sentence.strip()
            if (15 <= len(phrase) <= 160
                    and not _DYNAMIC_RE.search(phrase)):
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
    stt_ms  = round(t.get("stt_ms",  0), 1)
    llm_ms  = round(t.get("llm_ms",  0), 1)
    tts_ms  = round(t.get("tts_ms",  m.latency_total_ms), 1)
    ttfb_ms = round(t.get("ttfb_ms", m.latency_total_ms), 1)

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
            # Pipeline breakdown
            "stt_ms":  stt_ms,
            "llm_ms":  llm_ms,
            "tts_ms":  tts_ms,
            "ttfb_ms": ttfb_ms,
        },
    })


@app.on_event("startup")
async def _preload_greeting_corpus() -> None:
    """Synthesize greeting phrases into each agent's corpus on startup."""
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

    # --- Opening greeting: agent speaks first, before any user input ---
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
                await ws.send_json({"type": "config.accepted", "agent": agent,
                                    "model": model})

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
                    user_text = await asyncio.to_thread(
                        stt.transcribe_bytes, pcm_bytes, 16000
                    )
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
                        bfsi_agent.respond, session, user_text
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

                # TTFB: commit → first audio byte (stt + llm + first segment render)
                first_seg_ms = rendered[0].latency_ms if rendered else 0.0
                ttfb_ms = stt_ms + llm_ms + first_seg_ms
                log.info("[ws] tts=%.0fms ttfb=%.0fms", tts_ms, ttfb_ms)

                timing = {
                    "stt_ms":  stt_ms,
                    "llm_ms":  llm_ms,
                    "tts_ms":  tts_ms,
                    "ttfb_ms": ttfb_ms,
                }
                await _send_metrics(ws, text_template, rendered, config, timing)

            else:
                await ws.send_json({"type": "error", "code": "unknown_message_type",
                                    "message": f"Unknown type: {msg_type!r}"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "code": "internal_error",
                                "message": str(e)})
        except Exception:
            pass
