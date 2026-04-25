from __future__ import annotations

import io
import logging
import os
import warnings
from typing import Protocol, runtime_checkable

import numpy as np

log = logging.getLogger(__name__)

_DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
_DEEPGRAM_PARAMS = "model=nova-2&language=en&smart_format=true&punctuate=true"


@runtime_checkable
class STTEngine(Protocol):
    available: bool

    def transcribe(self, audio: np.ndarray, sr: int = 16000) -> str: ...
    def transcribe_bytes(self, audio_bytes: bytes, sr: int = 16000) -> str: ...
    def transcribe_wav_bytes(self, wav_bytes: bytes) -> str: ...


# ---------------------------------------------------------------------------
# Deepgram (cloud, ~200ms, Nova-2)
# ---------------------------------------------------------------------------

class DeepgramSTT:
    def __init__(self, api_key: str) -> None:
        import httpx
        self._key = api_key
        self._client = httpx.Client(timeout=15.0)
        self._available = True

    @property
    def available(self) -> bool:
        return self._available

    def transcribe(self, audio: np.ndarray, sr: int = 16000) -> str:
        pcm = (audio * 32767).astype(np.int16).tobytes()
        return self.transcribe_bytes(pcm, sr)

    def transcribe_bytes(self, audio_bytes: bytes, sr: int = 16000) -> str:
        url = f"{_DEEPGRAM_URL}?{_DEEPGRAM_PARAMS}&encoding=linear16&sample_rate={sr}&channels=1"
        resp = self._client.post(
            url,
            content=audio_bytes,
            headers={
                "Authorization": f"Token {self._key}",
                "Content-Type": "audio/raw",
            },
        )
        resp.raise_for_status()
        alts = resp.json()["results"]["channels"][0]["alternatives"]
        return alts[0]["transcript"].strip() if alts else ""

    def transcribe_wav_bytes(self, wav_bytes: bytes) -> str:
        url = f"{_DEEPGRAM_URL}?{_DEEPGRAM_PARAMS}"
        resp = self._client.post(
            url,
            content=wav_bytes,
            headers={
                "Authorization": f"Token {self._key}",
                "Content-Type": "audio/wav",
            },
        )
        resp.raise_for_status()
        alts = resp.json()["results"]["channels"][0]["alternatives"]
        return alts[0]["transcript"].strip() if alts else ""


# ---------------------------------------------------------------------------
# faster-whisper (local, offline fallback)
# ---------------------------------------------------------------------------

class WhisperSTT:
    """Local speech-to-text using faster-whisper."""

    def __init__(self, model_size: str = "base") -> None:
        try:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(model_size, device="cpu", compute_type="int8")
            self._available = True
            log.info("WhisperSTT: loaded model=%s", model_size)
        except ImportError:
            warnings.warn(
                "faster-whisper not installed — STT is in mock mode. "
                "Run: pip install faster-whisper"
            )
            self._model = None
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def transcribe(self, audio: np.ndarray, sr: int = 16000) -> str:
        if not self._available:
            return "[STT unavailable — install faster-whisper]"
        import librosa
        if sr != 16000:
            audio = librosa.resample(audio, orig_sr=sr, target_sr=16000)
        audio = audio.astype(np.float32)
        segments, _ = self._model.transcribe(
            audio,
            language="en",
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

    def transcribe_bytes(self, audio_bytes: bytes, sr: int = 16000) -> str:
        audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        return self.transcribe(audio, sr)

    def transcribe_wav_bytes(self, wav_bytes: bytes) -> str:
        import soundfile as sf
        buf = io.BytesIO(wav_bytes)
        audio, sr = sf.read(buf, dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        return self.transcribe(audio, sr)


# ---------------------------------------------------------------------------
# Factory — Deepgram if key present, else Whisper
# ---------------------------------------------------------------------------

_stt_instance: DeepgramSTT | WhisperSTT | None = None


def get_stt(model_size: str = "base") -> DeepgramSTT | WhisperSTT:
    global _stt_instance
    if _stt_instance is None:
        api_key = os.getenv("DEEPGRAM_API_KEY", "").strip()
        if api_key:
            log.info("STT: using Deepgram Nova-2 (cloud)")
            _stt_instance = DeepgramSTT(api_key)
        else:
            log.info("STT: DEEPGRAM_API_KEY not set — using faster-whisper %s (offline)", model_size)
            _stt_instance = WhisperSTT(model_size)
    return _stt_instance
