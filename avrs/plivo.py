"""Plivo AudioStream WebSocket handler.

Plivo's AudioStream API streams bidirectional audio over WebSocket:
  • Inbound : base64-encoded audio (PCMU μ-law or L16 PCM)
  • Outbound: base64-encoded audio (same format)

This module bridges Plivo audio with the AVRS pipeline:
  8 kHz audio → decode → STT → LLM → TTS → encode → 8 kHz → Plivo

Events are broadcast to the subscriber's Android app via /ws/screen.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass, field

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from avrs.agent import AGENTS, AgentSession, BFSIAgent
from avrs.audio_utils import (
    EnergyVAD,
    float32_to_pcm,
    pcm_to_float32,
    resample,
    resample_pcm,
    ulaw_to_pcm,
    pcm_to_ulaw,
)
from avrs.config import RenderConfig
from avrs.router import RenderRouter
from avrs.stt import get_stt
from avrs import exotel as exotel_mod
from avrs import users as users_mod

log = logging.getLogger(__name__)


def _make_config(agent_type: str = "screener", voice_id: str | None = None) -> RenderConfig:
    persona = AGENTS.get(agent_type, AGENTS["insurance"])
    return RenderConfig(
        corpus_dir=persona["corpus_dir"],
        cache_dir=f"cache/{agent_type}/",
        tts_model=__import__("os").getenv("AVRS_TTS_MODEL", "mock"),
        speaker_ref=__import__("os").getenv("AVRS_SPEAKER_REF"),
        voice_id=voice_id or persona["voice_id"],
    )


# ---------------------------------------------------------------------------
# Plivo Session
# ---------------------------------------------------------------------------

@dataclass
class PlivoSession:
    """Handles a single Plivo AudioStream call."""

    call_id: str
    stream_id: str
    caller: str
    callee: str
    plivo_ws: WebSocket
    user: users_mod.User
    encoding: str = "PCMU"  # PCMU | PCMA | L16

    stt = get_stt()
    config: RenderConfig = field(default_factory=lambda: _make_config("screener"))
    router: RenderRouter = field(init=False)
    vad: EnergyVAD = field(default_factory=lambda: EnergyVAD(sr=8000))
    agent_session: AgentSession = field(init=False)
    call_active: bool = True
    call_start_time: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.router = RenderRouter(self.config)
        self.agent_session = AgentSession(
            session_id=self.call_id,
            agent_type=self.user.persona,
        )

    def _decode_media(self, payload_b64: str) -> np.ndarray | None:
        """Decode Plivo media payload to float32 audio."""
        try:
            raw = base64.b64decode(payload_b64)
        except Exception:
            return None

        if self.encoding == "L16":
            # 16-bit PCM — same as Exotel
            return pcm_to_float32(raw)
        elif self.encoding == "PCMU":
            # μ-law
            pcm = ulaw_to_pcm(raw)
            return pcm_to_float32(pcm)
        elif self.encoding == "PCMA":
            # A-law — not commonly used, treat as PCM for now
            log.warning("PCMA not fully supported, treating as PCM")
            return pcm_to_float32(raw)
        else:
            log.warning("Unknown encoding %s, treating as PCM", self.encoding)
            return pcm_to_float32(raw)

    def _encode_media(self, audio: np.ndarray) -> str:
        """Encode float32 audio to Plivo media payload (base64)."""
        pcm = float32_to_pcm(audio)
        if self.encoding == "PCMU":
            raw = pcm_to_ulaw(pcm)
        else:
            raw = pcm
        return base64.b64encode(raw).decode()

    async def run(self) -> None:
        """Main loop: process audio, run AI pipeline, send responses."""
        ok, reason = self.user.can_accept_call()
        if not ok:
            log.warning("[plivo] call rejected for user %s: %s", self.user.user_id, reason)
            await self._send_silence()
            await exotel_mod._broadcast_to_user(self.user.user_id, {
                "type": "call.end", "reason": reason, "call_sid": self.call_id,
            })
            users_mod.add_call_history(self.user.user_id, {
                "call_sid": self.call_id, "caller": self.caller, "callee": self.callee,
                "status": "rejected", "reason": reason,
            })
            return

        self.user.record_call_start()

        if self.user.screening_mode == "block_all":
            await self._speak("The person you called is not available. Goodbye.", end_call=True)
            return

        if self.user.screening_mode == "allow_all":
            await self._speak("Please hold, connecting you now.", end_call=True)
            return

        greeting = self.user.greeting or "Hello, this is Pickr. Who may I say is calling?"
        await self._speak(greeting)

        try:
            while self.call_active:
                message = await self.plivo_ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if not message.get("text"):
                    continue

                msg = json.loads(message["text"])
                event = msg.get("event", "")

                if event == "media":
                    await self._on_media(msg)
                elif event == "stop":
                    self.call_active = False
                    log.info("[plivo] call ended: %s", self.call_id)
                    await exotel_mod._broadcast_to_user(self.user.user_id, {
                        "type": "call.end", "reason": "caller_hung_up", "call_sid": self.call_id,
                    })
                    break

        except WebSocketDisconnect:
            log.info("[plivo] WebSocket disconnected: %s", self.call_id)
        except Exception as e:
            log.exception("[plivo] session error: %s", e)
        finally:
            self.call_active = False
            duration_min = (time.time() - self.call_start_time) / 60.0
            self.user.record_call_minutes(duration_min)
            users_mod._persist()
            await exotel_mod._broadcast_to_user(self.user.user_id, {
                "type": "call.end", "reason": "session_closed", "call_sid": self.call_id,
            })
            users_mod.add_call_history(self.user.user_id, {
                "call_sid": self.call_id, "caller": self.caller, "callee": self.callee,
                "status": "ended",
                "duration_sec": round(time.time() - self.call_start_time, 1),
            })

    async def _on_media(self, msg: dict) -> None:
        """Handle inbound audio from Plivo."""
        media = msg.get("media", {})
        payload_b64 = media.get("payload", "")
        if not payload_b64:
            return

        audio = self._decode_media(payload_b64)
        if audio is None:
            return

        utterance = self.vad.feed(float32_to_pcm(audio))
        if utterance is None:
            return

        log.info("[plivo] utterance detected: %.1fs", len(utterance) / 8000)

        # 8 kHz → 16 kHz for STT
        pcm_16k = resample_pcm(float32_to_pcm(utterance), 8000, 16000)

        t0 = time.perf_counter()
        transcript = await asyncio.to_thread(self.stt.transcribe_bytes, pcm_16k, 16000)
        stt_ms = (time.perf_counter() - t0) * 1000
        log.info("[plivo] stt=%.0fms → %r", stt_ms, transcript)

        if not transcript:
            return

        await exotel_mod._broadcast_to_user(self.user.user_id, {
            "type": "transcript.final", "text": transcript,
            "speaker": "caller", "call_sid": self.call_id,
        })

        t0 = time.perf_counter()
        agent_obj = BFSIAgent(self.user.persona)
        text_template, slots = await asyncio.to_thread(
            agent_obj.respond, self.agent_session, transcript,
        )
        llm_ms = (time.perf_counter() - t0) * 1000
        log.info("[plivo] llm=%.0fms", llm_ms)

        spoken, intent, action, slots = exotel_mod._parse_screener_response(text_template)

        await exotel_mod._broadcast_to_user(self.user.user_id, {
            "type": "intent", "intent": intent, "action": action, "call_sid": self.call_id,
        })
        await exotel_mod._broadcast_to_user(self.user.user_id, {
            "type": "agent.speaking", "text": spoken, "call_sid": self.call_id,
        })

        await self._speak(spoken)

        if action == "end_call":
            log.info("[plivo] ending call: %s", intent)
            self.call_active = False
            await exotel_mod._broadcast_to_user(self.user.user_id, {
                "type": "call.end", "reason": intent, "call_sid": self.call_id,
            })

    async def _speak(self, text: str, end_call: bool = False) -> None:
        """Render text via AVRS and send audio to Plivo."""
        try:
            merged, _ = self.router.render(text, None)
        except Exception as e:
            log.warning("[plivo] TTS render failed: %s", e)
            return

        # Resample to 8 kHz
        audio_8k = resample(merged.audio, merged.sr, 8000)
        payload = self._encode_media(audio_8k)

        await self.plivo_ws.send_json({
            "event": "media",
            "streamId": self.stream_id,
            "media": {"track": "outbound", "chunk": 1, "payload": payload},
        })

        if end_call:
            self.call_active = False
            await exotel_mod._broadcast_to_user(self.user.user_id, {
                "type": "call.end", "reason": "end_call", "call_sid": self.call_id,
            })

    async def _send_silence(self) -> None:
        """Send a short silence packet to keep connection alive, then hang up."""
        silence = np.zeros(800, dtype=np.float32)  # 100ms of silence at 8kHz
        payload = self._encode_media(silence)
        try:
            await self.plivo_ws.send_json({
                "event": "media",
                "streamId": self.stream_id,
                "media": {"track": "outbound", "chunk": 1, "payload": payload},
            })
        except Exception:
            pass

    async def handle_app_action(self, action: str, text: str | None = None) -> None:
        """Handle user action from Android app."""
        if action == "join":
            await self._speak("Please hold, connecting you now.", end_call=True)
        elif action == "block":
            await self._speak("The person you called is not available. Goodbye.", end_call=True)
        elif action == "message":
            await self._speak(
                "The person you called is unavailable. Please leave a message or send a text.",
                end_call=True,
            )
        elif action == "typed_message" and text:
            await self._speak(text)
            await exotel_mod._broadcast_to_user(self.user.user_id, {
                "type": "agent.speaking", "text": text, "speaker": "user", "call_sid": self.call_id,
            })


# ---------------------------------------------------------------------------
# Session store (shared with exotel)
# ---------------------------------------------------------------------------

_plivo_sessions: dict[str, PlivoSession] = {}


def get_plivo_session(call_id: str) -> PlivoSession | None:
    return _plivo_sessions.get(call_id)


def register_plivo_session(session: PlivoSession) -> None:
    _plivo_sessions[session.call_id] = session


def remove_plivo_session(call_id: str) -> None:
    _plivo_sessions.pop(call_id, None)


async def route_plivo_app_action(user_id: str, call_id: str, action: str, text: str | None = None) -> bool:
    session = get_plivo_session(call_id)
    if session and session.user.user_id == user_id:
        await session.handle_app_action(action, text)
        return True
    return False
