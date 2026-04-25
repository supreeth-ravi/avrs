from __future__ import annotations

import io
import json
import os
from collections import deque
from dataclasses import asdict

import numpy as np
import soundfile as sf
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from avrs.config import RenderConfig
from avrs import metrics as metrics_mod
from avrs.router import RenderRouter

app = FastAPI(title="AVRS", description="Adaptive Voice Rendering System")

_metrics_store: deque[metrics_mod.UtteranceMetrics] = deque(maxlen=100)

_default_config = RenderConfig(
    tts_model=os.getenv("AVRS_TTS_MODEL", "chatterbox"),
    corpus_dir=os.getenv("AVRS_CORPUS_DIR", "corpus/"),
    cache_dir=os.getenv("AVRS_CACHE_DIR", "cache/"),
    speaker_ref=os.getenv("AVRS_SPEAKER_REF"),
)


class RenderRequest(BaseModel):
    text: str
    slots: dict = {}
    voice_id: str | None = None
    latency_budget_ms: int = 500


@app.post("/render")
async def render(req: RenderRequest) -> StreamingResponse:
    config = RenderConfig(
        tts_model=_default_config.tts_model,
        corpus_dir=_default_config.corpus_dir,
        cache_dir=_default_config.cache_dir,
        speaker_ref=_default_config.speaker_ref,
        voice_id=req.voice_id or _default_config.voice_id,
        latency_budget_ms=req.latency_budget_ms,
    )
    router = RenderRouter(config)
    merged, rendered = router.render(req.text, req.slots or None)

    m = metrics_mod.compute_metrics(req.text, rendered, merged, config)
    _metrics_store.append(m)

    buf = io.BytesIO()
    sf.write(buf, merged.audio, merged.sr, format="WAV", subtype="PCM_16")
    buf.seek(0)

    metrics_header = json.dumps(asdict(m), default=str)

    return StreamingResponse(
        buf,
        media_type="audio/wav",
        headers={"X-Render-Metrics": metrics_header},
    )


@app.get("/metrics")
async def get_metrics() -> list[dict]:
    return [asdict(m) for m in _metrics_store]


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "tts_model": _default_config.tts_model}
