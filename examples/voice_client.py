"""
AVRS Interactive Voice Client

Talk to the BFSI agent in real-time. Captures mic, sends to AVRS Voice API,
plays back the synthesised response.

Usage:
  python examples/voice_client.py                        # insurance agent (default)
  python examples/voice_client.py --agent banking        # banking agent
  python examples/voice_client.py --text                 # text input mode (no mic)
  python examples/voice_client.py --url ws://host:8000   # remote server

Requirements:
  pip install sounddevice websockets rich

Controls:
  SPACE or ENTER — hold to speak (push-to-talk)
  Ctrl+C         — quit
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

SR_MIC = 16000
SR_PLAYBACK = 22050
CHUNK_DURATION_S = 0.1  # 100ms chunks


def _check_deps() -> bool:
    missing = []
    try:
        import sounddevice
    except ImportError:
        missing.append("sounddevice")
    try:
        import websockets
    except ImportError:
        missing.append("websockets")
    if missing:
        console.print(f"[red]Missing: {', '.join(missing)}[/red]")
        console.print(f"Run: pip install {' '.join(missing)}")
        return False
    return True


def _record_until_silence(duration_s: float = 3.0) -> bytes:
    """Record mic audio for duration_s seconds, return raw PCM int16 bytes."""
    import sounddevice as sd
    import numpy as np

    console.print("[yellow]Recording...[/yellow] (speak now)")
    samples = sd.rec(int(duration_s * SR_MIC), samplerate=SR_MIC,
                     channels=1, dtype="int16")
    sd.wait()
    console.print("[dim]Done recording[/dim]")
    return samples.tobytes()


def _record_push_to_talk() -> bytes:
    """Record while Enter is held, stop on release. Returns PCM bytes."""
    import sounddevice as sd
    import numpy as np

    chunks: list[np.ndarray] = []
    recording = True

    def _callback(indata, frames, time_info, status):
        if recording:
            chunks.append(indata.copy())

    console.print("[bold yellow]→ Press ENTER to start speaking, ENTER again to stop[/bold yellow]")
    input()
    console.print("[green]● Recording...[/green]")

    stream = sd.InputStream(samplerate=SR_MIC, channels=1, dtype="int16",
                            callback=_callback, blocksize=int(SR_MIC * CHUNK_DURATION_S))
    with stream:
        input()

    console.print("[dim]Stopped.[/dim]")
    if not chunks:
        return b""
    audio = np.concatenate(chunks, axis=0)
    return audio.tobytes()


def _play_wav_bytes(wav_bytes: bytes) -> None:
    """Play WAV bytes through default output device."""
    try:
        import sounddevice as sd
        import soundfile as sf
        buf = io.BytesIO(wav_bytes)
        audio, sr = sf.read(buf, dtype="float32")
        sd.play(audio, samplerate=sr, blocking=True)
    except Exception as e:
        console.print(f"[dim]Audio playback: {e}[/dim]")


# ---------------------------------------------------------------------------
# WebSocket client
# ---------------------------------------------------------------------------

async def _ws_session(
    server_url: str,
    agent: str,
    model: str,
    api_key: str | None,
    text_mode: bool,
) -> None:
    import websockets

    params = f"?agent={agent}&model={model}"
    if api_key:
        params += f"&api_key={api_key}"
    url = server_url.rstrip("/") + "/v1/stream" + params

    console.print(Panel(
        f"[bold cyan]AVRS Voice Agent[/bold cyan]\n"
        f"Agent: [green]{agent}[/green]   Model: [yellow]{model}[/yellow]\n"
        f"Mode: {'text' if text_mode else 'voice'}\n"
        f"Server: {server_url}",
        title="Connecting",
    ))

    async with websockets.connect(url) as ws:
        # Receive session.created
        raw = await ws.recv()
        info = json.loads(raw)
        if info.get("type") == "session.created":
            console.print(Panel(
                f"[bold]{info['persona']}[/bold] from [italic]{info['company']}[/italic]\n"
                f"Session: [dim]{info['session_id']}[/dim]",
                title="Connected",
                border_style="green",
            ))
        else:
            console.print(f"[red]Unexpected: {info}[/red]")
            return

        console.print("\n[dim]Ctrl+C to quit[/dim]\n")

        while True:
            console.rule()

            if text_mode:
                try:
                    user_text = console.input("[bold]You:[/bold] ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not user_text:
                    continue
                await ws.send(json.dumps({"type": "input_text", "text": user_text}))
            else:
                pcm = _record_push_to_talk()
                if not pcm:
                    continue
                audio_b64 = base64.b64encode(pcm).decode()
                await ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": audio_b64,
                }))
                await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

            # Collect server events
            audio_segments: list[bytes] = []
            agent_text_parts: list[str] = []

            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
                except asyncio.TimeoutError:
                    console.print("[red]Timeout waiting for agent response[/red]")
                    break

                event = json.loads(raw)
                etype = event.get("type", "")

                if etype == "conversation.item.input_audio_transcription.completed":
                    console.print(f"[bold]You:[/bold] {event['transcript']}")

                elif etype == "response.text.delta":
                    agent_text_parts.append(event.get("text", ""))

                elif etype == "response.audio.delta":
                    wav_b64 = event.get("data", "")
                    mode = event.get("mode", "?")
                    text = event.get("text", "")
                    idx = event.get("segment_idx", 0)
                    mode_color = {"prerecorded": "green", "cached": "cyan", "tts": "yellow"}.get(mode, "white")
                    console.print(
                        f"  [{idx}] [{mode_color}]{mode}[/{mode_color}] "
                        f"[dim]\"{text[:50]}\"[/dim]"
                    )
                    audio_segments.append(base64.b64decode(wav_b64))

                elif etype == "response.done":
                    full_text = " ".join(agent_text_parts)
                    console.print(f"\n[bold green]{info['persona']}:[/bold green] {full_text}")

                    m = event.get("metrics", {})
                    console.print(
                        f"[dim]Cost reduction: [bold]{m.get('cost_reduction_pct', 0):.1f}%[/bold]  "
                        f"Latency: {m.get('latency_total_ms', 0):.0f}ms  "
                        f"TTS: {m.get('tts_chars_pct', 0):.0f}% chars[/dim]"
                    )

                    # Play all segments sequentially
                    for wav_bytes in audio_segments:
                        _play_wav_bytes(wav_bytes)
                    break

                elif etype == "error":
                    console.print(f"[red]Error {event.get('code')}: {event.get('message')}[/red]")
                    break

                elif etype in ("input_audio_buffer.speech_started",
                               "input_audio_buffer.speech_stopped",
                               "response.creating"):
                    pass  # status events, skip display


def main() -> None:
    ap = argparse.ArgumentParser(description="AVRS interactive voice client")
    ap.add_argument("--url", default="ws://localhost:8000",
                    help="AVRS server WebSocket base URL")
    ap.add_argument("--agent", default="insurance",
                    choices=["insurance", "banking", "payments"])
    ap.add_argument("--model", default="mock",
                    choices=["mock", "chatterbox", "kokoro"])
    ap.add_argument("--api-key", default=os.getenv("AVRS_API_KEY"),
                    help="API key (or set AVRS_API_KEY env var)")
    ap.add_argument("--text", action="store_true",
                    help="Use text input instead of microphone")
    args = ap.parse_args()

    if not args.text and not _check_deps():
        sys.exit(1)

    # Make URL ws:// compatible
    url = args.url.replace("http://", "ws://").replace("https://", "wss://")

    try:
        asyncio.run(_ws_session(url, args.agent, args.model,
                                args.api_key, args.text))
    except KeyboardInterrupt:
        console.print("\n[dim]Goodbye.[/dim]")


if __name__ == "__main__":
    main()
