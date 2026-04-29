#!/usr/bin/env python3
"""
AVRS Evaluation Benchmark
=========================
Produces real measurements for the research paper §5 tables:
  - Table 1: Cost reduction vs. cache warmth
  - Table 2: Render latency percentiles by tier (corpus / cache / TTS)
  - Table 3: Seam quality at segment boundaries (ΔRMS, ΔF0 post-correction)
  - Table 4: LLM response shape (template chars vs. slot chars)

Usage:
  cd /path/to/avrs
  AVRS_TTS_MODEL=kokoro uvicorn avrs.voice_api:app --port 8001 &
  python benchmark/run_benchmark.py [--sessions 50] [--turns 5] [--out benchmark/results]

The script calls the live server via HTTP — no mocking, no internal shortcuts.
All latency is wall-clock time inclusive of local network overhead (~0.5ms on loopback).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import statistics
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:8001"
ELEVENLABS_COST_PER_CHAR = 0.0003   # $0.30 / 1k chars (ElevenLabs, May 2026)

# ---------------------------------------------------------------------------
# Query templates with slot-value pools for the insurance agent.
# Slots are drawn randomly from the pools so each turn can produce a unique
# synthesis, preventing stale cache hits from prior runs.
# ---------------------------------------------------------------------------

# Queries that provide enough context for the agent to give a data-bearing response.
# Including policy/claim IDs so Claude can call tools and produce slot-filled templates.
QUERY_TEMPLATES = [
    "My claim ID is CN-20241130-442. What is my claim status?",
    "My policy ID is HS-2024-88821. What is my premium amount?",
    "Is Apollo Hospital in your network for cashless treatment?",
    "I want to file a claim for hospitalization. What documents do I need?",
    "My claim ID is CN-20241201-117. Has my claim been approved?",
    "I would like to renew my policy HS-2024-55003.",
    "My claim CN-20241110-889 was rejected. Can you help me?",
    "When does my policy HS-2024-88821 expire?",
    "I was hospitalized at Fortis Healthcare. Will I get cashless treatment?",
    "My claim ID is CN-20241205-334. What documents are still needed?",
    "Can you confirm my sum insured for policy HS-2024-55003?",
    "My premium payment for policy HS-2024-88821 failed.",
    "What is covered under my HealthShield Gold plan?",
    "I need to update my registered mobile number.",
    "Thank you, that is all I needed.",
]

# Slot value pools — drawn randomly per turn to produce varied slot values.
# Common values (e.g., "under review") will warm the cache quickly.
# Rare values (e.g., unique claim IDs) will stay in TTS tier longer.
STATUS_POOL = [
    "under review", "approved", "pending", "settled",
    "rejected", "documents required", "processing",
]
AMOUNT_POOL = [
    "5,432", "8,900", "12,750", "3,200", "7,650",
    "15,000", "4,800", "6,100", "9,975", "11,200",
]
PLAN_POOL = [
    "HealthShield Gold", "HealthShield Silver", "FamilyFirst Plus",
    "CriticalCare Elite", "Senior Protect", "MaterniPlus",
]
HOSPITAL_POOL = [
    "Apollo Hospital", "Fortis Healthcare", "Manipal Hospital",
    "AIIMS Delhi", "Narayana Health", "Max Hospital",
]
ETA_POOL = [
    "December 20", "January 5", "November 30", "February 10",
    "March 15", "December 28", "January 18",
]
CLAIM_ID_POOL = [
    f"CN-2024{random.randint(1000,9999)}-{random.randint(100,999)}"
    for _ in range(30)
]

# ---------------------------------------------------------------------------
# Data classes for results
# ---------------------------------------------------------------------------

@dataclass
class TurnResult:
    session_n: int          # cumulative session number
    turn_n: int             # turn index within session
    query: str
    template: str
    filled_response: str
    template_chars: int
    slot_chars: int
    total_chars: int
    tts_chars: int
    prerecorded_pct: float
    cached_pct: float
    tts_pct: float
    cost_reduction_pct: float
    render_latency_ms: float
    total_turn_ms: float    # wall-clock including agent + render
    segments: int
    seam_rms_deltas: list[float] = field(default_factory=list)
    seam_f0_deltas: list[float] = field(default_factory=list)


@dataclass
class MicroLatency:
    """Single segment render latency from /v1/speak."""
    tier: str        # corpus | cache | tts
    text: str
    chars: int
    latency_ms: float


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _post(path: str, **kwargs) -> requests.Response:
    r = requests.post(f"{BASE_URL}{path}", timeout=120, **kwargs)
    r.raise_for_status()
    return r


def _get(path: str, **kwargs) -> requests.Response:
    r = requests.get(f"{BASE_URL}{path}", timeout=30, **kwargs)
    r.raise_for_status()
    return r


def _delete(path: str) -> requests.Response:
    r = requests.delete(f"{BASE_URL}{path}", timeout=10)
    r.raise_for_status()
    return r


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def create_session(agent: str = "insurance") -> str:
    r = _post("/v1/agent/sessions", json={"agent": agent, "model": "kokoro"})
    return r.json()["session_id"]


def delete_session(session_id: str) -> None:
    try:
        _delete(f"/v1/agent/sessions/{session_id}")
    except Exception:
        pass


def send_turn(session_id: str, text: str) -> tuple[dict, float, float]:
    """
    Send a text turn. Returns (metrics_dict, render_latency_ms, total_ms).
    render_latency_ms comes from the server's own timer (X-AVRS-Latency-Ms).
    total_ms is wall-clock including HTTP round-trip + agent + render.
    """
    t0 = time.perf_counter()
    r = requests.post(
        f"{BASE_URL}/v1/agent/sessions/{session_id}/turn",
        params={"text": text, "model": "kokoro"},
        timeout=120,
    )
    r.raise_for_status()
    total_ms = (time.perf_counter() - t0) * 1000

    headers = r.headers
    render_ms = float(headers.get("X-AVRS-Latency-Ms", 0))
    raw_metrics = headers.get("X-AVRS-Metrics", "{}")
    try:
        metrics = json.loads(raw_metrics)
    except json.JSONDecodeError:
        metrics = {}

    metrics["_template"] = headers.get("X-Agent-Template", "")
    metrics["_filled_response"] = headers.get("X-Agent-Response", "")
    metrics["_transcript"] = headers.get("X-Transcript", "")
    return metrics, render_ms, total_ms


# ---------------------------------------------------------------------------
# Micro-benchmark: isolate tier latency via /v1/speak
# ---------------------------------------------------------------------------

def _speak(text: str, slots: dict | None = None) -> tuple[dict, float]:
    """Call /v1/speak and return (metrics, wall_ms)."""
    payload = {
        "text": text,
        "slots": slots or {},
        "agent": "insurance",
        "model": "kokoro",
    }
    t0 = time.perf_counter()
    r = _post("/v1/speak", json=payload)
    wall_ms = (time.perf_counter() - t0) * 1000
    try:
        m = json.loads(r.headers.get("X-AVRS-Metrics", "{}"))
    except Exception:
        m = {}
    return m, wall_ms


def run_micro_benchmark(n_repeats: int = 40) -> list[MicroLatency]:
    """
    Measure tier latency in isolation:
    - Corpus tier: phrases guaranteed to be in the corpus
    - Cache tier: same unique TTS phrase repeated (2nd call = cache)
    - TTS tier: unique phrases never synthesized before
    """
    results: list[MicroLatency] = []

    print(f"\n{'─'*60}")
    print("MICRO-BENCHMARK: Segment tier latency")
    print(f"{'─'*60}")

    # --- Corpus tier ---
    # These exact phrases are in corpus/insurance/index.json
    corpus_phrases = [
        "your claim is currently under review.",
        "your claim has been approved.",
        "i will be happy to help you with that.",
        "please give me a moment to check your details.",
        "thank you for your patience.",
        "i apologize for the inconvenience.",
        "i understand your concern.",
        "is there anything else i can help you with today?",
        "your policy is currently active.",
        "your premium payment was successful.",
    ]

    print(f"  Corpus tier: {n_repeats} calls across {len(corpus_phrases)} phrases...")
    for i in range(n_repeats):
        phrase = corpus_phrases[i % len(corpus_phrases)]
        m, wall_ms = _speak(phrase)
        render_ms = m.get("latency_total_ms", wall_ms)
        results.append(MicroLatency(
            tier="corpus",
            text=phrase,
            chars=len(phrase),
            latency_ms=render_ms,
        ))

    corpus_lats = [r.latency_ms for r in results if r.tier == "corpus"]
    print(f"    P50={_p50(corpus_lats):.1f}ms  P95={_p95(corpus_lats):.1f}ms  P99={_p99(corpus_lats):.1f}ms")

    # --- TTS tier (first call) and Cache tier (second call) ---
    # Use unique phrases not in corpus with slot values that are unlikely cached.
    # Craft phrases that will need synthesis.
    print(f"  TTS + Cache tier: {n_repeats} unique phrases (TTS first, cache second)...")

    unique_amounts = [str(random.randint(10000, 99999)) for _ in range(n_repeats)]
    unique_ref_ids = [f"BM{random.randint(100000, 999999)}" for _ in range(n_repeats)]

    tts_first_ms: list[float] = []
    cache_second_ms: list[float] = []

    for i in range(n_repeats):
        # Unique text — first call will always be TTS
        text = f"your reference number is {unique_ref_ids[i]} and amount is rupees {unique_amounts[i]}."

        # First call: TTS
        m1, w1 = _speak(text)
        render1 = m1.get("latency_total_ms", w1)
        results.append(MicroLatency(tier="tts_first", text=text, chars=len(text), latency_ms=render1))
        tts_first_ms.append(render1)

        # Second call: should be cache hit
        m2, w2 = _speak(text)
        render2 = m2.get("latency_total_ms", w2)
        results.append(MicroLatency(tier="cache_hit", text=text, chars=len(text), latency_ms=render2))
        cache_second_ms.append(render2)

    # Separate short / medium / long TTS by char count
    tts_results = [r for r in results if r.tier == "tts_first"]
    short_tts = [r.latency_ms for r in tts_results if r.chars < 40]
    medium_tts = [r.latency_ms for r in tts_results if 40 <= r.chars < 80]
    long_tts = [r.latency_ms for r in tts_results if r.chars >= 80]

    print(f"    TTS short   (<40c)  P50={_p50(short_tts):.0f}ms P95={_p95(short_tts):.0f}ms")
    print(f"    TTS medium (40-80c) P50={_p50(medium_tts):.0f}ms P95={_p95(medium_tts):.0f}ms")
    print(f"    TTS long    (>80c)  P50={_p50(long_tts):.0f}ms P95={_p95(long_tts):.0f}ms")
    print(f"    Cache hit           P50={_p50(cache_second_ms):.1f}ms P95={_p95(cache_second_ms):.1f}ms")

    return results


# ---------------------------------------------------------------------------
# Session benchmark: full pipeline (agent + render)
# ---------------------------------------------------------------------------

def run_session_benchmark(n_sessions: int = 30, turns_per_session: int = 5) -> list[TurnResult]:
    """
    Run n_sessions × turns_per_session full pipeline turns.
    Each turn goes through agent (Claude) + parser + router + merger.
    Results include routing distribution and cost reduction per turn.
    """
    results: list[TurnResult] = []
    session_counter = 0

    print(f"\n{'─'*60}")
    print(f"SESSION BENCHMARK: {n_sessions} sessions × {turns_per_session} turns")
    print(f"{'─'*60}")

    for sess_n in range(n_sessions):
        session_id = create_session("insurance")
        session_counter += 1

        for turn_n in range(turns_per_session):
            query = random.choice(QUERY_TEMPLATES)
            try:
                m, render_ms, total_ms = send_turn(session_id, query)
            except Exception as e:
                print(f"    [WARN] session {sess_n} turn {turn_n}: {e}")
                continue

            template = m.get("_template", "")
            filled = m.get("_filled_response", "")

            # Strip SLOTS: {...} block from template before counting
            import re
            clean_template = re.sub(
                r"\s*SLOTS\s*:\s*\{[^}]*\}", "", template,
                flags=re.IGNORECASE | re.DOTALL
            ).strip()
            # Static frame = template minus {slot_key} placeholders
            slot_pattern = re.compile(r"\{[^}]+\}")
            slot_keys = slot_pattern.findall(clean_template)
            static_frame = slot_pattern.sub("", clean_template).strip()
            template_chars = len(static_frame)
            # Slot value chars = filled length minus static frame length
            clean_filled = re.sub(
                r"\s*SLOTS\s*:\s*\{[^}]*\}", "", filled,
                flags=re.IGNORECASE | re.DOTALL
            ).strip()
            slot_chars = max(0, len(clean_filled) - template_chars)

            seam_rms = []
            seam_f0 = []
            if "seam_metrics" in m:
                for sm in m["seam_metrics"]:
                    seam_rms.append(abs(sm.get("rms_delta_db", 0)))
                    seam_f0.append(abs(sm.get("pitch_delta_semitones", 0)))

            tr = TurnResult(
                session_n=session_counter,
                turn_n=turn_n,
                query=query,
                template=template,
                filled_response=filled,
                template_chars=template_chars,
                slot_chars=slot_chars,
                total_chars=m.get("total_chars", len(filled)),
                tts_chars=m.get("tts_chars", 0),
                prerecorded_pct=m.get("prerecorded_pct", 0),
                cached_pct=m.get("cached_pct", 0),
                tts_pct=m.get("tts_pct", 0),
                cost_reduction_pct=m.get("cost_reduction_pct", 0),
                render_latency_ms=render_ms,
                total_turn_ms=total_ms,
                segments=m.get("segments", 0),
                seam_rms_deltas=seam_rms,
                seam_f0_deltas=seam_f0,
            )
            results.append(tr)

        delete_session(session_id)

        # Print per-session summary
        sess_results = [r for r in results if r.session_n == session_counter]
        if sess_results:
            eta = _mean([r.cost_reduction_pct for r in sess_results])
            lat = _mean([r.render_latency_ms for r in sess_results])
            pre = _mean([r.prerecorded_pct for r in sess_results])
            cac = _mean([r.cached_pct for r in sess_results])
            tts = _mean([r.tts_pct for r in sess_results])
            print(f"  [{sess_n+1:2d}/{n_sessions}] "
                  f"turns={len(sess_results)}  "
                  f"corpus={pre:.0f}%  cache={cac:.0f}%  tts={tts:.0f}%  "
                  f"η={eta:.1f}%  render={lat:.0f}ms")

    print(f"  Done — {len(results)} turns collected")
    return results


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyse_warmth_curve(results: list[TurnResult]) -> list[dict]:
    """
    Compute routing metrics at cumulative session checkpoints:
    sessions 1, 5, 10, 25, 50, 100, ...
    Shows how cache warmth builds over time.
    """
    checkpoints = [1, 5, 10, 20, 30, 50]
    sessions_seen = sorted(set(r.session_n for r in results))
    checkpoints = [c for c in checkpoints if c <= max(sessions_seen)]

    rows = []
    for cp in checkpoints:
        subset = [r for r in results if r.session_n <= cp]
        if not subset:
            continue
        rows.append({
            "session_count": cp,
            "n_turns": len(subset),
            "corpus_pct": _mean([r.prerecorded_pct for r in subset]),
            "cache_pct": _mean([r.cached_pct for r in subset]),
            "tts_pct": _mean([r.tts_pct for r in subset]),
            "cost_reduction_eta": _mean([r.cost_reduction_pct for r in subset]),
        })
    return rows


def analyse_latency(results: list[TurnResult], micro: list[MicroLatency]) -> dict:
    """Latency percentiles for each tier and for full turns."""

    corpus_lat = [r.latency_ms for r in micro if r.tier == "corpus"]
    cache_lat = [r.latency_ms for r in micro if r.tier == "cache_hit"]
    tts_lat = [r.latency_ms for r in micro if r.tier == "tts_first"]
    tts_short = [r.latency_ms for r in micro if r.tier == "tts_first" and r.chars < 40]
    tts_med = [r.latency_ms for r in micro if r.tier == "tts_first" and 40 <= r.chars < 80]
    tts_long = [r.latency_ms for r in micro if r.tier == "tts_first" and r.chars >= 80]
    render_lat = [r.render_latency_ms for r in results]
    total_lat = [r.total_turn_ms for r in results]

    def stats(data: list[float]) -> dict:
        if not data:
            return {"n": 0, "p50": 0, "p75": 0, "p95": 0, "p99": 0, "mean": 0}
        return {
            "n": len(data),
            "p50": _p50(data),
            "p75": _percentile(data, 75),
            "p95": _p95(data),
            "p99": _p99(data),
            "mean": _mean(data),
        }

    return {
        "corpus_hit": stats(corpus_lat),
        "cache_hit": stats(cache_lat),
        "tts_all": stats(tts_lat),
        "tts_short_under40c": stats(tts_short),
        "tts_medium_40_80c": stats(tts_med),
        "tts_long_over80c": stats(tts_long),
        "render_total": stats(render_lat),
        "turn_total_wall": stats(total_lat),
    }


def analyse_seams(results: list[TurnResult]) -> dict:
    """Aggregate seam quality across all segment boundaries."""
    all_rms = []
    all_f0 = []
    for r in results:
        all_rms.extend(r.seam_rms_deltas)
        all_f0.extend(r.seam_f0_deltas)

    def seam_stats(data: list[float], threshold: float) -> dict:
        if not data:
            return {}
        return {
            "n": len(data),
            "mean": round(_mean(data), 3),
            "std": round(statistics.stdev(data) if len(data) > 1 else 0, 3),
            "p50": round(_p50(data), 3),
            "p95": round(_p95(data), 3),
            "threshold": threshold,
            "pct_above_threshold": round(100 * sum(1 for x in data if x > threshold) / len(data), 1),
        }

    # Note: rms_delta_db is local boundary energy after global RMS normalization.
    # Large values (>6dB) indicate local energy pockets at segment edges.
    # f0_delta_semitones is pre-correction; pitch shift fires for |delta|>1.5st.
    return {
        "rms_delta_db": seam_stats(all_rms, threshold=6.0),
        "f0_delta_semitones": seam_stats(all_f0, threshold=1.5),
    }


def analyse_token_shape(results: list[TurnResult]) -> dict:
    """
    Estimate template vs. slot character split per turn.
    template_chars = static frame chars
    slot_chars     = dynamic value chars
    Both are character counts, not token counts.
    """
    tc = [r.template_chars for r in results if r.template_chars > 0]
    sc = [r.slot_chars for r in results if r.slot_chars >= 0]
    total = [r.total_chars for r in results if r.total_chars > 0]
    tts_ch = [r.tts_chars for r in results if r.tts_chars >= 0]

    return {
        "template_chars_mean": round(_mean(tc), 1) if tc else 0,
        "slot_chars_mean": round(_mean(sc), 1) if sc else 0,
        "total_chars_mean": round(_mean(total), 1) if total else 0,
        "tts_chars_mean": round(_mean(tts_ch), 1) if tts_ch else 0,
        "slot_pct_of_total": round(100 * _mean(sc) / _mean(total), 1) if total else 0,
    }


def corpus_audit() -> dict:
    """Count and characterise the actual deployed corpus."""
    import subprocess, json as _json
    try:
        with open("corpus/insurance/index.json") as f:
            index = _json.load(f)
        phrases = list(index.keys())
        lengths = [len(p) for p in phrases]
        return {
            "n_phrases": len(phrases),
            "mean_chars": round(_mean(lengths), 1),
            "min_chars": min(lengths),
            "max_chars": max(lengths),
            "sample": phrases[:5],
        }
    except FileNotFoundError:
        return {"n_phrases": 0, "error": "index.json not found"}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_json(data: dict, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"  → {path}")


def export_warmth_csv(rows: list[dict], path: str) -> None:
    if not rows:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"  → {path}")


def export_turn_csv(results: list[TurnResult], path: str) -> None:
    if not results:
        return
    scalar_fields = [
        f for f in TurnResult.__dataclass_fields__
        if f not in ("seam_rms_deltas", "seam_f0_deltas")
    ]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=scalar_fields)
        writer.writeheader()
        for r in results:
            row = {k: getattr(r, k) for k in scalar_fields}
            writer.writerow(row)
    print(f"  → {path}")


def export_micro_csv(micro: list[MicroLatency], path: str) -> None:
    if not micro:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["tier", "chars", "latency_ms"])
        writer.writeheader()
        for m in micro:
            writer.writerow({"tier": m.tier, "chars": m.chars, "latency_ms": round(m.latency_ms, 3)})
    print(f"  → {path}")


def print_paper_tables(warmth: list[dict], latency: dict, seams: dict, tokens: dict, corpus: dict) -> None:
    SEP = "─" * 72

    print(f"\n{SEP}")
    print("PAPER TABLE 1 — Cost Reduction vs. Cache Warmth")
    print(SEP)
    print(f"{'Sessions':>10} {'Turns':>6} {'Corpus%':>9} {'Cache%':>8} {'TTS%':>7} {'η (cost red%)':>14}")
    for r in warmth:
        print(f"{r['session_count']:>10} {r['n_turns']:>6} "
              f"{r['corpus_pct']:>9.1f} {r['cache_pct']:>8.1f} "
              f"{r['tts_pct']:>7.1f} {r['cost_reduction_eta']:>14.1f}")

    print(f"\n{SEP}")
    print("PAPER TABLE 2 — Latency Percentiles by Tier (ms)")
    print(SEP)
    print(f"{'Tier':<28} {'N':>5} {'P50':>7} {'P75':>7} {'P95':>7} {'P99':>7}")
    for tier, s in latency.items():
        if s.get("n", 0) == 0:
            continue
        print(f"  {tier:<26} {s['n']:>5} {s['p50']:>7.1f} {s['p75']:>7.1f} {s['p95']:>7.1f} {s['p99']:>7.1f}")

    print(f"\n{SEP}")
    print("PAPER TABLE 3 — Seam Quality at Segment Boundaries")
    print("  Note: rms_delta_db = local boundary energy after global normalization")
    print("        f0_delta = pre-correction pitch gap (correction fires at |Δ|>1.5st)")
    print(SEP)
    for metric, s in seams.items():
        if not s:
            continue
        label = "ΔRMS (dB)" if "rms" in metric else "ΔF0 (semitones)"
        thresh = s.get("threshold", 0)
        print(f"  {label}: N={s['n']}  mean={s['mean']:.2f}±{s['std']:.2f}  "
              f"P50={s['p50']:.2f}  P95={s['p95']:.2f}  "
              f">{thresh}={s['pct_above_threshold']:.1f}%")

    print(f"\n{SEP}")
    print("PAPER TABLE 4 — Response Shape (chars per turn)")
    print(SEP)
    print(f"  Total chars / turn (mean):     {tokens['total_chars_mean']:.1f}")
    print(f"  Template frame chars (mean):   {tokens['template_chars_mean']:.1f}")
    print(f"  Slot value chars (mean):       {tokens['slot_chars_mean']:.1f}")
    print(f"  TTS-synthesized chars (mean):  {tokens['tts_chars_mean']:.1f}")
    print(f"  Slot % of total:               {tokens['slot_pct_of_total']:.1f}%")

    print(f"\n{SEP}")
    print("CORPUS AUDIT")
    print(SEP)
    print(f"  Deployed corpus phrases:  {corpus['n_phrases']}")
    print(f"  Mean phrase length:       {corpus.get('mean_chars', 0):.1f} chars")
    print(f"  Char range:               {corpus.get('min_chars', 0)}–{corpus.get('max_chars', 0)}")

    print(f"\n{SEP}")


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

def _percentile(data: list[float], pct: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _p50(data: list[float]) -> float: return _percentile(data, 50)
def _p95(data: list[float]) -> float: return _percentile(data, 95)
def _p99(data: list[float]) -> float: return _percentile(data, 99)
def _mean(data: list[float]) -> float: return sum(data) / len(data) if data else 0.0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="AVRS benchmark harness")
    ap.add_argument("--sessions", type=int, default=30,
                    help="Number of conversation sessions (default: 30)")
    ap.add_argument("--turns", type=int, default=5,
                    help="Turns per session (default: 5)")
    ap.add_argument("--micro-n", type=int, default=40,
                    help="Repeats per tier in micro-benchmark (default: 40)")
    ap.add_argument("--out", default="benchmark/results",
                    help="Output path prefix (default: benchmark/results)")
    ap.add_argument("--skip-micro", action="store_true",
                    help="Skip micro-benchmark (faster)")
    ap.add_argument("--skip-sessions", action="store_true",
                    help="Skip session benchmark (use for micro-only run)")
    args = ap.parse_args()

    # Check server is up
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        r.raise_for_status()
        info = r.json()
        print(f"\nServer: {BASE_URL}")
        print(f"  TTS model: {info.get('tts_model', '?')}")
        print(f"  STT available: {info.get('stt_available', '?')}")
        print(f"  Agents: {info.get('agents', [])}")
    except Exception as e:
        print(f"\nERROR: Cannot reach server at {BASE_URL}: {e}")
        print("Start the server first:  uvicorn avrs.voice_api:app --port 8001")
        sys.exit(1)

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_prefix = f"{args.out}_{ts}"

    # --- Corpus audit ---
    print("\n[1/4] Corpus audit...")
    corpus = corpus_audit()
    print(f"  Corpus: {corpus['n_phrases']} phrases, "
          f"mean {corpus.get('mean_chars', 0):.1f} chars")

    # --- Micro-benchmark ---
    micro: list[MicroLatency] = []
    if not args.skip_micro:
        print("\n[2/4] Micro-benchmark (tier latency isolation)...")
        micro = run_micro_benchmark(n_repeats=args.micro_n)
        export_micro_csv(micro, f"{out_prefix}_micro.csv")
    else:
        print("\n[2/4] Micro-benchmark skipped.")

    # --- Session benchmark ---
    turns: list[TurnResult] = []
    if not args.skip_sessions:
        print(f"\n[3/4] Session benchmark ({args.sessions} sessions × {args.turns} turns)...")
        turns = run_session_benchmark(n_sessions=args.sessions, turns_per_session=args.turns)
        if turns:
            export_turn_csv(turns, f"{out_prefix}_turns.csv")
    else:
        print("\n[3/4] Session benchmark skipped.")

    # --- Analysis ---
    print("\n[4/4] Analysing results...")
    warmth = analyse_warmth_curve(turns)
    latency = analyse_latency(turns, micro)
    seams = analyse_seams(turns)
    tokens = analyse_token_shape(turns)

    export_warmth_csv(warmth, f"{out_prefix}_warmth.csv")

    all_results = {
        "meta": {
            "timestamp": ts,
            "server": BASE_URL,
            "n_sessions": args.sessions,
            "turns_per_session": args.turns,
            "micro_n": args.micro_n,
            "total_turns": len(turns),
            "total_micro_samples": len(micro),
        },
        "corpus_audit": corpus,
        "warmth_curve": warmth,
        "latency": latency,
        "seam_quality": seams,
        "response_shape": tokens,
    }
    export_json(all_results, f"{out_prefix}_summary.json")

    # --- Print tables ---
    print_paper_tables(warmth, latency, seams, tokens, corpus)

    print(f"\nAll outputs written with prefix: {out_prefix}")
    print("Use *_summary.json to update paper §5 tables.")


if __name__ == "__main__":
    main()
