# Voice Reference Samples

Drop a 6–10 second reference WAV file here as `voice_ref.wav`.

Requirements:
- Format: 16-bit PCM WAV, mono or stereo
- Duration: 6–10 seconds of clear speech
- Content: The target speaker reading any natural sentence(s)
- Quality: No background music, minimal noise

This file is used for zero-shot voice cloning with ChatterboxTTS.

Example: `samples/voice_ref.wav`

Pass it to commands via `--ref samples/voice_ref.wav`.
