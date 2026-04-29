#!/usr/bin/env bash
# Run the insurance agent demo with mock engine.
# Usage: ./scripts/run_demo.sh [ref_audio.wav] [model]

set -euo pipefail

REF="${1:-}"
MODEL="${2:-mock}"

CMD="python examples/insurance_agent.py --model $MODEL"
if [ -n "$REF" ]; then
    CMD="$CMD --ref-audio $REF"
fi

echo "Running AVRS insurance agent demo..."
eval $CMD
