from __future__ import annotations

import difflib
import json
import os
import shutil

import numpy as np

from avrs.tts import TTSEngine
from avrs.utils import load_audio, save_audio


class Corpus:
    def __init__(self, corpus_dir: str, engine: TTSEngine,
                 voice_id: str = "default") -> None:
        self.corpus_dir = corpus_dir
        self.engine = engine
        self.voice_id = voice_id
        self._index: dict[str, dict] = {}

        os.makedirs(corpus_dir, exist_ok=True)
        index_path = os.path.join(corpus_dir, "index.json")
        if os.path.exists(index_path):
            with open(index_path) as f:
                self._index = json.load(f)

    def add_audio(self, phrase: str, path: str) -> None:
        key = phrase.strip().lower()
        filename = f"{abs(hash(key))}.wav"
        dest = os.path.join(self.corpus_dir, filename)
        shutil.copy2(path, dest)

        entry: dict = {"path": dest, "text": phrase}
        try:
            from resemblyzer import VoiceEncoder, preprocess_wav
            wav = preprocess_wav(dest)
            encoder = VoiceEncoder()
            embedding = encoder.embed_utterance(wav).tolist()
            entry["embedding"] = embedding
        except Exception:
            pass

        self._index[key] = entry
        self.save_index()

    def build_from_phrases(
        self,
        phrases: list[str],
        ref_audio: np.ndarray | None = None,
        sr: int = 22050,
    ) -> None:
        os.makedirs(self.corpus_dir, exist_ok=True)
        for phrase in phrases:
            audio, audio_sr = self.engine.synthesize(phrase, ref_audio, sr)
            key = phrase.strip().lower()
            filename = f"{abs(hash(key))}.wav"
            dest = os.path.join(self.corpus_dir, filename)
            save_audio(audio, audio_sr, dest)
            self._index[key] = {"path": dest, "text": phrase}
        self.save_index()

    def lookup(self, text: str, threshold: float = 0.72) -> str | None:
        normalised = text.strip().lower()

        if normalised in self._index:
            return self._index[normalised]["path"]

        # Substring match: if corpus phrase is contained in query or vice versa
        for key, entry in self._index.items():
            if key in normalised or normalised in key:
                if len(normalised) >= 4:  # avoid tiny spurious matches
                    return entry["path"]

        best_ratio = 0.0
        best_path: str | None = None
        for key, entry in self._index.items():
            ratio = difflib.SequenceMatcher(None, normalised, key).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_path = entry["path"]

        if best_ratio >= threshold:
            return best_path
        return None

    def save_index(self) -> None:
        path = os.path.join(self.corpus_dir, "index.json")
        with open(path, "w") as f:
            json.dump(self._index, f, indent=2)
