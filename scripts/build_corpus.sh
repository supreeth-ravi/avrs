#!/usr/bin/env bash
# Build a static phrase corpus from a phrases file.
# Usage: ./scripts/build_corpus.sh phrases.txt [ref_audio.wav] [model]

set -euo pipefail

PHRASES="${1:-phrases.txt}"
REF="${2:-}"
MODEL="${3:-mock}"
CORPUS_DIR="corpus/"

if [ ! -f "$PHRASES" ]; then
    echo "Error: phrases file not found: $PHRASES"
    exit 1
fi

CMD="avrs corpus build --phrases $PHRASES --out $CORPUS_DIR --model $MODEL"
if [ -n "$REF" ]; then
    CMD="$CMD --ref $REF"
fi

echo "Building corpus..."
echo "  Phrases: $PHRASES"
echo "  Output:  $CORPUS_DIR"
echo "  Model:   $MODEL"
[ -n "$REF" ] && echo "  Ref:     $REF"
echo ""

eval $CMD
echo "Done."
