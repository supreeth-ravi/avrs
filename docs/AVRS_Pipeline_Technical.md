# AVRS: Adaptive Voice Rendering System
## Technical Pipeline Document

**Version:** 1.0  
**Date:** April 30, 2026  
**Author:** Phronetic AI Research  
**Context:** BFSI Voice Agent Research Program

---

## 1. Research Context: The Two Paradigms

The Phronetic AI research program is investigating automated speech synthesis pipelines for AI-driven customer contact centers, with a specific focus on the Indian BFSI (Banking, Financial Services, and Insurance) market. A core tension in this domain is between **response quality** and **cost efficiency** — a tension amplified in cost-sensitive markets where API calls must be minimized.

Two paradigms have been identified:

### Paradigm 1: Nondeterministic End-to-End (STT → TTT → TTS)

```
User speech → STT → LLM (text generation) → TTS → Agent audio
```

Every turn generates a novel response. The LLM synthesizes new text from scratch, and TTS converts it on the fly. This approach:
- Maximizes response flexibility and personalization
- **Generates the maximum number of tokens per turn** — every response is net-new LLM output
- Incurs full TTS synthesis cost on every utterance
- Latency: 2,000–5,000ms end-to-end per turn

This is the most common design for AI voice assistants today.

### Paradigm 2: Deterministic + Dynamic (Pre-generated + Slot Infilling)

```
User speech → STT → LLM (slot classification + fill) → AVRS Router → Hybrid Audio
                                                         ├─ Prerecorded corpus (static phrases)
                                                         ├─ Disk cache (previously synthesized)
                                                         └─ Live TTS (dynamic values only)
```

The agent's vocabulary is modeled as a **finite set of response templates** with **dynamic slot values** for per-customer data. The LLM's job is reduced from *generating text* to *classifying intent and filling named slots*. Audio for static phrases comes from a prerecorded corpus or cache; only dynamic values (amounts, dates, IDs) ever hit live TTS.

This approach:
- Dramatically reduces LLM output tokens (max ~50 tokens per turn vs. 200+ for full generation)
- Eliminates TTS cost for all static content (typically 70–85% of syllables)
- Achieves sub-100ms render latency for corpus hits; 300ms for cached content
- **Requires pre-investment in corpus construction and template design**

**AVRS implements Paradigm 2.** This document describes the technical pipeline, its components, and its measured impact at scale.

---

## 2. Why This Matters for India

Indian AI deployment is uniquely cost-constrained:

- **Rupee-denominated budgets:** Enterprises budget voice AI in rupees; API costs (USD) hit margins disproportionately.
- **Scale:** Tier-2/3 insurance and banking agents handle 50,000–500,000 calls/day at scale. At $0.006 per TTS minute (ElevenLabs commercial rate), a 3-minute average call costs $0.018 in TTS alone — at 100k calls/day, that is $1.8k/day in TTS before LLM inference.
- **Predictable vocabulary:** Indian BFSI agents have extremely bounded conversation flows. A health insurance agent's vocabulary spans perhaps 60–80 root phrases with dynamic slot substitution. This makes the corpus tractable.
- **Regulatory constraints:** RBI and IRDAI mandates around disclosure, consent, and grievance language mean those exact phrases must be spoken verbatim — they are *inherently* static content suitable for prerecording.

The deterministic + dynamic paradigm is not merely a cost optimization for India; it is **architecturally aligned** with how regulated financial conversations actually work.

---

## 3. System Architecture

```
                        ┌─────────────────────────────────────────────────┐
                        │                   AVRS Server                   │
                        │               (FastAPI / uvicorn)               │
    User                │                                                  │
    ────                │  ┌──────────┐    ┌───────────────────────────┐  │
    Mic / Phone ──WAV──►│  │  Whisper │    │       BFSIAgent           │  │
                        │  │  STT     │───►│   (Claude claude-sonnet-4-6 + Tools) │  │
                        │  └──────────┘    │  lookup_policy            │  │
                        │                  │  get_claim_status          │  │
                        │                  │  get_account_balance       │  │
                        │                  └─────────┬─────────────────┘  │
                        │                            │ text_template        │
                        │                            │ + slots_dict         │
                        │                            ▼                      │
                        │                  ┌─────────────────────────┐     │
                        │                  │   Parser / Slot Filler  │     │
                        │                  │  "Your claim {claim_id}"│     │
                        │                  │   → [static, slot, ...]  │     │
                        │                  └─────────┬───────────────┘     │
                        │                            │ Segment[]            │
                        │                            ▼                      │
                        │              ┌─────────────────────────────┐     │
                        │              │       RenderRouter          │     │
                        │              │                             │     │
                        │              │  Tier 1: Corpus lookup      │     │
                        │              │   (prerecorded WAV, ~2ms)   │     │
                        │              │                             │     │
                        │              │  Tier 2: Disk cache lookup  │     │
                        │              │   (synthesized WAV, ~3ms)   │     │
                        │              │                             │     │
                        │              │  Tier 3: Live TTS (Kokoro)  │     │
                        │              │   (synthesis, 800-3500ms)   │     │
                        │              └──────────────┬──────────────┘     │
                        │                             │ RenderedSegment[]  │
                        │                             ▼                    │
                        │              ┌──────────────────────────────┐    │
                        │              │    Merger / Crossfader       │    │
                        │              │  pitch align + 50ms fade     │    │
                        │              └──────────────┬───────────────┘    │
                        │                             │ MergedAudio        │
                        │                             ▼                    │
    User ◄──────WAV─────│         StreamingResponse (wav/bytes)            │
                        └─────────────────────────────────────────────────┘
```

---

## 4. Pipeline Components: Technical Specification

### 4.1 Speech-to-Text (faster-whisper)

| Property | Value |
|---|---|
| Model | `faster-whisper base` (CTranslate2 quantized) |
| Language | `en`, forced |
| VAD filter | Enabled (silero-vad) |
| Input format | WAV/PCM 16kHz mono |
| Latency (base) | 200–400ms on CPU |
| Accuracy target | >95% WER on Indian-accented English BFSI vocabulary |

The STT step converts raw mic audio to a user text transcript. The `transcribe_wav_bytes()` method accepts WAV bytes directly, enabling both REST API (file upload) and WebSocket (streaming PCM) ingestion paths.

In the phone-call frontend, Voice Activity Detection (VAD) runs **client-side** in the browser (ScriptProcessorNode, 80ms RMS chunks, threshold=0.018, onset=6 chunks, silence=22 chunks = ~1.8s silence to commit). Client-side VAD eliminates server-side audio buffering and enables real-time interruption: when the user speaks during agent playback, the browser immediately cancels the AudioBufferSourceNode queue and sends a new audio commit.

### 4.2 LLM Agent (Claude claude-sonnet-4-6 with Tool Use)

The `BFSIAgent` class orchestrates a multi-turn conversation session using Anthropic's Messages API with tool use. The agent's **system prompt encodes the response contract**:

```
RESPONSE RULES:
1. Keep responses to 1-3 short spoken sentences.
2. For ALL dynamic values, wrap in {curly_braces} with a descriptive key.
3. After the spoken text, write: SLOTS: {"key": "value", ...}
```

This prompt engineering is the core of the Paradigm 2 approach: Claude is instructed not to produce a complete spoken sentence but rather a **text template + slot dictionary**. This separation means:

- The **static frame** of the sentence ("Your claim ... for ... is currently ...") is reusable.
- Only the **slot values** (claim ID, reason, status) require dynamic synthesis.

**Tool loop:** Claude may call backend tools before producing the final text template:

```
User: "What is my claim status?"
→ Claude calls get_claim_status(claim_id=None)
→ Tool returns: {claim_id: "CN-20241130-442", status: "Under Review", eta: "December 20"}
→ Claude produces:
  "Your claim {claim_id} for {reason} is currently {status}. Resolution by {eta}."
  SLOTS: {"claim_id": "CN-20241130-442", "reason": "Dengue hospitalization",
          "status": "under review", "eta": "December 20"}
```

**Token efficiency:** A complete natural-language response to this query would be ~40 tokens. The template + SLOTS JSON adds ~15 tokens overhead but reduces the **synthesis surface** dramatically — only the dynamic slot values go to TTS.

**Model selection rationale:** `claude-sonnet-4-6` provides strong instruction-following for the response format contract and reliable tool use. `claude-haiku-4-5` was tested but showed higher SLOTS parsing failure rates (~8% vs ~1%). For a latency-sensitive voice path, format reliability outweighs cost savings from a smaller model at this call volume.

### 4.3 Parser and Slot Filler

`parser.parse_utterance(text)` converts the text template into a `list[Segment]`:

```python
@dataclass
class Segment:
    type: str       # "static" | "slot"
    text: str       # filled text value (or empty for unfilled slots)
    slot_key: str | None
```

For an annotated template like `"Your claim {claim_id} is {status}"`:

```python
[
  Segment(type="static", text="Your claim "),
  Segment(type="slot",   text="",  slot_key="claim_id"),
  Segment(type="static", text=" is "),
  Segment(type="slot",   text="",  slot_key="status"),
]
```

After `fill_slots(segments, slots)`:

```python
[
  Segment(type="static", text="Your claim "),
  Segment(type="slot",   text="CN-20241130-442", slot_key="claim_id"),
  Segment(type="static", text=" is "),
  Segment(type="slot",   text="under review",   slot_key="status"),
]
```

For unannotated responses (no `{slot}` markers), the parser falls back to spaCy NER to auto-detect named entities (MONEY, DATE, ORG, PERSON, CARDINAL) as slots. This handles agents that produce well-formed sentences without explicit slot markup.

### 4.4 Render Router: Three-Tier Audio Resolution

The `RenderRouter._render_segment()` method implements a priority-ordered resolution chain:

```
Tier 1: Corpus (prerecorded WAV)     →  ~2ms  | 0 TTS cost
Tier 2: Disk cache (synthesized WAV) →  ~3ms  | 0 TTS cost (amortized)
Tier 3: Live TTS (Kokoro ONNX)       →  800-3500ms | full cost
```

**Tier 1 — Prerecorded Corpus:**

The corpus is a curated library of human-recorded or high-quality TTS-pre-synthesized phrases for the most frequent static segments. The corpus lookup uses normalized text as the key (via `Corpus.lookup()`). In production, a human voice actor records the corpus once; in development, Kokoro synthesizes the corpus offline with careful prosody control.

**Critical corpus design rule:** Only complete, grammatically whole sentences or phrases are valid corpus entries. Fragments like "Your monthly premium is" — which would get sentence-final falling intonation from a TTS engine synthesizing them in isolation — produce wrong prosody when stitched with a following slot. The corpus must represent natural prosodic units.

**Tier 2 — Disk Cache:**

Every novel synthesis result is written to disk, keyed by:
```python
key = sha256(text + voice_id + tts_model + str(sr)).hexdigest()[:16]
```

On subsequent calls with identical text (e.g., the same claim status message for a different customer's call), the WAV is served from disk at ~3ms. Cache warmth grows rapidly for static phrases that recur across callers.

**Tier 3 — Live TTS (Kokoro ONNX):**

Kokoro is an 82M-parameter neural TTS model that runs locally via ONNX runtime. Key parameters:

| Parameter | Value | Rationale |
|---|---|---|
| Voice | `if_sara` | Indian female, appropriate for BFSI insurance agent |
| Speed | 1.05 | Slightly faster than neutral; avoids plodding cadence |
| Output SR | 24kHz float32 | Native; resampled to 22050Hz for output |
| Peak normalization | 0.95 | Prevents PCM_16 hard clipping (Kokoro peak often > 1.0) |
| Inference device | CPU / MPS | No GPU required for production |

**Hard clipping prevention:** Kokoro's float32 output can exceed 1.0 amplitude (observed peaks up to 1.27). When written to PCM_16 WAV without normalization, samples above 32767 are truncated, producing harsh square-wave distortion audible as a robotic or cartoonish artifact. All synthesis output is peak-normalized to 0.95 before caching or streaming.

### 4.5 Merger and Crossfader

After all segments are rendered, `merger.merge_segments()` concatenates them into a single audio buffer with:

1. **RMS normalization** per segment — equalizes loudness between prerecorded (often lower RMS) and TTS-synthesized segments.
2. **Pitch alignment** — at each segment boundary, compares F0 (fundamental frequency) in a 250ms window on each side. If pitch delta exceeds 1.5 semitones, applies `librosa.effects.pitch_shift` to the right segment to match.
3. **50ms crossfade** — linear fade-out on the left segment tail, fade-in on the right segment head. At 22050Hz, this is 1,102 samples of overlap, sufficient to eliminate click artifacts at segment boundaries.

The merger ensures that the output sounds like a single continuous utterance regardless of how many different sources (prerecorded, cached, live TTS) contributed segments.

### 4.6 Audio Output

The merged audio is returned as:
- **REST API:** `StreamingResponse` with `Content-Type: audio/wav`, PCM_16 encoded
- **WebSocket:** per-segment base64 PCM deltas sent as each segment renders, enabling the client to begin playback before all segments are ready

HTTP response headers carry metadata:
```
X-Transcript: <whisper output>
X-Agent-Response: <filled response text>
X-AVRS-Cost-Reduction-Pct: <percentage>
X-AVRS-Latency-Ms: <render time>
X-AVRS-Metrics: {"prerecorded_pct": 0.4, "cached_pct": 0.3, "tts_chars_pct": 0.3, ...}
```

All header values are sanitized to Latin-1 (HTTP header encoding constraint): em-dashes, curly quotes, and rupee symbols are transliterated before transmission.

---

## 5. Conversation Flow: End-to-End Example

**Session:** Insurance customer calling about claim status.

```
Turn 1
───────
User (audio): "Hi, can you tell me about my claim?"
  → Whisper STT: "Hi, can you tell me about my claim?"
  → Claude + tool use:
      calls get_claim_status() → {claim_id: "CN-20241130-442", status: "Under Review", ...}
      produces: "I found your claim {claim_id} for {reason}. It is currently {status}."
                SLOTS: {claim_id: ..., reason: "Dengue hospitalization", status: "under review"}
  → Parser segments: [static, slot, static, slot, static, slot]
  → Router:
      "I found your claim " → corpus hit     [2ms]
      "CN-20241130-442"     → live TTS       [840ms]
      " for "               → cache hit      [3ms]
      "Dengue hospitalization" → live TTS    [620ms]
      ". It is currently "  → corpus hit     [2ms]
      "under review"        → cache hit      [3ms]
  → Merger: crossfades 5 boundaries, normalizes RMS
  → Output: 2.1s WAV, render time 1,470ms
  → Metrics: prerecorded 33%, cached 16%, TTS 51%

Turn 2 (same session, warmer cache)
──────────────────────────────────
User: "When will it be resolved?"
  → Claude: "Your claim should be resolved by {eta}."
             SLOTS: {eta: "December 20"}
  → Segments: [static, slot]
  → Router:
      "Your claim should be resolved by " → corpus hit [2ms]
      "December 20"                        → cache hit  [3ms]  ← was synthesized in Turn 1
  → Merger: crossfade 1 boundary
  → Output: 0.8s WAV, render time 8ms
  → Metrics: prerecorded 70%, cached 30%, TTS 0%
```

Turn 2 demonstrates the **cache warmth effect**: values synthesized in Turn 1 are immediately available for Turn 2 and all subsequent calls from any session that day.

---

## 6. API Surface

### REST Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Service health + capability flags |
| `POST` | `/v1/agent/sessions` | Create conversation session |
| `POST` | `/v1/agent/sessions/{id}/turn` | Send text or audio, receive WAV |
| `DELETE` | `/v1/agent/sessions/{id}` | Terminate session |
| `GET` | `/v1/sessions` | List active sessions |

**Audio turn (STT path):**
```bash
curl -X POST http://localhost:8001/v1/agent/sessions/sess_abc123/turn \
  -F "audio=@recording.wav;type=audio/wav" \
  --output response.wav
```

**Text turn:**
```bash
curl -X POST http://localhost:8001/v1/agent/sessions/sess_abc123/turn \
  -F "text=What is my premium amount?"
  --output response.wav
```

### WebSocket (Phone-Call Mode)

`ws://localhost:8001/v1/stream?agent=insurance&model=kokoro`

Client sends PCM chunks as `input_audio_buffer.append` events (base64 encoded, 16kHz mono Int16). On silence commit, server runs full pipeline and streams per-segment audio deltas back. Client interrupts by sending a new `input_audio_buffer.append` event while agent is speaking.

---

## 7. Cost and Latency Model

### TTS Cost Reduction

TTS cost is proportional to character count synthesized. The AVRS cost metric measures what fraction of characters in the response are served from corpus or cache (zero marginal TTS cost):

```
cost_reduction_pct = (corpus_chars + cache_chars) / total_chars * 100
```

Observed values from the insurance agent:

| Cache warmth | Cost reduction |
|---|---|
| Cold (first call ever) | 15–25% (corpus phrases only) |
| Warm session (5+ turns) | 50–70% |
| Hot production (10k+ calls) | 75–85% |

### Latency Profile

| Tier | Source | Typical latency |
|---|---|---|
| All corpus | Prerecorded WAVs | 5–15ms |
| Mixed corpus + cache | Disk I/O only | 10–50ms |
| Mixed with 1–2 TTS segs | Kokoro synthesis | 500–1,500ms |
| All TTS (cold, complex) | Full synthesis | 1,500–3,500ms |

The worst-case all-TTS path (3,500ms) is still competitive with cloud TTS APIs (ElevenLabs: 800–2,000ms) while being zero-marginal-cost at the per-call level after the corpus is built.

### Scale Economics (Production Estimate)

Assumptions: 100,000 calls/day, 6 turns/call, 15 words/turn average response, ElevenLabs at $0.30/1k characters (~4 chars/word = 60 chars/turn).

**Without AVRS (Paradigm 1 — full TTS every turn):**
```
100,000 calls × 6 turns × 60 chars = 36,000,000 chars/day
Cost: 36M chars × $0.00030/char = $10,800/day = $3.94M/year
```

**With AVRS (Paradigm 2 — 75% corpus/cache hit rate):**
```
36M chars/day × 25% synthesized = 9,000,000 chars/day
Cost: 9M × $0.00030/char = $2,700/day = $985,500/year
Savings: ~$3M/year at 100k calls/day
```

At 1M calls/day (enterprise telco scale): **~$30M/year savings**.

The savings compound because:
1. Cache is shared across all concurrent calls (one synthesis fills the cache for the next N callers with the same query)
2. LLM inference tokens are ~75% lower (slot classification vs. full generation)
3. Infrastructure cost for local TTS (Kokoro ONNX) is flat per server, not per call

---

## 8. Relation to Phronetic AI Research Agenda

The Phronetic AI agenda identifies **voice AI for BFSI in bandwidth-constrained and cost-constrained markets** as a core research direction. Two principal dimensions drive the research:

### 8.1 The Token Efficiency Imperative

Rajesh's feedback in the agenda is explicit: *"India is cost sensitive (API — ElevenLabs). YOU CARE ABOUT # OF TOKENS GENERATED."*

AVRS addresses this at two levels:

**LLM token reduction:** By replacing "generate a response" with "fill these named slots," Claude's output per turn drops from ~200 tokens (full natural-language generation) to ~50 tokens (SLOTS JSON). Over 600,000 turns/day at $0.003/1k output tokens (Sonnet 4.6):
- Paradigm 1: 600k × 200 tokens = 120M tokens = $360/day
- Paradigm 2: 600k × 50 tokens = 30M tokens = $90/day
- **Savings: $270/day = $98,550/year from LLM alone**

**TTS token reduction:** As quantified in Section 7 — 75% of character synthesis eliminated at scale.

### 8.2 Determinism and Auditability

Regulatory voice agents in India (IRDAI for insurance, RBI for banking) increasingly require that key disclosure phrases be spoken *verbatim* as approved by compliance. Paradigm 1 (generative) cannot guarantee this — the model may paraphrase. Paradigm 2 encodes approved disclosures as corpus entries that are played back exactly.

This is not merely a technical property — it enables AVRS to serve as an **audit trail**: every response is a deterministic function of (template_id, slot_values), making conversation replay and compliance verification straightforward.

### 8.3 Bandwidth Considerations

Prerecorded corpus audio can be compressed and served from CDN at the edge, eliminating the synthesis + streaming latency for static content entirely. In low-bandwidth environments (2G/3G), streaming a prerecorded 0.5s phrase (compressed ~8kB) is faster and more reliable than waiting for real-time synthesis from a cloud endpoint.

### 8.4 Research Extension Points

The AVRS prototype surfaces several open research questions:

1. **Corpus construction automation:** Currently, corpus phrases are manually curated. Can an LLM agent analyze conversation logs and propose a minimal corpus set that covers 90% of utterance surface? This is a coverage optimization problem.

2. **Prosody transfer across tiers:** The 50ms crossfade + pitch alignment in the Merger is a heuristic. A learned prosody model could predict the target F0 trajectory across a segment boundary and apply time-domain manipulation more accurately — important when the static frame and dynamic value come from different synthesizers (human recording vs. Kokoro).

3. **Dynamic corpus eviction:** As conversation topics shift (new products, regulatory changes), cached synthesis becomes stale. What is the optimal TTL and eviction policy for the TTS cache? This is analogous to web CDN cache invalidation but with additional constraints around voice quality consistency.

4. **Multi-speaker mixing:** The current implementation uses a single `if_sara` voice for all output. If the corpus is recorded by a human voice actor, there is an acoustic mismatch between prerecorded (human) and synthesized (Kokoro) segments. The Merger normalizes RMS and F0, but timbre mismatch persists. A voice conversion layer between the Merger and the output could eliminate this.

5. **On-device inference:** Kokoro ONNX runs on CPU without GPU. On mobile devices in field agent use cases (bancassurance, doorstep KYC), the entire AVRS pipeline — including STT and TTS — could run on-device, eliminating network dependency entirely. This is the logical conclusion of the cost-sensitivity argument: zero API cost.

---

## 9. Evaluation Framework

| Metric | Measurement Method | Target |
|---|---|---|
| Cost reduction % | `(1 - tts_chars_synthesized / tts_chars_total)` | >70% at steady state |
| P50 render latency | Timer from turn receipt to first audio byte | <500ms |
| P95 render latency | — | <2000ms |
| MOS (voice quality) | NISQA automated MOS estimation | >3.8 |
| Seam artifact score | RMS delta at segment boundaries | <3 dB |
| Pitch continuity | Semitone delta at boundaries after correction | <0.5 st |
| STT WER | Against ground-truth transcripts | <5% on BFSI vocabulary |
| SLOTS parse success | Fraction of Claude turns producing valid JSON | >99% |
| Cache hit rate | Session-level cache lookups / total lookups | >60% after warmup |

---

## 10. Implementation Status

| Component | Status | Notes |
|---|---|---|
| Parser (annotated + NER) | Complete | spaCy fallback for unannotated responses |
| RenderRouter (3-tier) | Complete | Corpus / disk cache / Kokoro |
| Kokoro ONNX TTS | Complete | `if_sara` voice, speed 1.05, peak normalization |
| faster-whisper STT | Complete | Base model, VAD filter |
| BFSIAgent (Claude + tools) | Complete | Insurance, banking, payments personas |
| REST API (FastAPI) | Complete | Session management, audio/text turns |
| WebSocket phone-call mode | Complete | Client VAD, per-segment streaming, interruption |
| Browser frontend | Complete | Full-duplex UI, level meter, chat bubbles |
| Merger with crossfade | Complete | 50ms crossfade, F0 alignment |
| Metrics collection | Complete | Per-turn cost/latency/routing breakdown |
| Corpus builder scripts | Complete | `scripts/build_corpus.sh` |
| Redis cache backend | Designed, not implemented | Disk cache sufficient for prototype |
| On-device (mobile) | Research phase | Kokoro ONNX is mobile-compatible |
| Prosody transfer model | Research phase | See Section 8.4 |

---

## 11. Quick Start

```bash
# Install
git clone https://github.com/phronetic-ai/avrs
cd avrs
pip install -e ".[dev]"

# Run server (Kokoro TTS)
AVRS_TTS_MODEL=kokoro ANTHROPIC_API_KEY=sk-... \
  uvicorn avrs.voice_api:app --port 8001 --reload

# Browser frontend
open http://localhost:8001

# CLI voice demo (mic → server → speaker)
python examples/talk.py --agent insurance --port 8001

# REST text demo
curl -X POST http://localhost:8001/v1/agent/sessions \
     -H "Content-Type: application/json" \
     -d '{"agent": "insurance"}' | jq .session_id
```

---

*AVRS is a Phronetic AI research prototype demonstrating Paradigm 2 voice agent architecture for Indian BFSI applications. The codebase is structured for extension — the corpus, cache, TTS engine, and STT engine are all modular and swappable. The core thesis: for regulated, vocabulary-bounded voice applications, the deterministic + dynamic paradigm achieves order-of-magnitude cost reductions with better auditability than fully generative approaches.*
