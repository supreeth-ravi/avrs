"""Exotel WebSocket voicebot handler.

Exotel's Voicebot Applet streams bidirectional audio over WebSocket:
  • Inbound : base64-encoded 8 kHz 16-bit mono PCM (caller → bot)
  • Outbound: base64-encoded 8 kHz 16-bit mono PCM (bot → caller)

This module bridges Exotel audio with the AVRS pipeline:
  8 kHz PCM → resample(16 kHz) → STT → LLM → TTS → resample(8 kHz) → PCM → Exotel

Events are broadcast to the SUBSCRIBER'S Android app via /ws/screen so the
user sees a live transcript and can tap Join / Block / Message.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
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
)
from avrs.config import RenderConfig
from avrs.router import RenderRouter
from avrs.stt import get_stt
from avrs import users as users_mod

log = logging.getLogger(__name__)

# ── Regex for screener response parsing ────────────────────────────────────
_INTENT_RE = re.compile(r"INTENT:\s*(\w+)", re.IGNORECASE)
_ACTION_RE = re.compile(r"ACTION:\s*(\w+)", re.IGNORECASE)
_SLOTS_RE = re.compile(r"SLOTS:\s*(\{.*\})", re.IGNORECASE)


# ── App bridge: user_id → set of connected Android WebSockets ──────────────
_user_screens: dict[str, set[WebSocket]] = {}


def _make_config(agent_type: str = "screener", voice_id: str | None = None) -> RenderConfig:
    persona = AGENTS.get(agent_type, AGENTS["insurance"])
    return RenderConfig(
        corpus_dir=persona["corpus_dir"],
        cache_dir=f"cache/{agent_type}/",
        tts_model=os.getenv("AVRS_TTS_MODEL", "mock"),
        speaker_ref=os.getenv("AVRS_SPEAKER_REF"),
        voice_id=voice_id or persona["voice_id"],
    )


def _parse_screener_response(text: str) -> tuple[str, str, str, dict]:
    intent = (_INTENT_RE.search(text) or type("", (), {"group": lambda s, n: "unknown"})()).group(1)
    action = (_ACTION_RE.search(text) or type("", (), {"group": lambda s, n: "continue"})()).group(1)
    slots_match = _SLOTS_RE.search(text)
    slots = json.loads(slots_match.group(1)) if slots_match else {}
    spoken = _INTENT_RE.sub("", _ACTION_RE.sub("", _SLOTS_RE.sub("", text))).strip()
    return spoken, intent.lower(), action.lower(), slots


async def _broadcast_to_user(user_id: str, payload: dict) -> None:
    """Send JSON event only to the specified user's connected Android apps."""
    screens = _user_screens.get(user_id)
    if not screens:
        return
    dead: list[WebSocket] = []
    for ws in list(screens):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        screens.discard(ws)


# ---------------------------------------------------------------------------
# Call session
# ---------------------------------------------------------------------------

@dataclass
class ExotelSession:
    call_sid: str
    caller: str
    callee: str          # the Exotel virtual number that was dialled
    exotel_ws: WebSocket
    user: users_mod.User  # the subscriber who owns this virtual number
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
            session_id=self.call_sid,
            agent_type=self.user.persona,
        )

    async def run(self) -> None:
        """Main loop: read Exotel messages, process audio, send responses."""
        # Rate limit check
        ok, reason = self.user.can_accept_call()
        if not ok:
            log.warning("[exotel] call rejected for user %s: %s", self.user.user_id, reason)
            await self._speak(
                "We're sorry, this line is temporarily unavailable. Please try again later.",
                intent="unavailable", action="end_call"
            )
            await _broadcast_to_user(self.user.user_id, {
                "type": "call.end",
                "reason": reason,
                "call_sid": self.call_sid,
            })
            self.call_active = False
            users_mod.add_call_history(self.user.user_id, {
                "call_sid": self.call_sid,
                "caller": self.caller,
                "callee": self.callee,
                "status": "rejected",
                "reason": reason,
            })
            return

        self.user.record_call_start()

        # Screening mode handling
        if self.user.screening_mode == "block_all":
            await self._speak("The person you called is not available. Goodbye.", intent="blocked", action="end_call")
            self.call_active = False
            await _broadcast_to_user(self.user.user_id, {
                "type": "call.end", "reason": "block_all_mode", "call_sid": self.call_sid,
            })
            return

        if self.user.screening_mode == "allow_all":
            # Just let through with a brief message
            await self._speak("Please hold, connecting you now.", intent="work", action="continue")
            self.call_active = False
            await _broadcast_to_user(self.user.user_id, {
                "type": "call.end", "reason": "allow_all_mode", "call_sid": self.call_sid,
            })
            return

        # Use the user's custom greeting
        greeting = self.user.greeting or "Hello, this is Pickr. Who may I say is calling?"
        await self._speak(greeting, intent="unknown", action="continue")

        try:
            while self.call_active:
                message = await self.exotel_ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes"):
                    continue  # Exotel sends JSON text, not binary
                if not message.get("text"):
                    continue

                msg = json.loads(message["text"])
                event = msg.get("event", "")

                if event == "media":
                    await self._on_media(msg)
                elif event == "stop":
                    self.call_active = False
                    log.info("[exotel] call ended: %s", self.call_sid)
                    await _broadcast_to_user(self.user.user_id, {
                        "type": "call.end",
                        "reason": "caller_hung_up",
                        "call_sid": self.call_sid,
                    })
                    break
                elif event == "mark":
                    pass  # ignore media stream marks

        except WebSocketDisconnect:
            log.info("[exotel] WebSocket disconnected: %s", self.call_sid)
        except Exception as e:
            log.exception("[exotel] session error: %s", e)
        finally:
            self.call_active = False
            duration_min = (time.time() - self.call_start_time) / 60.0
            self.user.record_call_minutes(duration_min)
            users_mod._persist()
            await _broadcast_to_user(self.user.user_id, {
                "type": "call.end",
                "reason": "session_closed",
                "call_sid": self.call_sid,
            })
            users_mod.add_call_history(self.user.user_id, {
                "call_sid": self.call_sid,
                "caller": self.caller,
                "callee": self.callee,
                "status": "ended",
                "duration_sec": round(time.time() - self.call_start_time, 1),
            })

    async def _on_media(self, msg: dict) -> None:
        """Handle inbound audio frame from Exotel."""
        media = msg.get("media", {})
        payload_b64 = media.get("payload", "")
        if not payload_b64:
            return

        pcm_8k = base64.b64decode(payload_b64)
        utterance = self.vad.feed(pcm_8k)

        if utterance is None:
            return

        # ── Turn detected: STT → LLM → TTS ──
        log.info("[exotel] utterance detected: %.1fs", len(utterance) / 8000)

        # 8 kHz → 16 kHz for STT
        pcm_16k = resample_pcm(float32_to_pcm(utterance), 8000, 16000)

        t0 = time.perf_counter()
        transcript = await asyncio.to_thread(self.stt.transcribe_bytes, pcm_16k, 16000)
        stt_ms = (time.perf_counter() - t0) * 1000
        log.info("[exotel] stt=%.0fms → %r", stt_ms, transcript)

        if not transcript:
            return

        # Broadcast to the OWNER's app only
        await _broadcast_to_user(self.user.user_id, {
            "type": "transcript.final",
            "text": transcript,
            "speaker": "caller",
            "call_sid": self.call_sid,
        })

        # Run screener LLM with user's persona
        t0 = time.perf_counter()
        agent_obj = BFSIAgent(self.user.persona)
        text_template, slots = await asyncio.to_thread(
            agent_obj.respond,
            self.agent_session,
            transcript,
        )
        llm_ms = (time.perf_counter() - t0) * 1000
        log.info("[exotel] llm=%.0fms", llm_ms)

        spoken, intent, action, slots = _parse_screener_response(text_template)

        # Broadcast intent/action to owner's app
        await _broadcast_to_user(self.user.user_id, {
            "type": "intent",
            "intent": intent,
            "action": action,
            "call_sid": self.call_sid,
        })
        await _broadcast_to_user(self.user.user_id, {
            "type": "agent.speaking",
            "text": spoken,
            "call_sid": self.call_sid,
        })

        # Speak response back to caller
        await self._speak(spoken, intent=intent, action=action, slots=slots)

        if action == "end_call":
            log.info("[exotel] ending call: %s", intent)
            self.call_active = False
            await _broadcast_to_user(self.user.user_id, {
                "type": "call.end",
                "reason": intent,
                "call_sid": self.call_sid,
            })

    async def _speak(
        self,
        text: str,
        intent: str = "unknown",
        action: str = "continue",
        slots: dict | None = None,
    ) -> None:
        """Render text via AVRS (corpus → cache → TTS) and send audio to Exotel."""
        try:
            merged, _ = self.router.render(text, slots)
        except Exception as e:
            log.warning("[exotel] TTS render failed: %s", e)
            return

        # Resample TTS output → 8 kHz for Exotel
        audio_8k = resample(merged.audio, merged.sr, 8000)
        pcm_8k = float32_to_pcm(audio_8k)

        payload = base64.b64encode(pcm_8k).decode()
        await self.exotel_ws.send_json({
            "event": "media",
            "media": {"payload": payload},
        })

    async def handle_app_action(self, action: str, text: str | None = None) -> None:
        """Handle user action from Android app (join, block, message, typed_message)."""
        if action == "join":
            log.info("[exotel] user joined call %s", self.call_sid)
            await self._speak("Please hold, connecting you now.", intent="work", action="continue")
            self.call_active = False
            await _broadcast_to_user(self.user.user_id, {
                "type": "call.end",
                "reason": "user_joined",
                "call_sid": self.call_sid,
            })

        elif action == "block":
            log.info("[exotel] user blocked call %s", self.call_sid)
            await self._speak("The person you called is not available. Goodbye.", intent="blocked", action="end_call")
            self.call_active = False
            await _broadcast_to_user(self.user.user_id, {
                "type": "call.end",
                "reason": "user_blocked",
                "call_sid": self.call_sid,
            })

        elif action == "message":
            log.info("[exotel] user sent message on call %s", self.call_sid)
            await self._speak(
                "The person you called is unavailable. Please leave a message or send a text.",
                intent="message",
                action="end_call",
            )
            self.call_active = False
            await _broadcast_to_user(self.user.user_id, {
                "type": "call.end",
                "reason": "user_message",
                "call_sid": self.call_sid,
            })

        elif action == "typed_message":
            if text:
                log.info("[exotel] typed message: %r", text)
                await self._speak(text, intent="user_typed", action="continue")
                await _broadcast_to_user(self.user.user_id, {
                    "type": "agent.speaking",
                    "text": text,
                    "speaker": "user",
                    "call_sid": self.call_sid,
                })


# ---------------------------------------------------------------------------
# Session store
# ---------------------------------------------------------------------------

_sessions: dict[str, ExotelSession] = {}


def get_session(call_sid: str) -> ExotelSession | None:
    return _sessions.get(call_sid)


def register_session(session: ExotelSession) -> None:
    _sessions[session.call_sid] = session


def remove_session(call_sid: str) -> None:
    _sessions.pop(call_sid, None)


# ── App screen registry (per-user) ──────────────────────────────────────────

def register_app_screen(user_id: str, ws: WebSocket) -> None:
    _user_screens.setdefault(user_id, set()).add(ws)


def unregister_app_screen(user_id: str, ws: WebSocket) -> None:
    screens = _user_screens.get(user_id)
    if screens:
        screens.discard(ws)
        if not screens:
            _user_screens.pop(user_id, None)


async def route_app_action(user_id: str, call_sid: str, action: str, text: str | None = None) -> bool:
    """Route an action from the Android app to the correct Exotel session."""
    session = get_session(call_sid)
    if session and session.user.user_id == user_id:
        await session.handle_app_action(action, text)
        return True
    return False
