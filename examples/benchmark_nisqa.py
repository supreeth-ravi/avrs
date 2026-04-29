"""
NISQA corpus benchmark.

Loads a subset of the NISQA speech quality corpus, attempts to render
each file through AVRS auto-NER slot detection, and exports metrics.

Usage:
  python examples/benchmark_nisqa.py --nisqa-dir /path/to/nisqa_corpus
  python examples/benchmark_nisqa.py --nisqa-dir /path/to/nisqa_corpus --model mock --limit 20
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from rich.console import Console
from rich.table import Table

from avrs.config import RenderConfig
from avrs import metrics as metrics_mod
from avrs.router import RenderRouter

console = Console()


def load_nisqa_transcripts(nisqa_dir: str, limit: int) -> list[dict]:
    """
    Expects NISQA CSV with columns: filename, transcript (or deg).
    Falls back to scanning for .txt sidecar files.
    """
    entries: list[dict] = []

    csv_candidates = [
        os.path.join(nisqa_dir, "NISQA_corpus_file.csv"),
        os.path.join(nisqa_dir, "files.csv"),
    ]
    for csv_path in csv_candidates:
        if os.path.exists(csv_path):
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    fname = row.get("filepath_deg") or row.get("filename", "")
                    text = row.get("transcript") or row.get("condition", "")
                    if fname and text:
                        entries.append({"file": os.path.join(nisqa_dir, fname),
                                        "text": text})
                    if len(entries) >= limit:
                        break
            if entries:
                return entries

    # Fallback: scan for .wav + matching .txt
    for root, _, files in os.walk(nisqa_dir):
        for fname in sorted(files):
            if not fname.endswith(".wav"):
                continue
            txt_path = os.path.join(root, fname.replace(".wav", ".txt"))
            if os.path.exists(txt_path):
                with open(txt_path) as f:
                    text = f.read().strip()
                if text:
                    entries.append({"file": os.path.join(root, fname),
                                    "text": text})
            if len(entries) >= limit:
                break
        if len(entries) >= limit:
            break

    return entries


def main() -> None:
    ap = argparse.ArgumentParser(description="NISQA corpus AVRS benchmark")
    ap.add_argument("--nisqa-dir", required=True,
                    help="Path to NISQA corpus directory")
    ap.add_argument("--model", default="mock",
                    choices=["chatterbox", "kokoro", "mock"])
    ap.add_argument("--limit", type=int, default=50,
                    help="Max utterances to benchmark (default: 50)")
    ap.add_argument("--out-csv", default="benchmark_nisqa_metrics.csv",
                    help="Output CSV path")
    ap.add_argument("--corpus", default="corpus/")
    args = ap.parse_args()

    if not os.path.isdir(args.nisqa_dir):
        console.print(f"[red]NISQA directory not found: {args.nisqa_dir}[/red]")
        sys.exit(1)

    console.print(f"[cyan]Loading NISQA entries from:[/cyan] {args.nisqa_dir}")
    entries = load_nisqa_transcripts(args.nisqa_dir, args.limit)

    if not entries:
        console.print("[red]No transcripts found. Check NISQA directory structure.[/red]")
        sys.exit(1)

    console.print(f"[green]{len(entries)} utterances loaded[/green]")

    config = RenderConfig(tts_model=args.model, corpus_dir=args.corpus,
                          cache_dir="cache/")
    router = RenderRouter(config)
    all_metrics: list[metrics_mod.UtteranceMetrics] = []

    for i, entry in enumerate(entries):
        text = entry["text"]
        try:
            merged, rendered = router.render(text)
            m = metrics_mod.compute_metrics(text, rendered, merged, config)
            all_metrics.append(m)
            if (i + 1) % 10 == 0:
                console.print(f"  [{i+1}/{len(entries)}] avg reduction so far: "
                              f"{sum(x.cost_reduction_pct for x in all_metrics)/len(all_metrics):.1f}%")
        except Exception as e:
            console.print(f"[yellow]Skipped utterance {i}: {e}[/yellow]")

    metrics_mod.export_csv(all_metrics, args.out_csv)
    console.print(f"\n[green]Metrics saved:[/green] {args.out_csv}")

    if all_metrics:
        avg_reduction = sum(m.cost_reduction_pct for m in all_metrics) / len(all_metrics)
        avg_tts_pct = sum(m.tts_chars_pct for m in all_metrics) / len(all_metrics)

        table = Table(title="NISQA Benchmark Summary", header_style="bold magenta")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_row("Utterances processed", str(len(all_metrics)))
        table.add_row("Avg TTS chars %", f"{avg_tts_pct:.1f}%")
        table.add_row("Avg cost reduction", f"{avg_reduction:.2f}%")
        console.print(table)


if __name__ == "__main__":
    main()
