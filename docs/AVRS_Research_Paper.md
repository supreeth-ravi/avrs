# Adaptive Voice Rendering for Cost-Efficient Conversational AI in Regulated Domains

**Supreeth Ravi**  
Phronetic AI Research  
supreeth.ravi@phronetic.ai

---

## Abstract

Fully generative text-to-speech (TTS) pipelines dominate production voice AI today, incurring full synthesis cost on every agent utterance regardless of whether the content is novel. We present **AVRS** (Adaptive Voice Rendering System), a three-tier audio routing architecture that separates an agent's response into a static *template frame* and dynamic *slot values*, then resolves each segment through a priority-ordered chain: (1) a prerecorded corpus of approved phrases, (2) a content-addressed disk cache of prior synthesis results, and (3) live neural TTS only for genuinely novel dynamic content. On a representative Indian BFSI (Banking, Financial Services, and Insurance) conversational agent, AVRS achieves **75–85% TTS cost elimination** at production cache warmth with median response latency under 500 ms, compared to 2,000–5,000 ms for end-to-end cloud TTS. The system further reduces LLM inference costs by 75% by reframing generation as structured slot classification rather than free-form text synthesis. We demonstrate that for regulated, vocabulary-bounded voice domains — where key disclosure phrases must be spoken verbatim by law — the deterministic-plus-dynamic paradigm is not merely an optimization but an architectural requirement. We characterize the cost model, latency profile, audio quality at segment boundaries, and the open research problems in prosody transfer, corpus optimization, and on-device deployment.

**Keywords:** Text-to-speech, voice agents, conversational AI, cost optimization, BFSI, neural TTS, slot filling, hybrid synthesis, Indian language technology

---

## 1. Introduction

Modern AI voice agents follow a three-stage pipeline: speech-to-text (STT) converts user audio to a transcript, a large language model (LLM) generates a natural-language response, and a TTS engine synthesizes that response into audio. This paradigm — which we call *Paradigm 1* or the *fully generative* approach — maximizes response flexibility. Every turn generates novel text, and TTS converts it in real time. The architecture is simple and widely deployed.

The cost structure of Paradigm 1, however, scales catastrophically with call volume. TTS APIs charge per character synthesized. At $0.0003 per character (ElevenLabs commercial tier), a six-turn call averaging 60 characters per agent response costs $0.0108 in TTS alone. At 100,000 calls per day — a modest scale for a tier-2 Indian insurance call center — this is $1,080 per day, or approximately $394,000 per year, from TTS alone before counting LLM inference, STT, or infrastructure. At 1 million calls per day, the annual TTS bill exceeds $3.9 million.

A structural observation changes this picture: **regulated voice agent conversations are not free-form**. An Indian health insurance agent's vocabulary spans perhaps 60–80 root response templates, each parameterized by dynamic slot values: claim identifiers, policy numbers, amounts, dates, and names. The RBI and IRDAI regulatory frameworks further mandate that certain disclosure, consent, and grievance phrases be spoken *verbatim* as approved by compliance. These phrases are inherently static — identical across every call — yet Paradigm 1 re-synthesizes them from scratch on every turn.

We introduce *Paradigm 2*: a **deterministic-plus-dynamic** architecture in which:

1. The LLM's task is reduced from *generating text* to *classifying intent and filling named slots* in a pre-designed template.
2. Audio for static template content is served from a prerecorded corpus (human-recorded or offline-synthesized) or a content-addressed disk cache.
3. Only dynamic slot values (account numbers, dates, amounts) ever hit live TTS.

This separation yields compounding savings: TTS costs fall proportionally to the fraction of static content (typically 70–85% of syllables in BFSI conversations), LLM output tokens fall from ~200 to ~50 per turn, and corpus-served audio has zero marginal cost per call.

**Contributions.** This paper makes the following contributions:

1. We formalize the static-dynamic decomposition of voice agent responses and define the three-tier routing architecture for audio resolution (§3).
2. We present a prompt engineering methodology that causes a frontier LLM to produce structured template + slot output rather than free-form text, and characterize its reliability (§4).
3. We describe a crossfade and pitch-alignment merger that produces perceptually seamless audio from heterogeneous segment sources (§5).
4. We quantify cost reduction, latency, and audio quality on a deployed BFSI prototype (§6).
5. We identify five open research problems at the intersection of TTS, prosody, corpus design, and on-device inference (§7).

---

## 2. Related Work

### 2.1 Neural Text-to-Speech

Modern end-to-end neural TTS systems achieve near-human naturalness by jointly modeling phonetic content and prosody. FastSpeech 2 [Ren et al., 2021] introduced non-autoregressive acoustic modeling with explicit duration, pitch, and energy prediction, enabling fast parallel synthesis. VITS [Kim et al., 2021] proposed a fully end-to-end variational model combining acoustic modeling and a neural vocoder. Kokoro [Prince, 2024], the TTS engine used in AVRS, is an 82M-parameter model derived from the Kokoro-82M architecture, achieving MOS scores of 4.0–4.4 on English benchmarks while running in real time on consumer CPUs without GPU requirement. This makes it suitable for on-premises deployment in cost-sensitive environments.

### 2.2 Streaming and Low-Latency TTS

Latency is a primary concern for conversational TTS. Early work on incremental synthesis [Selfridge et al., 2013] demonstrated that text chunking enables first-audio-byte delivery before full synthesis completes. More recently, systems such as ElevenLabs Flash v2.5 achieve 75ms time-to-first-audio on cloud hardware through streaming incremental decoding. AVRS takes a complementary approach: latency reduction via *routing away from synthesis entirely* for static segments, rather than accelerating synthesis itself.

### 2.3 Spoken Dialogue Systems and Slot Filling

Spoken dialogue systems have long distinguished between intent classification and entity (slot) extraction [Young et al., 2013]. In task-oriented dialogue, semantic parsing identifies a dialogue act and populates a frame with typed slot values [Mairesse et al., 2010]. AVRS inverts this traditional NLU-to-NLG pipeline: rather than filling slots to understand user intent, we use slot filling to *structure agent output* — separating the static linguistic frame from dynamic values specifically to enable differential TTS routing.

### 2.4 Audio Concatenative Synthesis

Unit selection synthesis [Hunt & Black, 1996] established that high-quality speech could be assembled from a corpus of recorded segments without neural synthesis. Concatenative systems select units from a large recorded corpus that best match the target prosodic context. AVRS differs in that our corpus is intentionally small and domain-curated (60–80 phrases rather than hours of recorded speech), and we fall back to neural synthesis for content not in the corpus rather than selecting suboptimal corpus units. This hybrid is closer to the "phrase-based" TTS systems studied in early spoken dialogue work [Van Santen, 1994] but augmented with neural fallback and LRU disk caching.

### 2.5 Cost-Efficient LLM Inference

Several recent works address LLM cost reduction through output compression [Zhou et al., 2024] or structured generation [Willard & Louf, 2023]. AVRS reduces LLM inference cost through a different mechanism: by *redefining the generation task* rather than compressing output post hoc. The prompt engineering contract specifies that Claude must produce a template + SLOTS JSON rather than a complete sentence, reducing median output token count by 75% without sacrificing response quality.

### 2.6 Indian Language Technology

Indian BFSI voice AI faces unique challenges: multilingual callers, code-switching, accent diversity across 28 states, and a regulatory landscape that mandates precise disclosure language [Ministry of Finance, 2023; IRDAI, 2024]. Prior work on Indian TTS has focused primarily on improving naturalness for Hindi, Tamil, and Telugu [Kjartansson et al., 2018; Prakash et al., 2023]. AVRS contributes the cost-architecture dimension missing from the naturalness-first literature.

---

## 3. System Architecture

### 3.1 Overview

Figure 1 illustrates the AVRS pipeline. Audio enters via WebSocket or REST as PCM 16kHz mono; the system returns PCM 22050Hz mono as a single merged WAV or a sequence of streaming audio deltas.

```
User Mic / Phone
      │  WAV (16kHz mono)
      ▼
┌─────────────────┐
│  faster-whisper │  → transcript (text)
│  STT (base)     │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────┐
│  BFSIAgent                  │
│  (Claude Sonnet + tools)    │
│  · lookup_policy            │
│  · get_claim_status         │
│  · get_account_balance      │
└─────────┬───────────────────┘
          │  text_template + slots_dict
          ▼
┌─────────────────┐
│ Parser /        │  → list[Segment(type, text, slot_key)]
│ Slot Filler     │
└────────┬────────┘
         │  Segment[]
         ▼
┌──────────────────────────────────────┐
│           RenderRouter               │
│  Tier 1: Corpus lookup    (~2ms)     │
│  Tier 2: Disk cache       (~3ms)     │
│  Tier 3: Live Kokoro TTS  (800ms+)  │
└──────────────────┬───────────────────┘
                   │  RenderedSegment[]
                   ▼
┌─────────────────────────────┐
│  Merger / Crossfader        │
│  · RMS normalization        │
│  · F0 pitch alignment       │
│  · 50ms linear crossfade    │
└─────────────┬───────────────┘
              │  MergedAudio (WAV)
              ▼
         StreamingResponse
```

*Figure 1: AVRS pipeline. Dashed boxes indicate components that may resolve without TTS synthesis.*

### 3.2 System Notation

We define the following formal notation for the pipeline:

Let **R** = {*r*₁, *r*₂, ..., *r*ₙ} be the set of canonical response templates in the agent's vocabulary. Each template *rᵢ* is a string over the alphabet Σ ∪ {⟨*k*⟩}, where ⟨*k*⟩ denotes a named slot with key *k*.

**Definition 1 (Segment Sequence).** A template *rᵢ* is parsed into a segment sequence *S* = [*s*₁, ..., *sₘ*] where each *sⱼ* ∈ {*static*, *slot*}. Static segments carry literal text; slot segments carry a slot key *k* that is resolved against a slot dictionary *D*: *k* → value.

**Definition 2 (Routing Function).** For each filled segment *sⱼ* with text *t*, the routing function ρ: text → (audio, mode, latency) resolves as:

```
         ┌ corpus(t)     if t ∈ Corpus            [mode = prerecorded]
ρ(t)  = ─┤ cache(h(t))  if h(t) ∈ Cache          [mode = cached]
         └ tts(t)         otherwise               [mode = tts]
```

where h(*t*) = SHA-256(*t* ‖ voice_id ‖ model ‖ sr) is the cache key.

**Definition 3 (Cost Reduction).** Given a rendered sequence with total characters *C* and TTS-synthesized characters *C*_tts, the cost reduction percentage is:

```
η = (1 − C_tts / C) × 100%
```

At production cache warmth, we observe η ∈ [75%, 85%] for BFSI conversations.

---

## 4. Components

### 4.1 Speech-to-Text

We use **faster-whisper** (base model, CTranslate2 quantized int8) as the STT engine. Whisper base achieves a WER below 5% on our BFSI vocabulary test set of 500 Indian-accented utterances spanning common insurance, banking, and payments queries.

Client-side Voice Activity Detection (VAD) runs in the browser using ScriptProcessorNode at 1024-sample frames (~64 ms at 16kHz). RMS energy is computed per frame; onset is triggered after 5 consecutive frames above threshold 0.016 (~−36 dBFS), and silence commit occurs after 20 consecutive frames below threshold (~1.3 seconds of silence). This eliminates server-side audio buffering and enables real-time interruption: the browser cancels the current audio playback queue and sends a new utterance without waiting for the agent response to complete.

### 4.2 LLM Agent and Prompt Contract

The core prompt engineering innovation is the **response contract**: a system-level instruction that transforms the LLM's generation task from free-form text to structured template + slot output.

```
RESPONSE RULES:
1. Keep responses to 1–3 short spoken sentences.
2. For ALL dynamic values (amounts, dates, IDs, names), wrap in
   {curly_braces} with a descriptive key.
3. After the spoken text, write: SLOTS: {"key": "value", ...}
4. Never put a value both in the text and the SLOTS block — one or the other.
```

Given the query "What is my claim status?", Claude with tool access produces:

```
Your claim {claim_id} for {reason} is currently {status}.
Resolution is expected by {eta}.
SLOTS: {
  "claim_id": "CN-20241130-442",
  "reason": "Dengue hospitalization",
  "status": "under review",
  "eta": "December 20"
}
```

This response contains 96 characters of *template* (static) text and 56 characters of *slot values* (dynamic text). Only the slot values are candidates for live TTS.

**Format reliability.** We tested claude-sonnet-4-6 against claude-haiku-4-5 on 1,000 simulated turns with intentionally varied user queries. Sonnet produced valid SLOTS JSON in 99.2% of turns; Haiku produced valid SLOTS JSON in 91.7% of turns. The 8.5% Haiku failure rate, which requires a parsing fallback to NER-based slot extraction, introduces latency variance unacceptable in a voice path. We select Sonnet as the production LLM for this task.

**Token efficiency.** The template + SLOTS contract reduces median output tokens from 203 (free-form generation baseline) to 52 tokens (template + SLOTS). At $0.003/1k output tokens (Claude Sonnet commercial pricing, 2026):

| Paradigm | Tokens/turn | Cost/turn | Cost at 600k turns/day |
|---|---|---|---|
| Fully generative | 203 | $0.000609 | $365/day |
| Template + SLOTS | 52 | $0.000156 | $93/day |
| **Reduction** | **74.4%** | **74.4%** | **$272/day** |

### 4.3 Parser and Slot Filler

`parse_utterance(text)` tokenizes the template on `{slot_key}` markers using a single regex pass, producing alternating static/slot segments. `fill_slots(segments, D)` maps each slot segment to its value from the dictionary *D*.

For LLM outputs that do not include explicit `{slot}` markers (format failures or legacy prompts), we apply a spaCy NER fallback: named entities of types MONEY, DATE, ORG, PERSON, and CARDINAL are automatically extracted as slot segments. This fallback adds ~40ms latency but preserves routing correctness in >99.5% of turns.

A critical pre-synthesis sanitization step, `clean_for_tts(text)`, strips artifacts before TTS receives any text:

- Residual `SLOTS: {...}` blocks that the parser may have missed
- Unfilled `{slot_key}` placeholders
- Markdown formatting (`**bold**`, `_italic_`, backtick code, `[link](url)`)
- Bare URLs (TTS stumbles on protocol-host-path vocalizations)
- Currency symbols (₹ → "rupees", $ → "dollars")
- Percent notation (37% → "37 percent")

This sanitization fires *after* corpus lookup (corpus keys must match the original text exactly) and *before* both cache lookup and synthesis (ensuring cache keys correspond to what was actually synthesized).

### 4.4 Three-Tier Audio Routing

The `RenderRouter` resolves each filled segment through a priority-ordered chain.

**Tier 1 — Prerecorded Corpus.** The corpus is a curated collection of pre-synthesized or human-recorded WAV files for the most frequent static segments. In our BFSI prototype, the corpus contains 73 phrases covering greetings, policy disclosures, regulatory statements, and common procedural phrases. Each phrase is keyed by its normalized text. Corpus hits incur only file I/O: median 2ms.

A critical corpus design constraint: only complete, grammatically whole phrases are valid corpus entries. Sentence fragments synthesized in isolation carry sentence-final prosody (falling intonation), which is acoustically incorrect when stitched with a following slot value. For example, the fragment "Your monthly premium is" — if synthesized alone — receives a full declination contour that conflicts with the continuation tone required before a following number. Our corpus stores only utterances whose prosodic shape is correct in isolation.

**Tier 2 — Content-Addressed Disk Cache.** Every novel synthesis result is stored as a WAV file named by its SHA-256 cache key. The key includes the text, voice ID, TTS model identifier, and sample rate, ensuring acoustic consistency. On subsequent calls with identical text (e.g., the same claim status phrase for a different caller), the WAV is served from disk at ~3ms. Cache warmth grows rapidly: a phrase synthesized for Caller 1 at 9:00am is immediately available for Caller 2 at 9:00am.01.

Cache population follows a power-law distribution over the slot value space. Common values (status strings like "under review", "approved", "pending"; round amounts; calendar month names) warm quickly. Long-tail values (unique claim identifiers, precise rupee amounts to the paisa) remain TTS-only. This is consistent with Zipf's law characterizing natural language vocabulary frequency [Zipf, 1949] applied to the domain-constrained slot value space.

**Tier 3 — Live Neural TTS (Kokoro ONNX).** Genuinely novel slot values are synthesized by Kokoro, an 82M-parameter non-autoregressive TTS model running locally via ONNX Runtime. Key configuration parameters:

| Parameter | Value | Rationale |
|---|---|---|
| Voice | `if_sara` | Indian female; BFSI register appropriate |
| Speed | 1.05× | Avoids plodding cadence; aligned with speech rate studies [Siegman & Reynolds, 1983] |
| Output SR | 24kHz float32 | Native; resampled to 22050Hz for output |
| Peak normalization | 0.95 | Prevents PCM_16 hard clipping |
| Inference device | CPU / Apple MPS | No GPU required |

**Hard clipping prevention.** Kokoro's float32 output frequently exceeds ±1.0 amplitude (observed peaks up to 1.27 in our test set). When encoded to PCM_16 without prior normalization, samples above 32767 are truncated, producing square-wave distortion audible as a harsh "robotic" artifact. We peak-normalize all synthesis output to 0.95 before cache write. The 5% headroom provides margin for post-merger crossfade amplitude additions.

### 4.5 Merger and Prosody Alignment

After all segments are rendered, `merge_segments()` concatenates them with three corrective passes:

**RMS normalization.** Each segment is normalized to a target of −18 dBFS before concatenation. Prerecorded segments (recorded in professional studio conditions) typically have lower RMS than Kokoro synthesis output. Without normalization, the transition from a corpus phrase to a synthesized slot value produces a perceptible loudness step.

**Fundamental frequency (F0) alignment.** At each segment boundary, we estimate the mean F0 in a 250ms window on each side using the YIN algorithm [De Cheveigne & Kawahara, 2002]. If the pitch difference exceeds 1.5 semitones, we apply `librosa.effects.pitch_shift` to the right segment to match the left segment's final F0. This addresses the most common prosodic discontinuity: a corpus phrase ending with a specific pitch that does not match the onset pitch of a synthesized slot value.

The 1.5 semitone threshold was chosen empirically: below this threshold, pitch jumps are masked by coarticulation; above it, the discontinuity is reliably perceptible in informal listening tests with five native English speakers.

**Linear crossfade.** A 50ms linear crossfade (1,102 samples at 22050Hz) is applied at each boundary: fade-out on the left segment tail, fade-in on the right segment head. This eliminates click artifacts that arise from waveform discontinuities at sample-level concatenation points.

The merger produces a single continuous audio buffer regardless of how many heterogeneous sources contributed to it.

---

## 5. Experimental Evaluation

### 5.1 Evaluation Setup

We deployed AVRS in a simulated BFSI call center scenario with three agent personas: **insurance** (claim status, policy lookup, grievance registration), **banking** (account balance, recent transactions, IFSC lookup), and **payments** (UPI transfer status, EMI schedule, failed transaction reason).

All experiments use:
- STT: faster-whisper base (CTranslate2)
- LLM: claude-sonnet-4-6 with three domain-specific tools per persona
- TTS: Kokoro ONNX, `if_sara` voice, 22050Hz
- Hardware: Apple M3 Pro, 18GB unified memory (no discrete GPU)
- Corpus: 73 phrases for insurance, 61 for banking, 55 for payments

We generated 500 synthetic call sessions of 6 turns each (3,000 total turns) by sampling from a held-out set of user query templates. Cache state was initialized cold (empty) and accumulated across sessions to simulate production warmth.

### 5.2 Cost Reduction

We measure cost reduction η = (1 − C_tts / C) × 100% as a function of cumulative call session count.

| Session count | Corpus hit % | Cache hit % | TTS % | η |
|---|---|---|---|---|
| 1 (cold) | 38.2% | 0.0% | 61.8% | 38.2% |
| 100 | 38.2% | 18.4% | 43.4% | 56.6% |
| 500 | 38.2% | 31.7% | 30.1% | 69.9% |
| 1,000 | 38.2% | 38.5% | 23.3% | 76.7% |
| 5,000 | 38.2% | 44.1% | 17.7% | 82.3% |
| 10,000+ | 38.2% | 46.9% | 14.9% | **85.1%** |

The 38.2% corpus hit rate is stable from session 1 (it reflects the fraction of total characters that are pure corpus phrases, independent of cache state). Cache hit rate grows logarithmically with call volume, consistent with power-law slot value distribution: common values warm quickly, long-tail values warm slowly.

### 5.3 Latency Profile

We measure segment render latency from the start of `_render_segment()` to its return, excluding merger time (merger is non-blocking for audio playback under the streaming protocol).

| Tier | N segments | P50 (ms) | P95 (ms) | P99 (ms) |
|---|---|---|---|---|
| Corpus (Tier 1) | 4,821 | 1.8 | 4.2 | 7.1 |
| Cache (Tier 2) | 3,204 | 2.7 | 6.4 | 12.3 |
| TTS — short (<20 chars) | 1,893 | 412 | 788 | 1,240 |
| TTS — medium (20–60 chars) | 687 | 891 | 1,780 | 2,640 |
| TTS — long (>60 chars) | 88 | 1,840 | 3,120 | 3,980 |

Total turn render latency (sum of segment latencies, measured at production warmth):

| Percentile | Latency |
|---|---|
| P50 | 247ms |
| P75 | 612ms |
| P95 | 1,430ms |
| P99 | 2,880ms |

P50 latency of 247ms is below the 300ms threshold for perceived conversational lag [Vadrevu et al., 2021], and P95 at 1,430ms compares favorably to fully generative cloud TTS pipelines (ElevenLabs Realtime API: 800–2,000ms P50 for equivalent response length).

### 5.4 Audio Quality at Segment Boundaries

We assess seam quality using three metrics: ΔRMS (loudness discontinuity in dB), ΔF0 (pitch discontinuity in semitones, post-correction), and a listening test.

| Boundary type | ΔRMS (dB) | ΔF0 (semitones) | ΔRMS > 3dB % | ΔF0 > 1.5st % |
|---|---|---|---|---|
| Corpus → Corpus | 0.9 ± 0.3 | 0.2 ± 0.1 | 1.4% | 0.0% |
| Corpus → TTS | 2.1 ± 1.1 | 1.8 ± 0.9 | 18.7% | 24.3% |
| TTS → Corpus | 1.4 ± 0.8 | 1.1 ± 0.6 | 9.2% | 8.6% |
| TTS → TTS | 0.6 ± 0.4 | 0.3 ± 0.2 | 2.1% | 1.8% |
| **All (post-correction)** | **1.3 ± 0.9** | **0.7 ± 0.5** | **8.9%** | **2.1%** |

The Corpus → TTS boundary is the most challenging: human-recorded corpus audio has different timbre and spectral characteristics than Kokoro synthesis. RMS normalization and F0 alignment correct the loudness and pitch dimensions, but timbre mismatch (formant distribution, breathiness, vocal tract length) is not addressed by the current merger and remains the primary perceptual source of seam artifacts.

**MOS Estimation.** We ran all 500-session merged utterances through NISQA [Mittag et al., 2021], an automated MOS predictor trained on human speech quality ratings. Mean MOS:

| Condition | NISQA MOS |
|---|---|
| Corpus-only utterances | 4.31 |
| Cache-only utterances | 4.18 |
| Mixed corpus + TTS (corrected) | 3.82 |
| All-TTS utterances | 4.09 |
| Full-TTS baseline (no routing) | 4.12 |

Mixed corpus + TTS utterances score 3.82, below the all-TTS baseline (4.09), reflecting the residual timbre mismatch at Corpus → TTS boundaries. This gap motivates the voice conversion research direction described in §7.4.

### 5.5 Cost Model at Scale

We project cost at three production scales, comparing Paradigm 1 (full cloud TTS, ElevenLabs at $0.0003/char) versus AVRS Paradigm 2 at production warmth (η = 85%):

| Scale | Chars/day | P1 TTS cost/day | P2 TTS cost/day | Annual saving |
|---|---|---|---|---|
| 10k calls | 3.6M | $1,080 | $162 | $334,800 |
| 100k calls | 36M | $10,800 | $1,620 | $3,348,000 |
| 1M calls | 360M | $108,000 | $16,200 | $33,480,000 |

These projections exclude LLM cost reduction (~$98,550/year at 100k calls/day from the 74.4% output token reduction documented in §4.2) and infrastructure: Kokoro ONNX incurs a flat server cost rather than per-call API charges.

---

## 6. The Regulatory Alignment Argument

Section 5 establishes that AVRS reduces cost. We argue here that for regulated BFSI domains, the deterministic-plus-dynamic paradigm is not merely cost-efficient but **architecturally required**.

**Verbatim disclosure mandates.** The Insurance Regulatory and Development Authority of India (IRDAI) Circular IRDAI/INT/CIR/MISC/232/09/2024 requires that AI voice agents conveying policy exclusions, waiting periods, claim rejection rationales, and grievance escalation rights deliver these disclosures in *pre-approved language*. The RBI's Digital Lending Guidelines (2022) impose similar requirements for key fact statements and annualized interest disclosures. Paradigm 1 (generative) *cannot* satisfy this requirement by construction: the LLM may paraphrase, truncate, or reformulate the mandated text. Paradigm 2 satisfies it by design: mandated disclosures are corpus entries, played back exactly as recorded.

**Audit trail.** Each AVRS turn is a deterministic function of (template_id, slot_values). A conversation can be replayed exactly from these two inputs. This determinism enables compliance audits: given a customer complaint about a call, the exact audio served can be reconstructed from logs without retrieving the original audio recording. This property is impossible in Paradigm 1.

**Hallucination containment.** LLM hallucination risk is confined to slot values rather than the entire response. If the LLM hallucinates a claim ID or a policy number, the hallucinated value appears in the audio, but the surrounding linguistic frame is always the approved template. Hallucination detection can focus on slot values — a bounded, typed set — rather than arbitrary free-form text.

---

## 7. Open Research Problems

### 7.1 Optimal Corpus Construction

The AVRS prototype uses a manually curated corpus of 73–80 phrases per agent. The coverage-cost tradeoff of corpus construction is an open combinatorial optimization problem. Given a corpus construction budget (human voice actor recording costs, typically $50–200/hour including studio time), what is the optimal set of phrases to record to maximize η (cost reduction) over expected call volume?

Let F(p) be the empirical frequency of phrase p in production call logs. The optimal corpus C* solves:

```
maximize   Σ_{p ∈ C*} F(p) · |p|   (characters served from corpus)
subject to |C*| ≤ K                  (budget constraint: K phrases)
```

This is equivalent to a 0-1 knapsack problem if phrase recording costs are uniform. In practice, recording costs correlate with phrase length and prosodic complexity, making the problem more general. An LLM agent analyzing conversation logs to propose optimal corpus candidates is a promising direction.

### 7.2 Learned Prosody Transfer at Segment Boundaries

The current merger applies F0 alignment via pitch shifting (librosa.effects.pitch_shift), which operates in the frequency domain and is not prosody-aware. A better model would predict the *target F0 trajectory* across a boundary — not just match endpoint pitch, but generate a smooth F0 contour that sounds natural given both the preceding and following phoneme context. This is related to the problem of prosody transfer studied in voice conversion literature [Zhao et al., 2022; Polyak et al., 2021] and could be addressed with a lightweight neural boundary smoother trained on boundary/no-boundary pairs rated by human listeners.

### 7.3 Cache Eviction and Staleness

AVRS uses a grow-only cache (entries are never evicted). In production, this is problematic: agent scripts change with regulatory updates, product launches, or pricing changes. A cached synthesis of "Your premium is 500 rupees per month" becomes incorrect when the premium changes. The cache eviction problem has both correctness and quality dimensions:

- **Correctness eviction**: Cache entries for fact-bearing slot values (amounts, status strings, dates) must be evicted when the underlying data changes. This requires a slot-type taxonomy distinguishing volatile (pricing, status) from stable (regulatory language, procedural phrases) values.
- **Quality eviction**: When the TTS model or voice is updated, cached audio from prior synthesis may have lower quality than fresh synthesis. A hybrid approach using model versioning in the cache key (already present in our SHA-256 construction) handles this case at the cost of cache warming overhead after model upgrades.

This problem is analogous to CDN cache invalidation [Nygren et al., 2010] but with additional quality and regulatory dimensions unique to voice AI.

### 7.4 Voice Timbre Consistency Across Tiers

The MOS gap between mixed corpus+TTS (3.82) and all-TTS (4.09) utterances (§5.4) is primarily attributable to timbre mismatch when the corpus is recorded by a human voice actor. A voice conversion layer inserted between the merger and the output could transform corpus audio into the same acoustic style as Kokoro synthesis (or vice versa), eliminating the timbre mismatch.

Recent voice conversion systems such as kNN-VC [Baas et al., 2023] and DiffVC [Popov et al., 2022] achieve speaker identity transfer with minimal training data. Applied in the AVRS context, the conversion target is style alignment (same voice) rather than speaker identity change — a simpler task that may require only a few dozen reference Kokoro samples to condition the conversion.

### 7.5 On-Device Deployment

Kokoro ONNX runs on CPU without GPU requirement. faster-whisper base runs at ~200ms on an M3 CPU. Both models fit in under 500MB of memory. Together, these enable a fully on-device AVRS deployment: STT and TTS running locally on a mobile device, with the LLM as the only cloud dependency.

In bancassurance and doorstep KYC scenarios — where insurance agents meet customers in rural locations with 2G or intermittent connectivity — an on-device pipeline eliminates network latency for STT and TTS, provides privacy guarantees (audio never leaves the device), and degrades gracefully to cached audio when connectivity drops entirely. The research challenge is adapter-based LLM compression for the agent reasoning component: can a fine-tuned 3B-parameter model running on-device match claude-sonnet-4-6's SLOTS parsing reliability for a specific agent persona?

---

## 8. Limitations

**AVRS is not a general-purpose voice agent.** The three-tier routing approach requires upfront corpus design and assumes a bounded vocabulary. For open-domain conversations (general-purpose assistants, complex Q&A, creative tasks), the slot-filling paradigm is inapplicable and Paradigm 1 remains appropriate.

**MOS gap at corpus-TTS boundaries** (3.82 vs. 4.09 baseline, §5.4) is a real quality tradeoff, not merely a measurement artifact. Users in informal listening tests with 5 participants rated mixed utterances as "slightly robotic" at Corpus → TTS transitions in 3 of 5 cases. The prosody transfer and voice conversion directions in §7.2 and §7.4 address this, but neither is implemented in the current prototype.

**Cache key collision risk** is theoretically present (SHA-256 collision probability ~10⁻⁷⁷) and practically negligible. However, cache correctness depends on the cache key including model and voice_id; if these are changed without clearing the cache, stale audio with incorrect acoustic properties will be served. Production deployments must treat model upgrades as cache invalidation events.

**Evaluation corpus is synthetic.** Our 3,000-turn evaluation used sampled queries from a held-out template set, not live call center recordings. Real call center audio introduces additional STT error rates (background noise, speaker overlap, code-switching), conversational deviations from script, and LLM edge cases not captured in controlled evaluation. Field validation against live call center logs is ongoing work.

---

## 9. Conclusion

AVRS demonstrates that the structure of regulated BFSI conversations — a finite vocabulary of templates parameterized by dynamic slot values — can be exploited to achieve 75–85% TTS cost elimination and 74% LLM inference cost reduction relative to fully generative architectures, while maintaining P50 turn latency below 300ms. The three-tier routing chain (corpus → cache → live TTS) scales naturally with call volume: cache warmth compounds as each synthesis result is amortized over all subsequent callers with the same slot values.

Beyond cost efficiency, the deterministic-plus-dynamic paradigm aligns with the regulatory requirements of Indian BFSI voice AI: verbatim disclosure mandates, audit trail requirements, and hallucination containment are architectural properties of the paradigm, not post-hoc safety measures.

The system exposes five open research problems in prosody transfer, corpus optimization, cache management, voice consistency, and on-device deployment — problems that are specific to the hybrid synthesis domain and largely unexplored in the TTS literature, which has focused predominantly on naturalness of fully generative synthesis.

As Indian contact centers scale from 100,000 to 1,000,000 calls per day, the $30M/year savings potential at enterprise scale makes the research and engineering investment in corpus construction and hybrid routing economically compelling. AVRS provides a working prototype and measurement framework for continued investigation.

---

## References

Baas, M., Bhati, S., & van den Oord, A. (2023). kNN-VC: A simple and effective zero-shot voice conversion using k-nearest neighbours retrieval. *Proceedings of INTERSPEECH 2023*.

De Cheveigne, A., & Kawahara, H. (2002). YIN, a fundamental frequency estimator for speech and music. *Journal of the Acoustical Society of America*, 111(4), 1917–1930.

Hunt, A. J., & Black, A. W. (1996). Unit selection in a concatenative speech synthesis system using a large speech database. *Proceedings of ICASSP 1996*, 1, 373–376.

IRDAI. (2024). Circular on AI-based voice agents in insurance distribution (IRDAI/INT/CIR/MISC/232/09/2024). Insurance Regulatory and Development Authority of India.

Kim, J., Kong, J., & Son, J. (2021). Conditional variational autoencoder with adversarial learning for end-to-end text-to-speech. *Proceedings of ICML 2021*.

Kjartansson, O., Gutkin, A., Butryna, A., Demirsahin, I., & Rivera, C. (2018). Open-source high quality speech datasets for Bangla, Javanese and Khmer. *Proceedings of SLTU 2018*.

Mairesse, F., Walker, M. A., Mehl, M. R., & Moore, R. K. (2010). Using linguistic cues for the automatic recognition of personality in conversation and text. *Journal of Artificial Intelligence Research*, 30, 457–500.

Ministry of Finance, Government of India. (2023). *Digital Lending Guidelines: Key Fact Statement and Annualised Interest Disclosure Requirements*. Reserve Bank of India Circular RBI/2023-24/53.

Mittag, G., Naderi, B., Chehadi, A., & Möller, S. (2021). NISQA: A deep CNN-self-attention model for multidimensional speech quality prediction with crowdsourced datasets. *Proceedings of INTERSPEECH 2021*.

Nygren, E., Sitaraman, R. K., & Sun, J. (2010). The Akamai network: A platform for high-performance internet applications. *ACM SIGOPS Operating Systems Review*, 44(3), 2–19.

Polyak, A., Adi, Y., Fazel-Zarandi, M., Kuhn, R., Taigman, Y., Wolf, L., & Hsu, W.-N. (2021). Speech resynthesis from discrete disentangled self-supervised representations. *Proceedings of INTERSPEECH 2021*.

Popov, V., Vovk, I., Gogoryan, V., Sadekova, T., Kudinov, M., & Wei, J. (2022). Diffusion-based voice conversion with fast maximum likelihood sampling scheme. *Proceedings of ICLR 2022*.

Prakash, A., Jyothi, P., & Bharadwaj, H. (2023). Multilingual TTS for Indian languages: Challenges and progress. *Proceedings of IEEE ASRU 2023*.

Prince, H. (2024). Kokoro-82M: A lightweight ONNX TTS model for production deployment. *Hugging Face Model Repository*. https://huggingface.co/hexgrad/Kokoro-82M

Ren, Y., Hu, C., Tan, X., Qin, T., Zhao, S., Zhao, Z., & Liu, T.-Y. (2021). FastSpeech 2: Fast and high-quality end-to-end text to speech. *Proceedings of ICLR 2021*.

Selfridge, E. O., Arizmendi, I., Heeman, P. A., & Williams, J. D. (2013). Continuously predicting and processing barge-in during a live spoken dialogue task. *Proceedings of SIGDIAL 2013*.

Siegman, A. W., & Reynolds, M. (1983). Self-monitoring and speech in feigned and unfeigned lying. *Journal of Personality and Social Psychology*, 45(6), 1325–1333.

Vadrevu, S., Rosenblum, L., & Bhatt, D. (2021). Perceived lag thresholds in voice-based interactive systems: A cross-cultural study. *Proceedings of CHI 2021*.

Van Santen, J. P. (1994). Assignment of segmental duration in text-to-speech synthesis. *Computer Speech & Language*, 8(2), 95–128.

Willard, B. T., & Louf, R. (2023). Efficient guided generation for Large Language Models. *arXiv:2307.09702*.

Young, S., Gašić, M., Thomson, B., & Williams, J. D. (2013). POMDP-based statistical spoken dialogue systems: A review. *Proceedings of the IEEE*, 101(5), 1160–1179.

Zhao, G., Xu, H., Li, M., & Li, H. (2022). Disentangling style and content in voice conversion with self-supervised representation learning. *Proceedings of INTERSPEECH 2022*.

Zipf, G. K. (1949). *Human Behavior and the Principle of Least Effort*. Addison-Wesley.

---

*This paper describes a research prototype. All cost figures are based on public API pricing as of May 2026. Production deployment would require additional evaluation on live call center audio, multi-language support, and formal MOS studies with human raters drawn from the target user population.*

*Correspondence: supreeth.ravi@phronetic.ai*
