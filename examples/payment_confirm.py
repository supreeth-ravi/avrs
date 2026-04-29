"""
PayCentral payment confirmation demo.

Usage:
  python examples/payment_confirm.py
  python examples/payment_confirm.py --ref samples/voice_ref.wav --model chatterbox
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from rich.console import Console

from avrs.config import RenderConfig
from avrs import metrics as metrics_mod
from avrs.router import RenderRouter
from avrs.utils import save_audio

console = Console()

UTTERANCES = [
    {
        "text": "Your payment of ₹{amount} to {merchant} is confirmed.",
        "slots": {"amount": "5,432", "merchant": "Amazon India"},
    },
    {
        "text": "Transaction ID {txn_id}. Amount debited from {account}.",
        "slots": {"txn_id": "TXN20241201882", "account": "HDFC ****4521"},
    },
]


def main() -> None:
    ap = argparse.ArgumentParser(description="PayCentral payment confirmation demo")
    ap.add_argument("--ref-audio", default=None,
                    help="Path to speaker reference WAV")
    ap.add_argument("--model", default="mock",
                    choices=["chatterbox", "kokoro", "mock"])
    ap.add_argument("--out-dir", default="output/payment")
    args = ap.parse_args()

    if args.model != "mock" and not args.ref_audio:
        console.print("[yellow]No --ref-audio provided. Falling back to MockEngine.[/yellow]")
        args.model = "mock"

    os.makedirs(args.out_dir, exist_ok=True)

    config = RenderConfig(
        tts_model=args.model,
        speaker_ref=args.ref_audio,
        corpus_dir="corpus/",
        cache_dir="cache/",
    )
    router = RenderRouter(config)
    all_metrics: list[metrics_mod.UtteranceMetrics] = []

    console.print("\n[bold cyan]PayCentral — AVRS Demo[/bold cyan]")
    console.rule()

    for i, utt in enumerate(UTTERANCES):
        merged, rendered = router.render(utt["text"], utt["slots"])
        wav_path = os.path.join(args.out_dir, f"payment_{i:02d}.wav")
        save_audio(merged.audio, merged.sr, wav_path)

        m = metrics_mod.compute_metrics(utt["text"], rendered, merged, config)
        all_metrics.append(m)
        metrics_mod.print_report(m)

    avg_reduction = sum(m.cost_reduction_pct for m in all_metrics) / len(all_metrics)
    console.print(f"\n[bold]Average cost reduction: {avg_reduction:.2f}%[/bold]")
    console.print(f"[green]WAV files saved to:[/green] {args.out_dir}/")


if __name__ == "__main__":
    main()
