from __future__ import annotations

import json
import os
import sys

import click
from rich.console import Console

from avrs.config import RenderConfig
from avrs import metrics as metrics_mod
from avrs.router import RenderRouter
from avrs.utils import save_audio

console = Console()


@click.group()
def main() -> None:
    """AVRS — Adaptive Voice Rendering System."""


@main.command()
@click.argument("text")
@click.option("--slots", default=None, help="JSON string of slot values")
@click.option("--out", default="output.wav", show_default=True, help="Output WAV path")
@click.option("--report", is_flag=True, help="Print metrics table")
@click.option("--corpus", default="corpus/", show_default=True, help="Corpus directory")
@click.option("--ref", default=None, help="Speaker reference WAV path")
@click.option("--model", default="chatterbox", show_default=True,
              help="TTS model (chatterbox | kokoro | mock)")
def render(text: str, slots: str | None, out: str, report: bool,
           corpus: str, ref: str | None, model: str) -> None:
    """Render TEXT to speech and save WAV."""
    slot_dict: dict | None = None
    if slots:
        try:
            slot_dict = json.loads(slots)
        except json.JSONDecodeError as e:
            console.print(f"[red]Invalid --slots JSON: {e}[/red]")
            sys.exit(1)

    config = RenderConfig(
        corpus_dir=corpus,
        tts_model=model,
        speaker_ref=ref,
    )
    router = RenderRouter(config)
    merged, rendered = router.render(text, slot_dict)

    save_audio(merged.audio, merged.sr, out)
    console.print(f"[green]Saved:[/green] {out}")

    if report:
        m = metrics_mod.compute_metrics(text, rendered, merged, config)
        metrics_mod.print_report(m)


@main.group()
def corpus() -> None:
    """Corpus management commands."""


@corpus.command("build")
@click.option("--phrases", required=True, help="Text file with one phrase per line")
@click.option("--out", default="corpus/", show_default=True, help="Output corpus directory")
@click.option("--ref", default=None, help="Speaker reference WAV path")
@click.option("--model", default="chatterbox", show_default=True, help="TTS model")
def corpus_build(phrases: str, out: str, ref: str | None, model: str) -> None:
    """Build a corpus from a phrases file."""
    if not os.path.exists(phrases):
        console.print(f"[red]Phrases file not found: {phrases}[/red]")
        sys.exit(1)

    with open(phrases) as f:
        phrase_list = [line.strip() for line in f if line.strip()]

    config = RenderConfig(corpus_dir=out, tts_model=model, speaker_ref=ref)
    from avrs.tts import get_engine
    from avrs.corpus import Corpus
    import numpy as np

    engine = get_engine(model)
    ref_audio: np.ndarray | None = None
    if ref:
        from avrs.utils import load_audio
        ref_audio, _ = load_audio(ref, config.sr)

    corp = Corpus(out, engine)
    console.print(f"Building corpus with {len(phrase_list)} phrases...")
    corp.build_from_phrases(phrase_list, ref_audio=ref_audio, sr=config.sr)
    console.print(f"[green]Corpus built:[/green] {out} ({len(phrase_list)} phrases)")


@main.command()
@click.option("--input", "input_path", required=True,
              help="JSON file: list of {text, slots} objects")
@click.option("--corpus", default="corpus/", show_default=True, help="Corpus directory")
@click.option("--ref", default=None, help="Speaker reference WAV")
@click.option("--out", default="benchmark_output/", show_default=True,
              help="Output directory for WAV files")
@click.option("--report", "report_path", default=None,
              help="Output JSON metrics path")
@click.option("--model", default="chatterbox", show_default=True, help="TTS model")
def benchmark(input_path: str, corpus: str, ref: str | None, out: str,
              report_path: str | None, model: str) -> None:
    """Run a batch benchmark from a JSON input file."""
    if not os.path.exists(input_path):
        console.print(f"[red]Input file not found: {input_path}[/red]")
        sys.exit(1)

    with open(input_path) as f:
        items = json.load(f)

    os.makedirs(out, exist_ok=True)
    config = RenderConfig(corpus_dir=corpus, tts_model=model, speaker_ref=ref)
    router = RenderRouter(config)
    all_metrics: list[metrics_mod.UtteranceMetrics] = []

    for i, item in enumerate(items):
        text = item["text"]
        slots = item.get("slots")
        merged, rendered = router.render(text, slots)
        wav_path = os.path.join(out, f"utterance_{i:04d}.wav")
        save_audio(merged.audio, merged.sr, wav_path)
        m = metrics_mod.compute_metrics(text, rendered, merged, config)
        all_metrics.append(m)
        metrics_mod.print_report(m)

    if report_path:
        metrics_mod.export_json(all_metrics, report_path)
        console.print(f"[green]Metrics saved:[/green] {report_path}")

    total_reduction = sum(m.cost_reduction_pct for m in all_metrics) / len(all_metrics) if all_metrics else 0
    console.print(f"\n[bold]Average cost reduction: {total_reduction:.2f}%[/bold]")
