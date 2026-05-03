# AVRS: Adaptive Voice Rendering System
## Research Update — In-Call Infilling

**Date:** May 2026  
**Status:** Available for integration  
**Prepared for:** Research Team

---

## Context: From Post-Call to In-Call Infilling

Our team has been working on **post-call infilling** — the task of synthesising and inserting missing or corrected speech segments into recorded call audio after the call ends. The core challenge there is maintaining acoustic consistency (matching speaker prosody, room acoustics, and temporal alignment) in a non-real-time setting.

AVRS now brings that same capability **into the live call itself**. Instead of patching a recording, the system renders each agent response in real time — sentence by sentence, segment by segment — choosing the cheapest and fastest audio source for each piece of text while keeping the output perceptually seamless.

The shift in constraint is significant:

| Dimension | Post-Call Infilling | In-Call Infilling (AVRS) |
|---|---|---|
| Time budget | Minutes to hours | < 500ms to first audio byte |
| Audio source | Single synthesised clip | Three-tier corpus / cache / live TTS |
| Consistency target | Match original speaker | Consistent voice across segments |
| Dynamic content | Can be pre-planned | Must handle live slot values (IDs, dates, amounts) |
| Evaluation | Offline MOS / NISQA | Real-time latency + corpus hit rate |

---

## What is AVRS?

AVRS is a **hybrid audio rendering pipeline** for voice AI agents. Given a natural language response from an LLM, it:

1. **Parses** the response into static text segments and dynamic slot values
2. **Routes** each static segment to the cheapest audio source that can serve it within latency budget:
   - **Tier 1 — Corpus (prerecorded):** ~2ms, zero compute
   - **Tier 2 — Session cache (previously synthesised):** ~3ms, zero compute
   - **Tier 3 — Live TTS (Kokoro):** ~200–840ms, on-demand synthesis
3. **Merges** all segments with pitch alignment and 50ms crossfades for seamless output

The key insight is that a large fraction of what a BFSI voice agent says is **repeated across calls** — phrases like "Your claim is under review", "You can renew your policy online", "How may I assist you today?" These can be prerecorded once by a human voice artist and served at near-zero latency. Only the dynamic values (claim numbers, amounts, dates) need live synthesis.

---

## Figure 1: Full Pipeline Overview

![AVRS Voice Response Pipeline](../../../Downloads/AVRS.png)

### Pipeline Stages

**Stage 1 — Capture**  
Audio arrives from the user's microphone or phone channel (PCM/WAV). An STT model (Whisper offline or Deepgram cloud) converts it to text. Deepgram's `nova-2` model achieves ~200ms transcription latency vs. 4–8s for Whisper large-v3 on CPU, making it the preferred option when network is available.

**Stage 2 — Intent & Data Fetching**  
The transcribed text is sent to a `BFSIAgent` backed by Claude. The agent has access to a set of domain tools (`lookup_policy`, `get_claim_status`, `get_account_balance`, `get_customer_policies`). It calls these tools to retrieve live customer data, then formulates a response using a strict template format:

```
Your claim {claim_id} is under review. You can expect a resolution by {eta}.
SLOTS: {"claim_id": "CN-20241130-442", "eta": "December 20"}
```

The response always separates **static prose** (which can hit the corpus) from **dynamic values** (which must be synthesised or spoken as slot fills). This separation is enforced in the system prompt.

**Stage 3 — Parse & Slot Fill**  
A parser splits the LLM response into an ordered list of segments. Each segment is typed as either `static` (fixed text, corpus-eligible) or `slot` (a dynamic value that must be rendered live). For example:

```
"I found your claim {claim_id} for {reason}. It is currently {status}."
→ Segments:
  1. "I found your claim"    [static]
  2. "CN-20241130-442"       [slot]
  3. "for"                   [static]
  4. "Dengue hospitalization" [slot]
  5. "It is currently"       [static]
  6. "under review"          [slot]
```

**Stage 4 — Render Router (Smart Tiered Retrieval)**  
Each segment is independently routed through three tiers:

- **Tier 1 — Corpus Lookup:** The segment text is fuzzy-matched (SequenceMatcher, threshold 0.68) against a prerecorded phrase library stored as `.flac` files. A match serves audio instantly at ~2ms latency.
- **Tier 2 — Slot-in-Slot Cache Lookup:** If the exact segment (with its dynamic value) was synthesised in a previous turn of the same session, the cached `.wav` is returned at ~3ms.
- **Tier 3 — Live TTS:** If neither cache tier hits, Kokoro TTS synthesises the segment on demand. Latency ranges from ~200ms for short phrases to ~840ms for longer ones.

**Stage 5 — Merge & Crossfade**  
All rendered audio segments (regardless of source) are pitch-aligned and joined with 50ms crossfades at each segment boundary. RMS normalisation ensures consistent loudness. The result is a single, acoustically seamless WAV that is indistinguishable from end-to-end TTS synthesis but delivered much faster and at much lower cost.

**Stage 6 — Output**  
The merged WAV is streamed back to the client. Turn 1 of a cold session typically delivers in 1,400–1,500ms. By Turn 2, if the session cache is warm, the same response structure can be delivered in **8ms**.

---

### The RenderRouter — Three-Tier Decision Logic

```
For each segment:
  ┌─────────────────────────────────────────┐
  │  Tier 1: Corpus Lookup                  │  ← ~2ms, highest quality
  │  Fuzzy match against prerecorded index  │
  │  (SequenceMatcher ≥ 0.68)               │
  └────────────────┬────────────────────────┘
                   │ MISS
  ┌────────────────▼────────────────────────┐
  │  Tier 2: Slot Cache Lookup              │  ← ~3ms, good quality
  │  Exact match: (text, voice_id) → .wav   │
  │  (synthesised in a prior turn)          │
  └────────────────┬────────────────────────┘
                   │ MISS
  ┌────────────────▼────────────────────────┐
  │  Tier 3: Live TTS (Kokoro)              │  ← 200–840ms, on-demand
  │  Synthesise + write to cache            │
  │  (available next turn)                  │
  └─────────────────────────────────────────┘
```

---

## Figure 2: Server Architecture

![AVRS Server Architecture](../../../Downloads/AVRS_Arch.png)

### Component Breakdown

**Input / Capture**  
WAV bytes arrive over HTTP or WebSocket. The STT layer is pluggable: set `DEEPGRAM_API_KEY` in the environment to use Deepgram `nova-2` (fast, cloud); leave it unset to fall back to `faster-whisper` (offline, no external dependency).

**BFSIAgent (Intent & Data Fetching)**  
A stateful agent that maintains conversation history per session. It uses Claude with an agentic tool-use loop — the model decides which tools to call, calls them, receives structured JSON results, and incorporates the data into its response. The agent persona (name, company, system prompt, greeting phrases) is fully configurable via `agents.yaml` without touching source code.

Three agent personas are currently defined:
- **Priya** — HealthFirst Insurance (health and motor policies, claims)
- **Arjun** — SafeBank India (savings accounts, EMIs, cards)
- **Maya** — PayCentral (UPI payments, refunds)

**Parsing & Slot Filling**  
The parser reads the `SLOTS: {...}` line appended to every LLM response and maps slot keys back to rendered text positions. The regex `\{(\w+)\}` identifies slot placeholders. A critical invariant: **slot keys must use only letters, digits, and underscores** — hyphens and spaces in placeholders break extraction and cause silent gaps in output.

**Audio Rendering (Three-Tier)**  
- Tier 1: Corpus `.flac` files indexed in memory at startup
- Tier 2: Session cache as `.wav` files on disk (keyed by `text + voice_id`)
- Tier 3: Kokoro ONNX TTS with a fallback strategy; newly synthesised clips are written back to Tier 2 cache automatically

**Merging & Crossfading**  
The `Merger/Crossfader` module pitch-aligns segments before joining (compensating for slight prosodic differences between corpus, cache, and live TTS sources) and applies 50ms linear crossfades at boundaries. This is the component most directly related to the post-call infilling work — same acoustic consistency goal, now operating in real time.

**Output / Streaming**  
FastAPI `StreamingResponse` returns the final merged WAV as bytes. The response headers carry per-turn metrics (`X-AVRS-Metrics`) including segment counts, routing percentages, and total render latency.

**Tech Stack**

| Component | Technology |
|---|---|
| API server | FastAPI + uvicorn |
| STT | Whisper (offline) / Deepgram nova-2 (cloud) |
| LLM | Claude claude-sonnet-4-6 (configurable via `AVRS_LLM_MODEL`) |
| TTS | Kokoro ONNX |
| Storage / Cache | Local disk (`.flac` corpus, `.wav` cache) |
| Audio processing | librosa, soundfile, numpy/scipy |

---

## Figure 3: End-to-End Walkthrough — Turn 1 and Turn 2

![AVRS Turn-by-Turn Example](../../../Downloads/AVRS_Example.png)

### Turn 1 — Cold Session: "Hi, can you tell me about my claim?"

This is the first turn of a session — no session cache yet, corpus is the only fast tier.

**Step 1 — ASR**  
Whisper (or Deepgram) converts the user's spoken audio to: `"Hi, can you tell me about my claim?"`

**Step 2 — LLM + Tools**  
Claude calls `get_claim_status()`. The tool returns:
```json
{
  "claim_id": "CN-20241130-442",
  "status": "Under Review",
  "reason": "Dengue hospitalization",
  ...
}
```
Claude formulates the response:
```
I found your claim {claim_id} for {reason}. It is currently {status}.
SLOTS: {"claim_id": "CN-20241130-442", "reason": "Dengue hospitalization", "status": "under review"}
```

**Step 3 — Parse & Slot Fill**  
The parser produces 6 ordered segments:
1. `"I found your claim"` — static
2. `"CN-20241130-442"` — slot (claim_id)
3. `"for"` — static
4. `"Dengue hospitalization"` — slot (reason)
5. `". It is currently"` — static
6. `"under review"` — slot (status)

**Step 4 — Render Router**

| Segment | Source | Latency | Notes |
|---|---|---|---|
| "I found your claim" | **Corpus hit** | 2ms | Prerecorded phrase in library |
| "CN-20241130-442" | **Live TTS** | 840ms | Novel value, must synthesise |
| "for" | **Cache hit** | 3ms | Short common word, previously cached |
| "Dengue hospitalization" | **Live TTS** | 620ms | Novel medical term |
| ". It is currently" | **Corpus hit** | 2ms | Common transition phrase |
| "under review" | **Cache hit** | 3ms | Status word, previously synthesised |

Note: the Live TTS segments are rendered in parallel where dependencies allow, which is why total render time (1,470ms) is less than the sum of individual TTS latencies.

**Step 5 — Merge & Crossfade**  
5 crossfade boundaries are applied. Pitch alignment ensures the corpus-sourced segments (human voice) blend naturally with the Kokoro-synthesised segments.

**Step 6 — Output**  
2.1s WAV delivered in 1,470ms total render time.

**Turn 1 Metrics:**  
`Prerecorded: 33%` | `Cached: 16%` | `Live TTS: 51%` | `Total: 1,470ms`

---

### Turn 2 — Warm Cache: "When will it be resolved?"

The session cache now holds the segments synthesised in Turn 1. This turn asks a follow-up — the answer is structurally similar but contains one new slot value.

**Step 2 — LLM**  
No tool call needed (context carries the ETA). Claude responds:
```
Your claim should be resolved by {eta}.
SLOTS: {"eta": "December 20"}
```

**Step 3 — Parse**  
2 segments:
1. `"Your claim should be resolved by"` — static
2. `"December 20"` — slot (eta)

**Step 4 — Render Router**

| Segment | Source | Latency | Notes |
|---|---|---|---|
| "Your claim should be resolved by" | **Corpus hit** | 2ms | Phrase in prerecorded library |
| "December 20" | **Cache hit** ★ | 3ms | Was synthesised in Turn 1 and cached |

★ "December 20" was synthesised during Turn 1 when the claim status response was built. It is now in the session cache.

**Step 5 — Merge**  
1 crossfade boundary.

**Step 6 — Output**  
0.8s WAV delivered in **8ms** total render time.

**Turn 2 Metrics:**  
`Prerecorded: 70%` | `Cached: 30%` | `Live TTS: 0%` | `Total: 8ms`

---

## Why This Matters for the Research Team

### The In-Call Infilling Problem

Post-call infilling solves: *"Given a reference recording and a new segment to insert, how do we synthesise the insertion so it matches the original speaker's prosody, pace, and acoustic environment?"*

In-call infilling (AVRS) solves: *"Given a live agent response generated in real time, how do we render it as natural-sounding audio in under 500ms, re-using as much precomputed audio as possible?"*

The two problems share the **acoustic consistency challenge** (seam quality across segment boundaries) but differ in:
- **Time budget**: Offline vs. real-time
- **Reference material**: A single speaker recording vs. a tiered corpus + cache
- **Dynamic content handling**: Pre-planned insertions vs. live slot values from a tool call
- **Scale**: Single insertion vs. many segments per response

### Corpus Hit Rate as the Key Metric

The primary optimisation target in AVRS is **corpus hit rate** — the percentage of characters in each response that are served from prerecorded or cached audio rather than live TTS:

```
corpus_score = prerecorded_pct + cached_pct × 0.5
```

A 7-turn conversation benchmark across the insurance domain yielded:
- Best single-turn corpus score: **75%** ("Has my claim been approved?")
- Average across 7-turn conversation: **33–44%** corpus hit rate
- Turn 2 in warm-cache scenario: **100%** corpus (0ms live TTS)

The corpus currently holds **121 prerecorded phrases** for the insurance domain (as of this update). Expanding it with domain-specific sentences is the highest-leverage action for improving the in-call experience.

### Connection to Post-Call Infilling Research

The **Merge & Crossfade** module (Stage 5) is the direct descendant of post-call infilling work. The same pitch alignment and crossfade logic that ensures quality in offline infilling now runs on every turn, in real time. Improvements to the seam model (better pitch estimation, dynamic crossfade window sizing, RMS-aware normalisation) developed in the post-call context transfer directly to AVRS.

One open research question: the current fuzzy match threshold (0.68) was set empirically. A learned similarity model — trained on perceptual quality ratings of corpus-served vs. TTS-served segments — could improve the corpus hit rate without degrading output naturalness.

---

## Current Limitations and Open Questions

1. **Corpus coverage**: 121 phrases for insurance; banking and payments corpora are minimal. Coverage directly limits hit rate for those domains.

2. **Slot-in-corpus**: Currently, slot placeholders (`{claim_id}`) always force a Tier 3 live TTS render. For high-frequency values (common dates, round amounts), a value-keyed cache tier could bridge this.

3. **Seam quality at speed**: At 8ms total render time, the crossfade quality has not been benchmarked under adversarial conditions (very short segments, large pitch gaps between corpus and cache sources). This is an open evaluation gap.

4. **Fuzzy match threshold**: The 0.68 threshold is fixed. A learned similarity model could dynamically adjust based on acoustic distance between candidate corpus phrases, not just text similarity.

5. **Streaming first byte**: TTFB (time-to-first-byte) is currently `STT_ms + LLM_ms + first_segment_latency_ms`. For Tier 1 corpus hits, TTFB could be further reduced by beginning audio delivery before all segments are rendered (incremental streaming), which is not yet implemented.

---

## Getting Started

```bash
# Clone and install
cd avrs
pip install -e ".[kokoro]"

# Set environment
export ANTHROPIC_API_KEY=...
export DEEPGRAM_API_KEY=...   # optional — falls back to Whisper if not set

# Start server
uvicorn avrs.server:app --host 0.0.0.0 --port 8001

# Create a session and run a turn
curl -X POST http://localhost:8001/v1/agent/sessions \
  -H "Content-Type: application/json" \
  -d '{"agent": "insurance", "model": "kokoro"}'

# Run the best-question benchmark
python scripts/find_best_questions.py

# Expand the insurance corpus
python scripts/build_insurance_corpus.py
```

Agent personas (name, company, system prompt, greeting phrases) are configured in `agents.yaml` at the project root — no code changes needed to update agent behaviour.

---

*For questions or to access the codebase, contact supreeth.ravi@phronetic.ai*
