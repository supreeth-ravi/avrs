#!/bin/bash
set -e

COMMAND=${1:-serve}

# ── download-models ────────────────────────────────────────────────────────
if [ "$COMMAND" = "download-models" ]; then
    BASE_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
    mkdir -p models/kokoro

    for file in "kokoro-v1.0.onnx" "voices-v1.0.bin"; do
        dest="models/kokoro/$file"
        if [ -f "$dest" ]; then
            echo "  $file already exists, skipping"
        else
            echo "  Downloading $file..."
            curl -L --progress-bar "$BASE_URL/$file" -o "$dest"
            echo "  Done"
        fi
    done
    echo ""
    echo "Models ready."
    exit 0
fi

# ── build-corpus ───────────────────────────────────────────────────────────
if [ "$COMMAND" = "build-corpus" ]; then
    echo "Building insurance corpus..."
    python scripts/build_insurance_corpus.py
    exit 0
fi

# ── serve (default) ────────────────────────────────────────────────────────
if [ "$COMMAND" = "serve" ]; then
    # Guard: models must exist when using kokoro
    if [ "${AVRS_TTS_MODEL:-kokoro}" = "kokoro" ]; then
        if [ ! -f "models/kokoro/kokoro-v1.0.onnx" ] || [ ! -f "models/kokoro/voices-v1.0.bin" ]; then
            echo ""
            echo "ERROR: Kokoro model files not found."
            echo "Run setup first:"
            echo "  docker compose run --rm avrs download-models"
            echo "  docker compose run --rm avrs build-corpus"
            echo ""
            echo "Or use mock TTS (no models needed):"
            echo "  AVRS_TTS_MODEL=mock docker compose up"
            echo ""
            exit 1
        fi
    fi

    echo "Starting AVRS server on port 8001..."
    exec uvicorn avrs.voice_api:app --host 0.0.0.0 --port 8001
fi

echo "Unknown command: $COMMAND"
echo "Usage: docker compose run --rm avrs [download-models|build-corpus|serve]"
exit 1
