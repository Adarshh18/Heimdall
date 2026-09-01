# HEIMDALL middleware — Docker SDK Space (port 7860)
FROM python:3.11-slim

# Match the UID Spaces uses internally — avoids permission issues on /home/user
RUN useradd -m -u 1000 user

WORKDIR /home/user/app

# ── Install CPU-only torch FIRST ────────────────────────────────────────────
# sentence-transformers pulls torch as a dependency. Left to its own devices,
# pip resolves the default (CUDA-enabled) torch wheel — ~6.5GB of unused GPU
# libraries on hardware that has no GPU. Installing the CPU wheel explicitly
# first means sentence-transformers later sees torch already satisfied and
# skips re-resolving it. This takes the image from ~8GB to ~1.8GB and cuts
# build time roughly in half.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# ── App dependencies (cached as its own layer) ──────────────────────────────
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ── App source ───────────────────────────────────────────────────────────────
# api/ (old Guardian v2 entry point, unused), tests/, and __pycache__ are
# excluded via .dockerignore — heimdall_app.py is the only entry point.
COPY --chown=user . .

USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

# HF caches downloaded model weights under $HOME/.cache/huggingface by default.
# Disk is ephemeral on free-tier Spaces, so this re-downloads after every
# sleep/restart — expected, takes ~60-90s on first request after a cold start.

EXPOSE 7860

CMD ["uvicorn", "heimdall_app:app", "--host", "0.0.0.0", "--port", "7860"]
