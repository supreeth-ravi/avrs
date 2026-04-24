from __future__ import annotations

import warnings
from abc import ABC, abstractmethod

import numpy as np


class TTSEngine(ABC):
    @abstractmethod
    def synthesize(
        self, text: str, ref_audio: np.ndarray | None, sr: int
    ) -> tuple[np.ndarray, int]:
        pass


class MockEngine(TTSEngine):
    def synthesize(
        self, text: str, ref_audio: np.ndarray | None, sr: int
    ) -> tuple[np.ndarray, int]:
        duration = max(len(text) * 0.06, 0.1)
        t = np.linspace(0, duration, int(duration * sr), endpoint=False)
        audio = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        return audio, sr


class ChatterboxEngine(TTSEngine):
    def __init__(self) -> None:
        try:
            from chatterbox.tts import ChatterboxTTS
            self._model = ChatterboxTTS.from_pretrained(device="cpu")
        except ImportError:
            raise ImportError(
                "ChatterboxTTS not installed. Run: pip install chatterbox-tts"
            )

    def synthesize(
        self, text: str, ref_audio: np.ndarray | None, sr: int
    ) -> tuple[np.ndarray, int]:
        import tempfile, soundfile as sf

        prompt_path = None
        if ref_audio is not None:
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            sf.write(tmp.name, ref_audio, sr)
            prompt_path = tmp.name

        wav = self._model.generate(text, audio_prompt_path=prompt_path)

        if prompt_path:
            import os; os.unlink(prompt_path)

        audio = wav.squeeze().numpy().astype(np.float32)
        model_sr = getattr(self._model, "sr", 24000)
        return audio, model_sr


class KokoroEngine(TTSEngine):
    # Search order for model files
    _MODEL_CANDIDATES = [
        ("models/kokoro/kokoro-v1.0.onnx", "models/kokoro/voices-v1.0.bin"),
        ("kokoro-v1.0.onnx", "voices-v1.0.bin"),
    ]

    def __init__(self) -> None:
        try:
            from kokoro_onnx import Kokoro
        except ImportError:
            raise ImportError("kokoro-onnx not installed. Run: pip install kokoro-onnx")

        import os
        for model_path, voices_path in self._MODEL_CANDIDATES:
            if os.path.exists(model_path) and os.path.exists(voices_path):
                self._model = Kokoro(model_path, voices_path)
                return
        raise FileNotFoundError(
            "Kokoro model files not found. Download from:\n"
            "  https://github.com/thewh1teagle/kokoro-onnx/releases\n"
            "Place kokoro-v1.0.onnx and voices-v1.0.bin in models/kokoro/"
        )

    # Voice options: if_sara (Indian female), im_nicola (Indian male),
    #                af_heart, af_bella, bf_emma, bm_george
    VOICE = "if_sara"

    def synthesize(
        self, text: str, ref_audio: np.ndarray | None, sr: int
    ) -> tuple[np.ndarray, int]:
        samples, sample_sr = self._model.create(
            text, voice=self.VOICE, speed=1.05, lang="en-us"
        )
        audio = samples.astype(np.float32)
        return audio, int(sample_sr)


def get_engine(model: str) -> TTSEngine:
    if model == "mock":
        return MockEngine()

    if model == "kokoro":
        try:
            return KokoroEngine()
        except (ImportError, FileNotFoundError, Exception) as e:
            warnings.warn(f"KokoroEngine unavailable ({e}), falling back to MockEngine.")
            return MockEngine()

    if model == "chatterbox":
        try:
            return ChatterboxEngine()
        except (ImportError, Exception) as e:
            warnings.warn(f"ChatterboxEngine unavailable ({e}), falling back to KokoroEngine.")
            try:
                return KokoroEngine()
            except Exception:
                return MockEngine()

    raise ValueError(f"Unknown TTS model: {model!r}. Choose: chatterbox, kokoro, mock.")
