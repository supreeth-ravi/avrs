from __future__ import annotations

import hashlib
import re

import librosa
import numpy as np
import soundfile as sf


def load_audio(path: str, sr: int = 22050) -> tuple[np.ndarray, int]:
    audio, file_sr = sf.read(path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if file_sr != sr:
        audio = librosa.resample(audio, orig_sr=file_sr, target_sr=sr)
    return audio, sr


def save_audio(audio: np.ndarray, sr: int, path: str) -> None:
    # Normalise to 0.95 peak before writing PCM_16 — prevents hard clipping
    peak = np.max(np.abs(audio))
    if peak > 0.95:
        audio = audio * (0.95 / peak)
    sf.write(path, audio, sr)


def resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    if orig_sr == target_sr:
        return audio
    return librosa.resample(audio, orig_sr=orig_sr, target_sr=target_sr)


def rms_normalise(audio: np.ndarray, target_dbfs: float = -18.0) -> np.ndarray:
    rms = np.sqrt(np.mean(audio ** 2))
    target_linear = 10 ** (target_dbfs / 20)
    scale = target_linear / (rms + 1e-8)
    return audio * scale


def get_f0(audio: np.ndarray, sr: int) -> float:
    try:
        f0 = librosa.yin(audio, fmin=80, fmax=400, sr=sr)
        result = float(np.nanmean(f0))
        if np.isnan(result) or result <= 0:
            return 200.0
        return result
    except Exception:
        return 200.0


def clean_for_tts(text: str) -> str:
    """Strip non-speech artifacts so TTS doesn't vocalise them."""
    # Remove any leftover SLOTS: {...} block the parser may have missed
    text = re.sub(r"SLOTS\s*:\s*\{[^}]*\}", "", text, flags=re.IGNORECASE | re.DOTALL)
    # Remove unfilled {slot_key} placeholders
    text = re.sub(r"\{[^}]+\}", "", text)
    # Strip markdown bold/italic: **x**, *x*, __x__, _x_
    text = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_\n]+)_{1,3}", r"\1", text)
    # Remove inline code backticks
    text = re.sub(r"`[^`]+`", "", text)
    # Markdown links [text](url) → text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Bare URLs → silence (TTS stumbles on them)
    text = re.sub(r"https?://\S+", "", text)
    # Currency symbols → spoken words
    text = text.replace("₹", "rupees ").replace("$", "dollars ").replace("€", "euros ").replace("£", "pounds ")
    # Percent symbol
    text = re.sub(r"(\d+)\s*%", r"\1 percent", text)
    # Remove remaining characters TTS vocalises badly (not letters/digits/punctuation)
    text = re.sub(r"[*#^~|\\<>{}]", "", text)
    # Collapse whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", " ", text)
    return text.strip()


def hash_cache_key(text: str, voice_id: str, model: str, sr: int) -> str:
    raw = f"{text}|{voice_id}|{model}|{sr}"
    return hashlib.sha256(raw.encode()).hexdigest()
