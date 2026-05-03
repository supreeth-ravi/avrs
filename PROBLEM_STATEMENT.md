# Problem Statement

## Context

Voice AI agents in India (insurance, banking, payments) must deliver
personalised, dynamic utterances to millions of users per day. Existing
full speech-to-speech synthesis costs ~$165/1M characters (ElevenLabs /
OpenAI TTS) — economically non-viable at Indian market scale.

## Problem

No system exists that intelligently routes each agent utterance to the
cheapest viable render path while preserving a single coherent voice
identity across all rendering modes.

## Formal Statement

Given a dynamic agent utterance containing static phrase segments and
variable data slots, design a real-time hybrid voice rendering system that:

1. Maximises the proportion of audio served from pre-recorded or cached
   sources.
2. Synthesises only the irreducible dynamic segments using open-weight TTS
   conditioned on a speaker reference.
3. Merges all segments into a perceptually seamless audio stream with no
   detectable boundary artifacts.
4. Quantifies cost reduction against a full-TTS baseline.

## Hypothesis

A hybrid render system routing ≥70% of utterance content to pre-recorded
or cached audio reduces TTS API cost by ≥80% versus full synthesis, while
achieving a seam MOS delta of <0.2 — making voice agents economically
viable at Indian market scale.

## Sub-problems

**P1 — Utterance decomposition:** Reliable slot detection at word/phrase
granularity in real time. Supports both annotated `{placeholder}` syntax
and automatic NER-based detection via spaCy.

**P2 — Acoustic seam consistency:** Merging audio from different sources
without perceptible boundary artifacts. AVRS applies per-boundary pitch
correction (librosa pitch shift when Δ > 1.5 semitones), RMS normalisation
to −18 dBFS, and 15 ms linear crossfade at every segment boundary.

**P3 — Cost instrumentation:** Reproducible per-utterance cost and latency
metrics for paper reporting. AVRS tracks segment-level render mode,
character counts, and computes cost against a $0.165/1M-char baseline.

## Evaluation

- **Cost metric:** `cost_reduction_pct` — percentage reduction versus
  baseline of synthesising the full utterance text.
- **Quality metric:** NISQA MOS score difference between AVRS-merged audio
  and full-TTS baseline (target: Δ MOS < 0.2).
- **Latency metric:** per-utterance `latency_total_ms` (target: < 500 ms
  p95 in cached/prerecorded path).

## Research Affiliation

Phronetic AI — MIT Paper on Hybrid Voice Rendering for Cost-Sensitive
Deployments (2024/2025).
