"""
Rajesh's insurance agent demo — AVRS paper Figure 1.

Simulates a voice AI agent delivering personalised utterances
to policyholders. Demonstrates hybrid rendering with cost metrics.

Usage:
  python examples/insurance_agent.py
  python examples/insurance_agent.py --ref samples/voice_ref.wav --model chatterbox
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from rich.console import Console
from rich.table import Table

from avrs.config import RenderConfig
from avrs import metrics as metrics_mod
from avrs.router import RenderRouter
from avrs.utils import save_audio

console = Console()

UTTERANCES = [
    {
        "text": "Hello {name}, welcome to HealthFirst Insurance.",
        "slots": {"name": "Priya"},
    },
    {
        "text": "Your premium for {plan} is ₹{amount} per month.",
        "slots": {"plan": "HealthShield Gold", "amount": "5,432"},
    },
    {
        "text": "Oh great, you want to insure your {vehicle}. Excellent choice!",
        "slots": {"vehicle": "BMW"},
    },
    {
        "text": "Your policy number is {policy_id}.",
        "slots": {"policy_id": "HS-2024-88821"},
    },
]


def main() -> None:
    ap = argparse.ArgumentParser(description="Insurance agent AVRS demo")
    ap.add_argument("--ref-audio", default=None,
                    help="Path to 6-10s speaker reference WAV")
    ap.add_argument("--model", default="mock",
                    choices=["chatterbox", "kokoro", "mock"],
                    help="TTS model to use (default: mock)")
    ap.add_argument("--out-dir", default="output/insurance",
                    help="Output directory for rendered WAV files")
    args = ap.parse_args()

    if args.model != "mock" and not args.ref_audio:
        console.print("[yellow]No --ref-audio provided. Using MockEngine for demo.[/yellow]")
        args.model = "mock"

    if args.model == "mock":
        console.print("[dim]Running with MockEngine (440Hz sine wave placeholder audio)[/dim]")

    os.makedirs(args.out_dir, exist_ok=True)

    config = RenderConfig(
        tts_model=args.model,
        speaker_ref=args.ref_audio,
        corpus_dir="corpus/",
        cache_dir="cache/",
    )
    router = RenderRouter(config)
    all_metrics: list[metrics_mod.UtteranceMetrics] = []

    console.print("\n[bold cyan]HealthFirst Insurance — AVRS Demo[/bold cyan]")
    console.rule()

    for i, utt in enumerate(UTTERANCES):
        merged, rendered = router.render(utt["text"], utt["slots"])
        wav_path = os.path.join(args.out_dir, f"utterance_{i:02d}.wav")
        save_audio(merged.audio, merged.sr, wav_path)

        m = metrics_mod.compute_metrics(utt["text"], rendered, merged, config)
        all_metrics.append(m)
        metrics_mod.print_report(m)

    # Aggregate summary
    console.rule()
    total_chars = sum(m.total_chars for m in all_metrics)
    tts_chars = sum(m.tts_chars for m in all_metrics)
    cost_full = sum(m.cost_full_tts_usd for m in all_metrics)
    cost_hybrid = sum(m.cost_hybrid_usd for m in all_metrics)
    avg_reduction = sum(m.cost_reduction_pct for m in all_metrics) / len(all_metrics)

    table = Table(title="Aggregate — 4 Utterances", header_style="bold magenta")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Total chars", str(total_chars))
    table.add_row("TTS chars", str(tts_chars))
    table.add_row("Cost full TTS", f"${cost_full:.7f}")
    table.add_row("Cost hybrid", f"${cost_hybrid:.7f}")
    table.add_row("Avg cost reduction", f"[bold green]{avg_reduction:.2f}%[/bold green]")
    console.print(table)

    console.print(f"\n[green]WAV files saved to:[/green] {args.out_dir}/")


if __name__ == "__main__":
    main()
