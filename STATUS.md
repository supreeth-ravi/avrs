# AVRS / Pickr — Current Status

**Snapshot:** 2026-05-10
**Branch:** `main` (up to date with `origin/main`)
**Last commit:** `a676f4b fix: Docker build and missing dependencies`

This file is a working snapshot of where the codebase stands today, what is committed vs in-flight, and what is wired up end-to-end. It is not historical documentation — overwrite or update it as the project evolves.

---

## TL;DR

The repo has evolved from the original **AVRS** research prototype (hybrid TTS routing, MIT/Phronetic paper) into a **multi-tenant voice screening product called Pickr** built on top of AVRS.

- **AVRS core (committed):** parser → corpus → router → merger → metrics pipeline + Kokoro/mock TTS + Deepgram/Whisper STT + FastAPI WebSocket voice agent. Ships with three BFSI personas (insurance / banking / payments).
- **Pickr layer (uncommitted, working tree only):** OTP/auth, multi-tenant user store with pricing tiers, virtual number pool, Exotel + Plivo telephony bridges, a `screener` persona for AI call screening, and an Android client (`ai.phronetic.screener`).
- 11 unstaged/untracked changes; nothing has been committed yet for the Pickr direction.

---

## What Is Committed (AVRS Research Prototype)

Recent commit history on `main`:

```
a676f4b fix: Docker build and missing dependencies
5b6166a docs: README, architecture diagrams, and distribution config
8913b27 chore: Docker setup for zero-friction distribution
586f363 feat: phrase corpus data, build scripts, and usage examples
8afccba test: unit tests for parser, merger, router, and metrics
2faf908 feat: LLM agent with tool use and externalised persona config
288e8f5 feat: FastAPI server with WebSocket voice API and browser UI
644994e feat: core AVRS audio pipeline
```

Capabilities in the committed baseline:
- Three-tier render routing (corpus → cache → live TTS) at segment granularity.
- Kokoro ONNX (CPU, no GPU) TTS + mock TTS for dev.
- Deepgram nova-2 cloud STT with offline `faster-whisper` fallback.
- Claude-driven LLM agent with tool use, persona config in `agents.yaml`.
- FastAPI app with REST + WebSocket endpoints and a static browser demo at `/`.
- pytest unit tests for `parser`, `merger`, `router`, `metrics`.
- Docker / `docker-compose` distribution with `download-models` and `build-corpus` entrypoints.
- README, problem statement, research papers (MD/PDF) under `docs/`.

---

## What Is In Flight (Pickr — Uncommitted)

`git status` highlights:

| Path | State | Purpose |
|---|---|---|
| `avrs/voice_api.py` | modified (+693 / −153) | Massive expansion: OTP auth, user/admin endpoints, Plivo answer XML, `/ws/screen`, `/ws/exotel`, `/ws/plivo`. |
| `agents.yaml` | modified (+73) | New `screener` persona for AI call screening with INTENT/ACTION protocol. |
| `avrs/users.py` | untracked (555 lines) | Multi-tenant user store — OTP, pricing tiers (free/starter/pro/enterprise), virtual number pool, JSON persistence. |
| `avrs/exotel.py` | untracked (396 lines) | Exotel Voicebot WebSocket bridge (8 kHz PCM ↔ STT/LLM/TTS) with screen-event broadcasting. |
| `avrs/plivo.py` | untracked (322 lines) | Plivo AudioStream WebSocket bridge (μ-law / L16) — same pipeline. |
| `avrs/audio_utils.py` | untracked (187 lines) | Resample, energy VAD, PCM↔float32, μ-law codec helpers shared by Exotel/Plivo. |
| `android/` | untracked | Kotlin/Compose Android app `ai.phronetic.screener` — service, overlay, view-models, repositories, Room DB. |
| `corpus/screener/` | untracked | 12 prerecorded WAVs + `index.json` for the screener persona. |
| `brand/` | untracked | `icon.svg`, `logo.svg`. |
| `docs/END_TO_END_SETUP.md` | untracked | Pickr backend + Exotel + Android wiring guide. |
| `docs/PLIVO_SETUP.md` | untracked | Pickr + Plivo step-by-step setup. |

### Pickr Architecture (per `docs/END_TO_END_SETUP.md`)

```
Caller → Exotel/Plivo (PSTN/SIP)
        → /ws/exotel or /ws/plivo (FastAPI)
        → STT → Claude (screener persona) → TTS → back to caller
        → /ws/screen broadcasts live transcript / INTENT / ACTION
        → Android app (ai.phronetic.screener): tap Join / Block / Message
```

---

## API Surface (current `voice_api.py`)

**Auth (OTP flow):** `POST /v1/auth/otp/request`, `POST /v1/auth/otp/verify`, `GET/PATCH /v1/auth/me`.

**Speech primitives:** `POST /v1/speak`, `POST /v1/transcribe`.

**Agent personas + sessions:** `GET /v1/agents`, `GET /v1/voices`, `POST /v1/agent/sessions`, `POST /v1/agent/sessions/{id}/turn`, `DELETE /v1/agent/sessions/{id}`.

**Corpus management:** `POST /v1/corpus/{agent}/build`, `GET /v1/corpus/{agent}/status`, `GET /v1/corpus/{agent}/recommendations`, `POST /v1/corpus/{agent}/add_phrases`.

**Telephony bridges (WebSocket):** `/v1/stream`, `/ws/exotel`, `/ws/plivo`, `/ws/screen` (Android live monitor).

**Plivo XML callbacks:** `GET/POST /v1/plivo/answer`, `GET/POST /v1/plivo/status`.

**Admin (X-API-Key gated):** number pool CRUD, user tier/enable/disable/list/get/delete, usage analytics.

**System:** `GET /health`, `GET /v1/metrics`, OpenAPI at `/docs` and `/redoc`.

---

## Personas (`agents.yaml`)

| ID | Name | Domain | Corpus dir |
|---|---|---|---|
| `insurance` | Priya | Health and motor insurance | `corpus/insurance/` |
| `banking` | Arjun | Savings, loans, cards, UPI | `corpus/banking/` |
| `payments` | Maya | Digital payments, refunds | `corpus/payments/` |
| `screener` | Assistant | **Call screening (Pickr)** | `corpus/screener/` |

The screener persona emits `INTENT: <spam|delivery|work|personal|emergency|unknown>` and `ACTION: <continue|end_call|flag_urgent>` lines so the Android app can route the call.

---

## Android App (`android/app/src/main/java/ai/phronetic/screener/`)

Kotlin + Jetpack Compose. Key components:

- `ScreenerService.kt`, `ScreeningWebSocketService.kt` — background services that connect to backend `/ws/screen`.
- `ui/MainActivity.kt`, `ui/ScreeningOverlayActivity.kt`, `ui/Components.kt`.
- `ui/screens/`: Dashboard, History, Contacts, Onboarding, Profile.
- `viewmodel/`: ContactsViewModel, HistoryViewModel, DashboardViewModel.
- `engine/`: ScreeningEngine + LlmEngine + OfflineEngine.
- `data/db/`: Room (`AppDatabase`, `ContactRule`, `ScreenedCallDao`).
- `data/repository/`: ContactRuleRepository, CallHistoryRepository.

---

## Tests

pytest suite under `tests/`: `test_parser.py`, `test_merger.py`, `test_router.py`, `test_metrics.py`, plus `conftest.py`.

Coverage is limited to the AVRS core. **Nothing in the Pickr layer (`users.py`, `exotel.py`, `plivo.py`, `audio_utils.py`, voice_api auth/admin endpoints) has tests yet.**

---

## Risks / Open Items

1. **Large uncommitted surface.** `voice_api.py` has grown 693 lines beyond what is on `main`; `users.py`, `exotel.py`, `plivo.py`, `audio_utils.py` are wholly untracked. None of it has been reviewed via PR.
2. **No tests for the Pickr layer.** OTP, tier limits, number-pool assignment, Exotel/Plivo bridges, μ-law codec — all untested. Common rule says ≥80% coverage.
3. **JSON-file persistence.** `users.json`, `otp_cache.json`, `number_pool.json` are MVP-grade; production needs Postgres + Redis (called out in code comments).
4. **Secrets in `.env` only.** `ANTHROPIC_API_KEY`, `DEEPGRAM_API_KEY`, `PLIVO_AUTH_ID/TOKEN`, `AVRS_API_KEY` — need a secret-manager story before any deploy.
5. **`AVRS_API_KEY` defaults to empty.** When unset, admin endpoints are open. Should fail-closed in production builds.
6. **Two telephony providers wired in parallel.** Exotel and Plivo both bridge the same pipeline; no doc on which is canonical. `docs/PLIVO_SETUP.md` says "recommended for Indian numbers".
7. **README is still AVRS-branded.** No mention of Pickr, OTP, multi-tenant, or the Android app.

---

## Suggested Next Moves

- Carve the Pickr work into reviewable commits (auth/users → telephony bridges → screener persona → Android), each with tests.
- Add pytest coverage for `users.py` (OTP expiry, tier enforcement, pool assignment) and a fake-WS test for `exotel.py` / `plivo.py`.
- Decide Exotel vs Plivo as the primary path, keep the other behind a flag.
- Migrate persistence to Postgres + Redis before onboarding real users.
- Update top-level `README.md` (or add `README_PICKR.md`) so the Pickr direction is discoverable.
