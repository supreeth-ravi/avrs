from __future__ import annotations

import os
import re
import time

import numpy as np

from avrs.config import MergedAudio, RenderConfig, RenderedSegment, Segment
from avrs.corpus import Corpus
from avrs.tts import get_engine
from avrs import merger, parser, utils

# Split on sentence-ending punctuation followed by whitespace or end-of-string.
_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+')


class RenderRouter:
    def __init__(self, config: RenderConfig) -> None:
        self.config = config
        self.engine = get_engine(config.tts_model)
        os.makedirs(config.corpus_dir, exist_ok=True)
        os.makedirs(config.cache_dir, exist_ok=True)
        self.corpus = Corpus(config.corpus_dir, self.engine, config.voice_id)

    def render(
        self,
        text: str,
        slots: dict | None = None,
    ) -> tuple[MergedAudio, list[RenderedSegment]]:
        segments = parser.parse_utterance(text)
        if slots:
            segments = parser.fill_slots(segments, slots)

        # Reconstruct the full spoken text after slot filling, then try corpus
        # at sentence level.  Fragment-level lookup fails because the agent wraps
        # dynamic values as {slots}, leaving only short static shards ("Your claim ",
        # " is currently ") that score below the 0.72 fuzzy threshold individually.
        # The complete sentence "Your claim CN-123 is currently under review."
        # scores ~0.82 against the corpus phrase — well above threshold.
        full_text = "".join(seg.text for seg in segments).strip()
        sentences = [s.strip() for s in _SENTENCE_RE.split(full_text) if s.strip()]
        if not sentences:
            sentences = [full_text] if full_text else []

        ref_audio = self._load_ref()

        rendered: list[RenderedSegment] = [
            self._render_unit(sentence, ref_audio) for sentence in sentences
        ]

        merged = merger.merge_segments(rendered, target_sr=self.config.sr)
        return merged, rendered

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_ref(self) -> np.ndarray | None:
        if self.config.speaker_ref and os.path.exists(self.config.speaker_ref):
            audio, _ = utils.load_audio(self.config.speaker_ref, self.config.sr)
            return audio
        return None

    def _render_unit(self, text: str, ref_audio: np.ndarray | None) -> RenderedSegment:
        """Corpus → cache → live TTS for a single text unit (typically one sentence)."""
        t_start = time.perf_counter()
        char_count = len(text)

        # 1. Corpus — fuzzy sentence-level match (threshold 0.68 for full sentences)
        corpus_path = self.corpus.lookup(text, threshold=0.68)
        if corpus_path and os.path.exists(corpus_path):
            audio, _ = utils.load_audio(corpus_path, self.config.sr)
            return RenderedSegment(audio=audio, sr=self.config.sr,
                                   mode="prerecorded",
                                   latency_ms=(time.perf_counter() - t_start) * 1000,
                                   char_count=char_count, text=text)

        tts_text = utils.clean_for_tts(text) or text

        # 2. Disk cache
        cached = self._cache_lookup(tts_text)
        if cached is not None:
            return RenderedSegment(audio=cached, sr=self.config.sr,
                                   mode="cached",
                                   latency_ms=(time.perf_counter() - t_start) * 1000,
                                   char_count=char_count, text=text)

        # 3. Live TTS
        try:
            audio, audio_sr = self.engine.synthesize(tts_text, ref_audio, self.config.sr)
        except (ValueError, RuntimeError):
            audio = np.zeros(int(0.1 * self.config.sr), dtype=np.float32)
            audio_sr = self.config.sr

        if audio_sr != self.config.sr:
            audio = utils.resample(audio, audio_sr, self.config.sr)

        peak = float(np.max(np.abs(audio)))
        if peak > 0.95:
            audio = audio * (0.95 / peak)

        self._cache_write(tts_text, audio)
        return RenderedSegment(audio=audio, sr=self.config.sr, mode="tts",
                               latency_ms=(time.perf_counter() - t_start) * 1000,
                               char_count=char_count, text=text)

    def _cache_lookup(self, text: str) -> np.ndarray | None:
        key = utils.hash_cache_key(text, self.config.voice_id,
                                   self.config.tts_model, self.config.sr)
        path = os.path.join(self.config.cache_dir, f"{key}.wav")
        if os.path.exists(path):
            audio, _ = utils.load_audio(path, self.config.sr)
            return audio
        return None

    def _cache_write(self, text: str, audio: np.ndarray) -> None:
        key = utils.hash_cache_key(text, self.config.voice_id,
                                   self.config.tts_model, self.config.sr)
        path = os.path.join(self.config.cache_dir, f"{key}.wav")
        utils.save_audio(audio, self.config.sr, path)
