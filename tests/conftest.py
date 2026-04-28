import numpy as np
import pytest

from avrs.config import RenderConfig
from avrs.tts import MockEngine


@pytest.fixture
def mock_engine():
    return MockEngine()


@pytest.fixture
def sample_audio():
    sr = 22050
    t = np.linspace(0, 1, sr, endpoint=False)
    audio = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    return audio, sr


@pytest.fixture
def mock_config(tmp_path):
    corpus = tmp_path / "corpus"
    cache = tmp_path / "cache"
    corpus.mkdir()
    cache.mkdir()
    return RenderConfig(
        corpus_dir=str(corpus),
        cache_dir=str(cache),
        tts_model="mock",
        speaker_ref=None,
    )
