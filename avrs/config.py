from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class RenderConfig:
    corpus_dir: str = "corpus/"
    cache_dir: str = "cache/"
    tts_model: str = "chatterbox"
    speaker_ref: str | None = None
    voice_id: str = "default"
    sr: int = 22050
    latency_budget_ms: int = 500
    cache_backend: str = "disk"
    redis_url: str = "redis://localhost:6379"
    tts_cost_per_char_usd: float = 0.000000165


@dataclass
class Segment:
    type: str
    text: str
    slot_key: str | None = None


@dataclass
class RenderedSegment:
    audio: np.ndarray
    sr: int
    mode: str
    latency_ms: float
    char_count: int
    text: str


@dataclass
class SeamMetric:
    boundary_idx: int
    pitch_delta_semitones: float
    rms_delta_db: float
    crossfade_ms: float


@dataclass
class MergedAudio:
    audio: np.ndarray
    sr: int
    seam_metrics: list[SeamMetric] = field(default_factory=list)
