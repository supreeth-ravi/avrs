import json
import os

import numpy as np
import pytest

from avrs.config import MergedAudio, RenderedSegment
from avrs.metrics import UtteranceMetrics, compute_metrics, export_csv, export_json


def _make_rendered():
    return [
        RenderedSegment(audio=np.zeros(1000, dtype=np.float32), sr=22050,
                        mode="prerecorded", latency_ms=5,
                        char_count=50, text="Your premium for"),
        RenderedSegment(audio=np.zeros(1000, dtype=np.float32), sr=22050,
                        mode="tts", latency_ms=150,
                        char_count=12, text="HealthShield Gold"),
        RenderedSegment(audio=np.zeros(1000, dtype=np.float32), sr=22050,
                        mode="prerecorded", latency_ms=5,
                        char_count=16, text="is confirmed per month"),
    ]


def test_cost_reduction(mock_config):
    rendered = _make_rendered()
    merged = MergedAudio(audio=np.zeros(3000, dtype=np.float32),
                         sr=22050, seam_metrics=[])
    m = compute_metrics("test", rendered, merged, mock_config)
    assert m.tts_chars == 12
    assert m.total_chars == 78
    assert m.cost_reduction_pct > 0
    assert m.prerecorded_pct > 0


def test_prerecorded_pct(mock_config):
    rendered = _make_rendered()
    merged = MergedAudio(audio=np.zeros(3000, dtype=np.float32),
                         sr=22050, seam_metrics=[])
    m = compute_metrics("test", rendered, merged, mock_config)
    assert abs(m.prerecorded_pct - (2 / 3 * 100)) < 1.0


def test_full_tts_zero_reduction(mock_config):
    rendered = [
        RenderedSegment(audio=np.zeros(1000, dtype=np.float32), sr=22050,
                        mode="tts", latency_ms=200,
                        char_count=40, text="Hello world"),
    ]
    merged = MergedAudio(audio=np.zeros(1000, dtype=np.float32),
                         sr=22050, seam_metrics=[])
    m = compute_metrics("test", rendered, merged, mock_config)
    assert m.cost_reduction_pct == 0.0
    assert m.tts_chars == 40


def test_json_export(tmp_path, mock_config):
    rendered = _make_rendered()
    merged = MergedAudio(audio=np.zeros(3000, dtype=np.float32),
                         sr=22050, seam_metrics=[])
    m = compute_metrics("test utterance", rendered, merged, mock_config)
    out_path = str(tmp_path / "metrics.json")
    export_json([m], out_path)
    assert os.path.exists(out_path)
    with open(out_path) as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]["utterance"] == "test utterance"
    assert "cost_reduction_pct" in data[0]


def test_csv_export(tmp_path, mock_config):
    rendered = _make_rendered()
    merged = MergedAudio(audio=np.zeros(3000, dtype=np.float32),
                         sr=22050, seam_metrics=[])
    m = compute_metrics("test utterance", rendered, merged, mock_config)
    out_path = str(tmp_path / "metrics.csv")
    export_csv([m], out_path)
    assert os.path.exists(out_path)
    with open(out_path) as f:
        content = f.read()
    assert "cost_reduction_pct" in content
