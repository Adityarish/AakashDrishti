# Hugging Face Space (free CPU: 2 vCPU / 16 GB RAM). Staged by scripts/deploy_hf.sh.
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 DEVICE=cpu \
    ENABLE_DEPTH_PRO=false PORT=7860 BACKEND_PORT=7860
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt backend/requirements.txt
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r backend/requirements.txt
COPY model model
RUN pip install --no-deps -e model/Depth-Anything-V2 -e model/ml-depth-pro-main
COPY backend backend
RUN useradd -m -u 1000 app && mkdir -p data && chown -R app /app
USER app
WORKDIR /app/backend
EXPOSE 7860
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
