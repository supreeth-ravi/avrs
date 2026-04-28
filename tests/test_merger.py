import numpy as np
import pytest

from avrs.config import MergedAudio, RenderedSegment
from avrs.merger import merge_segments


def make_seg(audio: np.ndarray, sr: int = 22050,
             mode: str = "tts") -> RenderedSegment:
    return RenderedSegment(
        audio=audio.copy(), sr=sr, mode=mode,
        latency_ms=100, char_count=10, text="test"
    )


def test_single_segment(sample_audio):
    audio, sr = sample_audio
    seg = make_seg(audio, sr)
    result = merge_segments([seg])
    assert result.audio.shape == audio.shape
    assert result.seam_metrics == []


def test_two_segments(sample_audio):
    audio, sr = sample_audio
    seg1 = RenderedSegment(audio=audio.copy(), sr=sr, mode="prerecorded",
                           latency_ms=5, char_count=10, text="Your premium")
    seg2 = RenderedSegment(audio=audio.copy(), sr=sr, mode="tts",
                           latency_ms=150, char_count=8, text="HealthShield")
    result = merge_segments([seg1, seg2])
    assert len(result.audio) < len(audio) * 2
    assert len(result.seam_metrics) == 1
    assert result.audio.max() <= 1.0
    assert result.audio.min() >= -1.0


def test_no_clipping(sample_audio):
    audio, sr = sample_audio
    loud = audio * 10
    seg1 = make_seg(loud, sr)
    seg2 = make_seg(loud, sr)
    result = merge_segments([seg1, seg2])
    assert result.audio.max() <= 1.0


def test_empty_segments():
    result = merge_segments([])
    assert len(result.audio) == 0
    assert result.seam_metrics == []


def test_three_segments(sample_audio):
    audio, sr = sample_audio
    segs = [make_seg(audio, sr) for _ in range(3)]
    result = merge_segments(segs)
    assert len(result.seam_metrics) == 2
    assert result.audio.max() <= 1.0


def test_different_sample_rates(sample_audio):
    audio, sr = sample_audio
    seg1 = make_seg(audio, sr=22050)
    short = audio[:11025]
    seg2 = make_seg(short, sr=11025)
    result = merge_segments([seg1, seg2], target_sr=22050)
    assert result.sr == 22050
    assert result.audio.max() <= 1.0
