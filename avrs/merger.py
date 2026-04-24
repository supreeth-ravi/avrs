from __future__ import annotations

import math

import numpy as np

from avrs.config import MergedAudio, RenderedSegment, SeamMetric
from avrs import utils


def merge_segments(
    segments: list[RenderedSegment],
    target_sr: int = 22050,
) -> MergedAudio:
    if not segments:
        return MergedAudio(audio=np.zeros(0, dtype=np.float32),
                           sr=target_sr, seam_metrics=[])

    if len(segments) == 1:
        seg = segments[0]
        audio = utils.resample(seg.audio, seg.sr, target_sr)
        audio = utils.rms_normalise(audio)
        return MergedAudio(audio=audio, sr=target_sr, seam_metrics=[])

    # Resample and normalise all segments
    arrays: list[np.ndarray] = []
    for seg in segments:
        a = utils.resample(seg.audio, seg.sr, target_sr)
        a = utils.rms_normalise(a)
        arrays.append(a)

    seam_metrics: list[SeamMetric] = []
    fade_len = int(0.050 * target_sr)

    for i in range(len(arrays) - 1):
        left = arrays[i]
        right = arrays[i + 1]

        # Extract boundary windows (250ms)
        window_len = int(0.25 * target_sr)
        left_window = left[-window_len:] if len(left) >= window_len else left
        right_window = right[:window_len] if len(right) >= window_len else right

        f0_left = utils.get_f0(left_window, target_sr)
        f0_right = utils.get_f0(right_window, target_sr)

        # Pitch correction
        if f0_left > 0 and f0_right > 0:
            delta = 12 * math.log2(f0_left / f0_right)
        else:
            delta = 0.0

        if abs(delta) > 1.5:
            import librosa
            right = librosa.effects.pitch_shift(right, sr=target_sr,
                                                n_steps=-delta)
            arrays[i + 1] = right

        # RMS delta for metric
        rms_left = float(np.sqrt(np.mean(left_window ** 2)) + 1e-8)
        rms_right = float(np.sqrt(np.mean(right_window ** 2)) + 1e-8)
        rms_delta_db = 20 * math.log10(rms_left / rms_right)

        seam_metrics.append(SeamMetric(
            boundary_idx=i,
            pitch_delta_semitones=round(delta, 3),
            rms_delta_db=round(rms_delta_db, 3),
            crossfade_ms=50.0,
        ))

        # 50ms crossfade — consume tail of left and head of right
        actual_fade = min(fade_len, len(left), len(right))
        if actual_fade > 0:
            fade_out = np.linspace(1.0, 0.0, actual_fade)
            fade_in = np.linspace(0.0, 1.0, actual_fade)

            left_tail = left[-actual_fade:]
            right_head = right[:actual_fade]
            crossfaded = left_tail * fade_out + right_head * fade_in

            arrays[i] = np.concatenate([left[:-actual_fade], crossfaded])
            arrays[i + 1] = right[actual_fade:]

    audio = np.concatenate(arrays).astype(np.float32)
    audio = np.clip(audio, -1.0, 1.0)

    return MergedAudio(audio=audio, sr=target_sr, seam_metrics=seam_metrics)
