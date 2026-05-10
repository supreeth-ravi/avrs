"""Audio utilities for telephony: resampling, VAD, PCM↔WAV conversions, μ-law.

Exotel sends 8 kHz 16-bit mono PCM (slin).
Plivo sends 8 kHz μ-law (PCMU) by default, or L16 if configured.
Deepgram STT expects 16 kHz.
TTS outputs varying sample rates (mock=any, chatterbox/kokoro≈24 kHz).
All resampling is done with scipy.signal.resample_poly for speed.
"""

from __future__ import annotations

import io
import logging

import numpy as np
import soundfile as sf
from scipy import signal

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PCM ↔ float32
# ---------------------------------------------------------------------------


def pcm_to_float32(pcm_bytes: bytes) -> np.ndarray:
    """16-bit signed little-endian PCM → float32 [-1, 1]."""
    return np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0


def float32_to_pcm(audio: np.ndarray) -> bytes:
    """float32 [-1, 1] → 16-bit signed little-endian PCM bytes."""
    audio = np.clip(audio, -1.0, 1.0)
    return (audio * 32767).astype(np.int16).tobytes()


# ---------------------------------------------------------------------------
# μ-law codec (for Plivo PCMU audio)
# ---------------------------------------------------------------------------


def ulaw_to_pcm(ulaw_bytes: bytes) -> bytes:
    """μ-law (G.711) → 16-bit signed little-endian PCM."""
    import audioop
    return audioop.ulaw2lin(ulaw_bytes, 2)


def pcm_to_ulaw(pcm_bytes: bytes) -> bytes:
    """16-bit signed little-endian PCM → μ-law (G.711)."""
    import audioop
    return audioop.lin2ulaw(pcm_bytes, 2)


# ---------------------------------------------------------------------------
# Resampling
# ---------------------------------------------------------------------------


def resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Resample using polyphase filtering (fast, good quality)."""
    if orig_sr == target_sr:
        return audio
    gcd = np.gcd(orig_sr, target_sr)
    up = target_sr // gcd
    down = orig_sr // gcd
    return signal.resample_poly(audio, up, down)


def resample_pcm(pcm_bytes: bytes, orig_sr: int, target_sr: int) -> bytes:
    """Resample raw PCM bytes from orig_sr to target_sr."""
    audio = pcm_to_float32(pcm_bytes)
    audio = resample(audio, orig_sr, target_sr)
    return float32_to_pcm(audio)


# ---------------------------------------------------------------------------
# WAV helpers
# ---------------------------------------------------------------------------


def pcm_to_wav_bytes(pcm_bytes: bytes, sr: int) -> bytes:
    """Wrap raw PCM bytes in a WAV container."""
    audio = pcm_to_float32(pcm_bytes)
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return buf.read()


def wav_to_pcm_bytes(wav_bytes: bytes) -> tuple[bytes, int]:
    """Extract raw PCM bytes and sample rate from WAV data."""
    buf = io.BytesIO(wav_bytes)
    audio, sr = sf.read(buf, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return float32_to_pcm(audio), int(sr)


def array_to_wav_bytes(audio: np.ndarray, sr: int) -> bytes:
    """float32 array → WAV bytes."""
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# Simple energy-based VAD / endpointing
# ---------------------------------------------------------------------------


class EnergyVAD:
    """Lightweight energy-based voice activity detector.

    Frames are analysed every *frame_ms*.  Speech is declared when RMS exceeds
    *threshold* for at least *speech_ms*.  An utterance ends when RMS stays
    below *threshold* for at least *silence_ms*.
    """

    def __init__(
        self,
        sr: int = 8000,
        frame_ms: int = 20,
        threshold: float = 0.015,
        speech_ms: int = 300,
        silence_ms: int = 1200,
    ):
        self.sr = sr
        self.frame_size = int(sr * frame_ms / 1000)
        self.threshold = threshold
        self.speech_frames_needed = max(1, speech_ms // frame_ms)
        self.silence_frames_needed = max(1, silence_ms // frame_ms)

        self._buffer = np.array([], dtype=np.float32)
        self._speech_frames = 0
        self._silence_frames = 0
        self._in_speech = False
        self._utterance: np.ndarray | None = None

    @property
    def frame_bytes(self) -> int:
        """Bytes per frame (16-bit PCM)."""
        return self.frame_size * 2

    def feed(self, pcm_bytes: bytes) -> np.ndarray | None:
        """Feed raw PCM bytes.  Returns complete utterance audio (float32)
        when end-of-utterance is detected, otherwise None."""
        audio = pcm_to_float32(pcm_bytes)
        self._buffer = np.concatenate((self._buffer, audio))

        utterance: np.ndarray | None = None

        while len(self._buffer) >= self.frame_size:
            frame = self._buffer[: self.frame_size]
            self._buffer = self._buffer[self.frame_size :]

            rms = np.sqrt(np.mean(frame ** 2))

            if rms > self.threshold:
                self._speech_frames += 1
                self._silence_frames = 0
                if not self._in_speech and self._speech_frames >= self.speech_frames_needed:
                    self._in_speech = True
                    self._utterance = frame.copy()
                elif self._in_speech:
                    self._utterance = np.concatenate((self._utterance, frame))  # type: ignore[arg-type]
            else:
                self._silence_frames += 1
                if self._in_speech:
                    self._utterance = np.concatenate((self._utterance, frame))  # type: ignore[arg-type]
                if self._in_speech and self._silence_frames >= self.silence_frames_needed:
                    utterance = self._utterance
                    self._reset()

        return utterance

    def flush(self) -> np.ndarray | None:
        """Force-end current utterance (e.g. on call hangup)."""
        if self._in_speech and self._utterance is not None and len(self._utterance) > self.sr * 0.3:
            return self._utterance
        return None

    def _reset(self) -> None:
        self._speech_frames = 0
        self._silence_frames = 0
        self._in_speech = False
        self._utterance = None
