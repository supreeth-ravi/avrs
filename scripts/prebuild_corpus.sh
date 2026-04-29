#!/usr/bin/env bash
# Pre-build BFSI corpora for all agents using AVRS CLI.
# Run this once before starting the server to enable prerecorded mode.
#
# Usage:
#   ./scripts/prebuild_corpus.sh [ref_audio.wav] [model]
#
# Examples:
#   ./scripts/prebuild_corpus.sh                              # mock engine
#   ./scripts/prebuild_corpus.sh samples/voice_ref.wav       # chatterbox
#   ./scripts/prebuild_corpus.sh samples/ref.wav chatterbox  # explicit model

set -euo pipefail

REF="${1:-}"
MODEL="${2:-mock}"

echo "======================================="
echo " AVRS BFSI Corpus Pre-builder"
echo " Model: $MODEL"
[ -n "$REF" ] && echo " Reference: $REF"
echo "======================================="
echo ""

for AGENT in insurance banking payments; do
    PHRASES="corpus_data/${AGENT}_phrases.txt"
    OUT="corpus/${AGENT}/"

    if [ ! -f "$PHRASES" ]; then
        echo "[SKIP] $PHRASES not found"
        continue
    fi

    COUNT=$(grep -c -v '^#' "$PHRASES" | tr -d '[:space:]' || true)
    echo "[BUILD] $AGENT corpus — $COUNT phrases → $OUT"

    CMD="python -m avrs.cli corpus build --phrases $PHRASES --out $OUT --model $MODEL"
    [ -n "$REF" ] && CMD="$CMD --ref $REF"

    eval $CMD
    echo "[DONE]  $AGENT corpus built at $OUT"
    echo ""
done

echo "All corpora built. Start server:"
echo "  uvicorn avrs.voice_api:app --host 0.0.0.0 --port 8000"
