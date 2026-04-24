from __future__ import annotations

import csv
import io
import json
import os
from dataclasses import asdict, dataclass

from rich.console import Console
from rich.table import Table

from avrs.config import MergedAudio, RenderConfig, RenderedSegment, SeamMetric


@dataclass
class UtteranceMetrics:
    utterance: str
    segments: int
    static_segments: int
    slot_segments: int
    prerecorded_pct: float
    cached_pct: float
    tts_pct: float
    total_chars: int
    tts_chars: int
    tts_chars_pct: float
    latency_total_ms: float
    cost_full_tts_usd: float
    cost_hybrid_usd: float
    cost_reduction_pct: float
    seam_metrics: list[SeamMetric]


def compute_metrics(
    utterance: str,
    rendered: list[RenderedSegment],
    merged: MergedAudio,
    config: RenderConfig,
) -> UtteranceMetrics:
    n = len(rendered)
    static_segs = sum(1 for r in rendered if r.mode in ("prerecorded", "cached"))
    slot_segs = n - static_segs

    mode_counts = {"prerecorded": 0, "cached": 0, "tts": 0}
    for r in rendered:
        mode_counts[r.mode] = mode_counts.get(r.mode, 0) + 1

    prerecorded_pct = 100.0 * mode_counts["prerecorded"] / n if n else 0.0
    cached_pct = 100.0 * mode_counts["cached"] / n if n else 0.0
    tts_pct = 100.0 * mode_counts["tts"] / n if n else 0.0

    total_chars = sum(r.char_count for r in rendered)
    tts_chars = sum(r.char_count for r in rendered if r.mode == "tts")
    tts_chars_pct = 100.0 * tts_chars / total_chars if total_chars else 0.0

    latency_total_ms = sum(r.latency_ms for r in rendered)

    cost_full = total_chars * config.tts_cost_per_char_usd
    cost_hybrid = tts_chars * config.tts_cost_per_char_usd
    reduction = (cost_full - cost_hybrid) / cost_full * 100 if cost_full > 0 else 0.0

    return UtteranceMetrics(
        utterance=utterance,
        segments=n,
        static_segments=static_segs,
        slot_segments=slot_segs,
        prerecorded_pct=round(prerecorded_pct, 1),
        cached_pct=round(cached_pct, 1),
        tts_pct=round(tts_pct, 1),
        total_chars=total_chars,
        tts_chars=tts_chars,
        tts_chars_pct=round(tts_chars_pct, 1),
        latency_total_ms=round(latency_total_ms, 2),
        cost_full_tts_usd=cost_full,
        cost_hybrid_usd=cost_hybrid,
        cost_reduction_pct=round(reduction, 2),
        seam_metrics=merged.seam_metrics,
    )


def print_report(m: UtteranceMetrics) -> None:
    console = Console()

    table = Table(title="AVRS Utterance Metrics", show_header=True,
                  header_style="bold cyan")
    table.add_column("Metric", style="dim", min_width=28)
    table.add_column("Value", justify="right")

    table.add_row("Utterance", f'"{m.utterance[:60]}"')
    table.add_row("Segments", str(m.segments))
    table.add_row("  Pre-recorded", f"{m.prerecorded_pct:.1f}%")
    table.add_row("  Cached", f"{m.cached_pct:.1f}%")
    table.add_row("  Live TTS", f"{m.tts_pct:.1f}%")
    table.add_row("Total chars", str(m.total_chars))
    table.add_row("TTS chars", f"{m.tts_chars} ({m.tts_chars_pct:.1f}%)")
    table.add_row("Latency (sum)", f"{m.latency_total_ms:.1f} ms")
    table.add_row("Cost (full TTS)",
                  f"${m.cost_full_tts_usd:.7f}")
    table.add_row("Cost (hybrid)",
                  f"${m.cost_hybrid_usd:.7f}")
    table.add_row("Cost reduction", f"[bold green]{m.cost_reduction_pct:.2f}%[/bold green]")

    if m.seam_metrics:
        for sm in m.seam_metrics:
            table.add_row(
                f"Seam {sm.boundary_idx}",
                f"Δpitch={sm.pitch_delta_semitones:+.2f}st  "
                f"ΔRMS={sm.rms_delta_db:+.1f}dB  "
                f"xfade={sm.crossfade_ms}ms",
            )

    console.print(table)


def export_json(metrics_list: list[UtteranceMetrics], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    data = []
    for m in metrics_list:
        d = asdict(m)
        data.append(d)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def export_csv(metrics_list: list[UtteranceMetrics], path: str) -> None:
    if not metrics_list:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    scalar_fields = [
        f for f in UtteranceMetrics.__dataclass_fields__
        if f != "seam_metrics"
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=scalar_fields)
        writer.writeheader()
        for m in metrics_list:
            row = {k: getattr(m, k) for k in scalar_fields}
            writer.writerow(row)
