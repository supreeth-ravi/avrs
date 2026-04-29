#!/bin/bash
# Download Kokoro ONNX model files
# Run this once before starting the server or Docker container

set -e

MODELS_DIR="$(dirname "$0")/../models/kokoro"
mkdir -p "$MODELS_DIR"

BASE_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"

download() {
    local file=$1
    local dest="$MODELS_DIR/$file"
    if [ -f "$dest" ]; then
        echo "  $file already exists, skipping"
    else
        echo "  Downloading $file..."
        curl -L --progress-bar "$BASE_URL/$file" -o "$dest"
        echo "  Done: $dest"
    fi
}

echo "Downloading Kokoro model files to $MODELS_DIR"
echo ""
download "kokoro-v1.0.onnx"
download "voices-v1.0.bin"
echo ""
echo "Models ready. You can now start the server:"
echo "  docker compose up"
echo "  # or: uvicorn avrs.server:app --port 8001"
