# Build from the repo root:  docker build -f backend/Dockerfile .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 DEVICE=cpu
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements.txt
# CPU wheels by default; swap the index URL for a CUDA build (e.g. cu121) to use a GPU.
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r backend/requirements.txt

# Vendored model source only (weights are excluded by .dockerignore and mounted at runtime).
COPY model model
RUN pip install --no-deps -e model/Depth-Anything-V2 -e model/ml-depth-pro-main

COPY backend backend
RUN useradd --create-home app && mkdir -p data && chown -R app /app/data
USER app

WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
