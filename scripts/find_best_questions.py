"""
Find the 7 questions that maximise corpus hit rate for the insurance agent.

Pass 1: Run each candidate question independently (fresh session each time)
         so scores are not polluted by conversation history.
Pass 2: Run the top-7 as a real 7-turn conversation and show final breakdown.
"""
from __future__ import annotations

import json
import time
import httpx

BASE = "http://localhost:8001"

# ── candidate questions ────────────────────────────────────────────────────
# Designed in two flavours:
#   HIGH-corpus — status/yes-no/procedural questions with no dynamic values in the reply
#   LOW-corpus  — questions that force the agent to recite IDs, amounts, dates
CANDIDATES = [
    # Likely HIGH corpus
    "Is my health insurance policy active?",
    "Is my motor insurance still active?",
    "Do I have any active policies?",
    "What does my health insurance cover?",
    "Is my claim still under review?",
    "Has my claim been approved?",
    "Can I add my family members to my policy?",
    "What should I do in case of a medical emergency?",
    "How do I file a new claim?",
    "Can I renew my policy online?",
    "How do I reach the nearest network hospital?",
    "Is cashless treatment available at network hospitals?",
    "What documents do I need to submit for a claim?",
    "Thank you, that's all I needed.",
    "Can you confirm my policy is not expired?",

    # Likely LOW corpus (forces dynamic values)
    "What is my policy number?",
    "What is my next premium due date?",
    "What is the premium amount for my health policy?",
    "What is the status of my claim and what is the claim number?",
    "How much is the claim amount I filed?",
    "What is the sum insured on my health policy?",
    "What is my vehicle number on the motor policy?",
]


def create_session(agent: str = "insurance") -> str:
    r = httpx.post(f"{BASE}/v1/agent/sessions", json={"agent": agent, "model": "kokoro"}, timeout=10)
    r.raise_for_status()
    return r.json()["session_id"]


def run_turn(session_id: str, question: str, model: str = "kokoro") -> dict:
    r = httpx.post(
        f"{BASE}/v1/agent/sessions/{session_id}/turn",
        params={"text": question, "model": model},
        timeout=60,
    )
    r.raise_for_status()
    raw = r.headers.get("X-AVRS-Metrics", "{}")
    metrics = json.loads(raw)
    return {
        "question": question,
        "response": r.headers.get("X-Agent-Response", ""),
        "prerecorded_pct": metrics.get("prerecorded_pct", 0),
        "cached_pct":      metrics.get("cached_pct", 0),
        "tts_chars_pct":   metrics.get("tts_chars_pct", 100),
        "cost_reduction":  metrics.get("cost_reduction_pct", 0),
        "latency_ms":      metrics.get("latency_total_ms", 0),
        "segments":        metrics.get("segments", 0),
    }


def corpus_score(result: dict) -> float:
    return result["prerecorded_pct"] + result["cached_pct"] * 0.5


# ── Pass 1: sweep every candidate independently ────────────────────────────
print("=" * 70)
print("PASS 1 — Independent sweep across all candidates")
print("=" * 70)

scores: list[dict] = []
for q in CANDIDATES:
    sid = create_session()
    try:
        r = run_turn(sid, q)
        score = corpus_score(r)
        scores.append({**r, "score": score})
        status = f"pre={r['prerecorded_pct']:.0f}%  cache={r['cached_pct']:.0f}%  tts={r['tts_chars_pct']:.0f}%  score={score:.1f}"
        print(f"  {'★' if score >= 50 else ' '}  {q[:55]:<56} {status}")
    except Exception as e:
        print(f"  ✗  {q[:55]:<56} ERROR: {e}")
    time.sleep(13)

scores.sort(key=lambda x: -x["score"])
top7 = scores[:7]

print()
print("=" * 70)
print("TOP 7 QUESTIONS BY CORPUS SCORE")
print("=" * 70)
for i, r in enumerate(top7, 1):
    print(f"  {i}. [{r['score']:4.1f}] {r['question']}")
    print(f"       pre={r['prerecorded_pct']:.0f}%  cache={r['cached_pct']:.0f}%  tts={r['tts_chars_pct']:.0f}%  lat={r['latency_ms']:.0f}ms")
    print(f"       → {r['response'][:90]}")
    print()


# ── Pass 2: real 7-turn conversation with top questions ────────────────────
print("=" * 70)
print("PASS 2 — Real 7-turn conversation (top questions in sequence)")
print("=" * 70)

sid = create_session()
total_pre = total_cache = total_tts = 0
turns = 0

for i, candidate in enumerate(top7, 1):
    try:
        r = run_turn(sid, candidate["question"])
        turns += 1
        total_pre   += r["prerecorded_pct"]
        total_cache += r["cached_pct"]
        total_tts   += r["tts_chars_pct"]
        mode_label = (
            "CORPUS " if r["prerecorded_pct"] > 60 else
            "CACHE  " if r["cached_pct"] > 60    else
            "TTS    "
        )
        print(f"  Turn {i} [{mode_label}] pre={r['prerecorded_pct']:.0f}%  cache={r['cached_pct']:.0f}%  tts={r['tts_chars_pct']:.0f}%")
        print(f"    Q: {candidate['question']}")
        print(f"    A: {r['response'][:90]}")
        print()
    except Exception as e:
        print(f"  Turn {i} ERROR: {e}")

if turns:
    avg_pre   = total_pre   / turns
    avg_cache = total_cache / turns
    avg_tts   = total_tts   / turns
    print("-" * 70)
    print(f"  Averages across {turns} turns:")
    print(f"    Prerecorded : {avg_pre:.1f}%")
    print(f"    Cached      : {avg_cache:.1f}%")
    print(f"    Live TTS    : {avg_tts:.1f}%")
    print(f"    Corpus hit  : {avg_pre + avg_cache:.1f}%")
    print()
    print("  Best question script for demos:")
    for i, r in enumerate(top7, 1):
        print(f"    {i}. \"{r['question']}\"")
