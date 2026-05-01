FROM python:3.11-slim

# System dependencies needed by librosa / soundfile / scipy
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer cache)
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -e ".[kokoro]"

# Download spaCy NER model
RUN python -m spacy download en_core_web_sm

# Copy application code
COPY avrs/ ./avrs/
COPY agents.yaml ./
COPY static/ ./static/
COPY scripts/ ./scripts/
COPY corpus_data/ ./corpus_data/

# Directories that are expected as volume mounts at runtime
# Creating them here so the container starts cleanly even without mounts
RUN mkdir -p models/kokoro corpus/insurance corpus/banking corpus/payments \
             cache/insurance cache/banking cache/payments

EXPOSE 8001

COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

ENTRYPOINT ["./docker-entrypoint.sh"]
