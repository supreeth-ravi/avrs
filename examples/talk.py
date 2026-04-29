"""
AVRS Talk — real voice demo through the production API.

Flow:
  Your mic → WAV → POST /v1/agent/sessions/{id}/turn (audio=) → Whisper STT
           → Claude Agent → AVRS Router (corpus/cache/TTS) → WAV → speaker

Usage:
  python examples/talk.py
  python examples/talk.py --agent banking
  python examples/talk.py --port 8001

Controls:  ENTER = start/stop recording   Ctrl+C = quit
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import threading
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.console import Console
from rich.panel import Panel

console = Console()

try:
    import sounddevice as sd
    import soundfile as sf
    import requests
except ImportError as e:
    console.print(f"[red]Missing dependency: {e}[/red]")
    console.print("Run: pip install sounddevice soundfile requests")
    sys.exit(1)

SR_MIC = 16000


# ── recording ─────────────────────────────────────────────────────────────────

def record_until_enter() -> bytes:
    """Record mic until ENTER pressed. Returns WAV bytes."""
    chunks: list[np.ndarray] = []
    stop_event = threading.Event()

    def _cb(indata, frames, time_info, status):
        chunks.append(indata.copy())

    stream = sd.InputStream(
        samplerate=SR_MIC, channels=1, dtype="int16",
        callback=_cb, blocksize=int(SR_MIC * 0.1),
    )
    console.print("\n[bold yellow]● Recording[/bold yellow] — press [bold]ENTER[/bold] to stop")
    with stream:
        input()

    if not chunks:
        return b""
    pcm = np.concatenate(chunks, axis=0).flatten()
    buf = io.BytesIO()
    sf.write(buf, pcm, SR_MIC, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def play_wav_bytes(wav_bytes: bytes) -> None:
    audio, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    sd.play(audio, samplerate=sr, blocking=True)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="AVRS real-voice demo (API mode)")
    ap.add_argument("--agent", default="insurance",
                    choices=["insurance", "banking", "payments"])
    ap.add_argument("--model", default="kokoro",
                    choices=["kokoro", "chatterbox", "mock"])
    ap.add_argument("--port", default=8001, type=int)
    ap.add_argument("--host", default="localhost")
    args = ap.parse_args()

    base = f"http://{args.host}:{args.port}"

    # Health check
    try:
        h = requests.get(f"{base}/health", timeout=3).json()
    except Exception:
        console.print(f"[red]Cannot reach API at {base} — is the server running?[/red]")
        console.print(f"  Start with: AVRS_TTS_MODEL=kokoro uvicorn avrs.voice_api:app --port {args.port}")
        sys.exit(1)

    if not h.get("stt_available"):
        console.print("[red]STT unavailable on server — run: pip install faster-whisper[/red]")
        sys.exit(1)

    # Start session
    sess = requests.post(f"{base}/v1/agent/sessions",
                         json={"agent": args.agent, "model": args.model}).json()
    SID  = sess["session_id"]

    console.print(Panel(
        f"[bold cyan]AVRS Voice Demo[/bold cyan]  (API mode)\n"
        f"Agent : [bold]{sess['persona_name']}[/bold] — {sess['company']}\n"
        f"TTS   : [yellow]{args.model}[/yellow]   STT: Whisper base\n"
        f"Server: {base}   Session: [dim]{SID}[/dim]",
        border_style="cyan",
    ))
    console.print("[dim]Press ENTER to start talking. Ctrl+C to quit.[/dim]\n")

    while True:
        console.rule()
        try:
            console.print("Press [bold]ENTER[/bold] to speak...")
            input()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        # Record real voice
        wav_bytes = record_until_enter()
        if len(wav_bytes) < SR_MIC * 0.3 * 2:   # ~0.3s minimum
            console.print("[dim]Too short, try again.[/dim]")
            continue

        # Send to API: audio → STT → Agent → AVRS → WAV
        console.print("[dim]Processing...[/dim]")
        t0 = time.perf_counter()
        try:
            r = requests.post(
                f"{base}/v1/agent/sessions/{SID}/turn",
                params={"model": args.model},
                files={"audio": ("mic.wav", io.BytesIO(wav_bytes), "audio/wav")},
                timeout=60,
            )
        except requests.exceptions.RequestException as e:
            console.print(f"[red]Request failed: {e}[/red]")
            continue
        rtt = (time.perf_counter() - t0) * 1000

        if r.status_code != 200:
            console.print(f"[red]API error {r.status_code}: {r.text[:200]}[/red]")
            continue

        h = r.headers
        transcript = h.get("x-transcript", "")
        agent_resp = h.get("x-agent-response", "")
        cost       = h.get("x-avrs-cost-reduction-pct", "?")
        latency    = h.get("x-avrs-latency-ms", "?")
        try:
            m = json.loads(h.get("x-avrs-metrics", "{}"))
        except Exception:
            m = {}

        pre   = float(m.get("prerecorded_pct", 0))
        cache = float(m.get("cached_pct", 0))
        tts_p = float(m.get("tts_chars_pct", 0))
        segs  = m.get("segments", "?")

        console.print(f"\n[bold]You:[/bold] {transcript}")
        console.print(f"\n[bold green]{sess['persona_name']}:[/bold green] {agent_resp}")
        console.print(
            f"\n  [dim]cost↓{cost}%  "
            f"📼{pre:.0f}% 💾{cache:.0f}% 🎤{tts_p:.0f}%  "
            f"{segs} segs  render={float(latency):.0f}ms  RTT={rtt:.0f}ms[/dim]"
        )

        # Play agent response
        if len(r.content) > 44:
            play_wav_bytes(r.content)

    requests.delete(f"{base}/v1/agent/sessions/{SID}", timeout=3)


if __name__ == "__main__":
    main()
