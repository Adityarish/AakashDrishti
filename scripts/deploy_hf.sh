#!/usr/bin/env bash
# Deploy the backend to a free Hugging Face Docker Space.
# Usage: HF_USER=<username> HF_TOKEN=<write token> scripts/deploy_hf.sh [space-name]
set -euo pipefail
SPACE="${1:-aakashdrishti-backend}"
: "${HF_USER:?set HF_USER}" "${HF_TOKEN:?set HF_TOKEN}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"

git lfs install >/dev/null
git clone "https://${HF_USER}:${HF_TOKEN}@huggingface.co/spaces/${HF_USER}/${SPACE}" "$WORK/space"
cd "$WORK/space"
rm -rf backend model Dockerfile README.md
cp "$ROOT/deploy/huggingface/Dockerfile" "$ROOT/deploy/huggingface/README.md" .
rsync -a --exclude '.venv' --exclude '__pycache__' --exclude 'data' --exclude '.env' "$ROOT/backend/" backend/
rsync -a --exclude '__pycache__' --exclude '.git' --exclude 'training' --exclude 'depth_anything_v2_vitb_gamus_best/' --exclude 'ml-depth-pro-main/checkpoints' "$ROOT/model/" model/
git lfs track "*.pth" "*.pt" >/dev/null
git add -A && git commit -qm "Deploy backend" && git push
echo "Space: https://huggingface.co/spaces/${HF_USER}/${SPACE}"
