# Deployment

## Docker Compose (recommended)

1. Place model weights in `./model` (gitignored, too large for the repo):
   - `model/depth_anything_v2_vitb_gamus_best.pth` (or `depth_anything_v2_vitb.pth`)
   - `model/ml-depth-pro-main/checkpoints/depth_pro.pt` (optional; set `ENABLE_DEPTH_PRO=false` to skip)
2. Optionally copy `.env.example` to `.env` and adjust (compose reads it for `${VAR}` substitution).
3. `docker compose up --build -d` → UI on :3000, API on :8000 (`/health`, `/docs`).

Job data persists in `./data`. Weights are mounted, not baked into the image.

## Production notes

- `NEXT_PUBLIC_API_BASE_URL` is inlined at **build time**; set it to the public API URL and rebuild the frontend.
- Set `CORS_ORIGINS` to the public frontend origin, `AUTH_REQUIRED=true` and a strong `AUTH_SECRET`.
- Put both services behind a TLS-terminating reverse proxy (Caddy/nginx).
- GPU: use CUDA torch wheels in `backend/Dockerfile`, set `DEVICE=cuda`, and add a GPU reservation in compose.
- Without Docker: `make install`, then `make backend` and `make frontend`.
