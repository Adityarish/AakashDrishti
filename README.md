# AakashDrishti — DepthWizard

> **Single-View Height Estimation & 3D Flythrough**  
> Smart India Hackathon 2026 · Problem Statement 26175 · ISRO / Department of Space · Theme: Disaster Management

AakashDrishti transforms a single RGB aerial/satellite image into a calibrated elevation map, 3D terrain mesh, and interactive flythrough — supporting disaster-response planning, building-height extraction, slope analysis, and more.

---

## Pipeline Overview

```
Single RGB / GeoTIFF Image
        ↓
Input Detection (PNG · JPG · TIFF · GeoTIFF)
        ↓
Depth Anything V2  +  Depth Pro  (sequential, GPU-memory safe)
        ↓
Edge-Aware Depth Fusion  +  Confidence Map
        ↓
SRTM / DEM / GCP Calibration  (georeferenced input)
        ↓
DSM / rDSM Export  (GeoTIFF)
        ↓
Terrain Mesh  +  RGB Texture
        ↓
Three.js 3D Flythrough  (first-person navigation)
        ↓
Height · Slope · Disaster-Zone Overlays · RMSE/MAE Validation
```

---

## Repository Layout

```
backend/    FastAPI service (app/), CLI scripts (scripts/), tests/, demo/ featured scene, Dockerfile
frontend/   Next.js app (src/), static assets (public/, incl. built Unity WebGL viewer), Dockerfile
unity/      Unity project source for the WebGL viewer
model/      Vendored Depth Anything V2 / Depth Pro source + training code (weights are gitignored)
docs/       Deployment and project docs
data/       Runtime uploads/outputs (gitignored)
```

Deploy with `docker compose up --build` — see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 16 · React 19 · TypeScript · Three.js |
| Backend | Python · FastAPI · Uvicorn |
| ML Models | Depth Anything V2 · Apple Depth Pro |
| Geospatial | rasterio · GDAL · SRTM 30m DEM |
| Image Processing | OpenCV · NumPy · Pillow |
| 3D Mesh Export | trimesh (GLB) |

---

## Prerequisites

| Tool | Minimum Version |
|------|----------------|
| Python | 3.11+ |
| Node.js | 18+ |
| npm | 9+ |
| CUDA (recommended) | 12.x (CPU fallback available) |
| VRAM | 8 GB (RTX 5060-class) |

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/Blrm123/AakashDrishti.git
cd AakashDrishti
```

### 2. Set up environment variables

```bash
copy .env.example .env
```

Edit `.env` and verify the paths (defaults work out-of-the-box after weight download):

```env
DEPTH_ANYTHING_V2_ENCODER=vitb
DEPTH_ANYTHING_V2_CHECKPOINT=./model/depth_anything_v2_vitb.pth
DEPTH_PRO_CHECKPOINT=./model/ml-depth-pro-main/checkpoints/depth_pro.pt
DEVICE=cuda          # or cpu
CORS_ORIGINS=http://localhost:3000
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

---

### 3. Download model weights

> Model weights are **not** included in the repository (~2.3 GB total).

**Depth Anything V2 — ViT-B checkpoint (~390 MB)**

```bash
# Windows PowerShell
Invoke-WebRequest `
  -Uri "https://huggingface.co/depth-anything/Depth-Anything-V2-Base/resolve/main/depth_anything_v2_vitb.pth" `
  -OutFile "model\depth_anything_v2_vitb.pth"

# or using Python
python -c "
import urllib.request
urllib.request.urlretrieve(
    'https://huggingface.co/depth-anything/Depth-Anything-V2-Base/resolve/main/depth_anything_v2_vitb.pth',
    'model/depth_anything_v2_vitb.pth'
)"
```

**Apple Depth Pro (~1.9 GB)**

```bash
mkdir model\ml-depth-pro-main\checkpoints

# Python download
python -c "
import urllib.request, os
os.makedirs('model/ml-depth-pro-main/checkpoints', exist_ok=True)
urllib.request.urlretrieve(
    'https://ml-site.cdn-apple.com/models/depth-pro/depth_pro.pt',
    'model/ml-depth-pro-main/checkpoints/depth_pro.pt'
)"
```

**Aerial object detector — YOLOv8s-OBB, DOTA (~23 MB)**

```bash
# ultralytics fetches it on first use; move it into model/yolo/
python -c "from ultralytics import YOLO; YOLO('yolov8s-obb.pt')"
mkdir model\yolo
move yolov8s-obb.pt model\yolo\
```

---

### 4. Backend setup

```bash
cd backend

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux / macOS

# Install PyTorch with CUDA (adjust index URL for your CUDA version)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# Install backend dependencies
pip install -r requirements.txt

# Install vendored model packages (editable, no-deps to avoid conflicts)
pip install --no-deps -e ..\model\Depth-Anything-V2
pip install --no-deps -e ..\model\ml-depth-pro-main
```

### 5. Frontend setup

```bash
cd frontend
npm install
```

---

## Running the Project

Open **two terminals**:

**Terminal 1 — Backend**
```bash
cd backend
.venv\Scripts\activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 
```
→ API available at **http://localhost:8000**  
→ Interactive API docs at **http://localhost:8000/docs**

**Terminal 2 — Frontend**
```bash
cd frontend
npm run dev
```
→ App available at **http://localhost:3000**

---

## Usage

1. Open **http://localhost:3000**
2. Upload a **PNG / JPG / TIFF / GeoTIFF** aerial or satellite image
3. The pipeline runs automatically:
   - Depth estimation (DA V2 + Depth Pro, sequential)
   - Edge-aware fusion + confidence map
   - For GeoTIFF: SRTM calibration → metric DSM
   - Terrain mesh generation
4. Explore the result in the **3D viewer**:
   - First-person flythrough (WASD + mouse)
   - Switch overlays: RGB / Elevation / Confidence / Disaster Zones
   - Measure height and slope by clicking the terrain
   - Export DSM as GeoTIFF
5. Open **Map** in the header to see every georeferenced scene on a world map (pins come from the GeoTIFF's own
   coordinates; hover a pin for an image preview, click it to open the scene).

---

## Project Structure

```
AakashDrishti/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI routes (upload, pipeline, output)
│   │   ├── core/         # Config, logging
│   │   ├── depth/        # DA V2 & Depth Pro adapters
│   │   ├── fusion/       # Edge-aware depth fusion
│   │   ├── calibration/  # SRTM / GCP calibration
│   │   ├── dsm/          # DSM / rDSM generation & export
│   │   ├── mesh/         # Terrain mesh + GLB export
│   │   ├── pipeline/     # End-to-end pipeline orchestration
│   │   ├── export/       # Unity bundle, scene_assets (buildings/trees/vehicles), rasters, PDF
│   │   └── geospatial/   # GeoTIFF utilities
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── app/          # Next.js pages
│       ├── components/
│       │   └── viewer/   # Three.js terrain viewer
│       ├── hooks/        # React hooks (pipeline polling, etc.)
│       └── lib/          # API client, utilities
├── model/
│   ├── Depth-Anything-V2/       # DA V2 source (vendored)
│   └── ml-depth-pro-main/       # Depth Pro source (vendored)
├── .env.example
└── README.md
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/project/upload` | Upload image, returns `job_id` |
| `POST` | `/api/pipeline/run/{job_id}` | Start pipeline |
| `GET` | `/api/pipeline/{job_id}` | Poll pipeline status & results |
| `GET` | `/api/pipeline/output/{job_id}/{filename}` | Download output file |
| `GET` | `/api/pipeline/{job_id}/disaster-zones` | Disaster zone overlay |
| `DELETE` | `/api/pipeline/{job_id}` | Delete a finished job and its outputs |
| `GET` | `/api/pipeline/locations` | Georeferenced jobs for the world map |
| `GET` | `/api/pipeline/{job_id}/site-analysis` | Site analysis JSON (hand-verified scenes) |
| `GET` | `/api/analyst/{job_id}/report.pdf` | Multi-page PDF situation brief |

---

## Height Field & Unity Export

- The **height field comes from the GAMUS fine-tuned Depth Anything V2** (flip-TTA mean, ground = 2nd percentile,
  scaled by `DA_V2_HEIGHT_SCALE` ≈ 2.6 to approximate metres). Depth Pro is kept as a reference output only
  (`ENABLE_DEPTH_PRO=false` skips it): on nadir imagery it is anti-correlated with height and made the DSM worse.
  Confidence = agreement between the original and horizontally-flipped inference.
- On 6 held-out GAMUS tiles the DSM has Spearman ρ 0.79–0.88 vs. true AGL height (aligned RMSE 1.1–3.0 m on typical tiles;
  a 196 m tall-building tile is much worse). The metre scale is empirical, so non-georeferenced output stays `is_metric: false`.
- Each job also writes a Unity bundle (`unity_scene.json`, `heightmap.r16`, `texture.jpg`) next to the other outputs,
  served at `/api/pipeline/output/{job_id}/{filename}`. Schema: `backend/app/export/unity.py`.
- The Unity viewer's WebGL build is already committed at `frontend/public/unity/` (loaded by
  `frontend/src/components/viewer/UnityViewer.tsx`). Its editable source (Unity 6000.6.2f1 project: scripts, scene,
  materials, WebGL template) lives at `unity/` -- open it in Unity Hub, then
  **AakashDrishti > Build WebGL** (`Assets/AakashDrishtiViewer/Editor/ViewerSetup.cs`) to rebuild. That menu writes
  to `unity/Builds/WebGL/`; copy `Build/` and `StreamingAssets/` from there into
  `frontend/public/unity/` (keep the existing `StreamingAssets/mock/` fixture) to redeploy.

## Additional Analysis Tools

- **Shadow-geometry cross-check** (`app/calibration/shadow_calibration.py`): for georeferenced input with a sun
  elevation angle in its metadata, compares each building's shadow-derived height (`app/buildings/shadow.py`, real
  trigonometry) against its depth-model height. If the median ratio across 3+ buildings deviates >20%, the height
  field is rescaled 50/50 toward the shadow-implied scale and `dsm_is_metric` flips to `true`. Never overrides an
  already DEM/SRTM-verified DSM. Status/numbers are in `metadata.json` under `shadow_calibration_*`.
- **Multi-point GCP refinement** — `POST /api/pipeline/{job_id}/buildings/scale-reference-multi` fits scale+offset
  by least squares over 2+ user-supplied reference heights (vs. the single-point `scale-reference` endpoint's pure
  ratio). Still reports `is_metric: false` — it's an unverified reference, not a survey.
- **Viewshed** — `POST /api/pipeline/{job_id}/viewshed` (`observer_px`, `observer_height_agl`) computes a real
  radial line-of-sight sweep over the DSM and writes a visible-area preview PNG. `app/buildings/scenarios.py::compute_viewshed`.
- **PDF situation report (basic)** — `POST /api/pipeline/{job_id}/report` renders `report.pdf` (title/stats, DSM preview,
  tallest buildings, disaster-zone summary) purely from the job's own already-persisted artifacts. `app/export/report.py`.
- **Landscape-stratified benchmark** — `model/training/bench.py` compares the stock vs. GAMUS fine-tuned checkpoint
  across urban/sparse/forested/mixed GAMUS test tiles (classified from GAMUS's own land-cover masks). Run it with
  `backend/.venv/Scripts/python.exe model/training/bench.py --n-per-subset 15`; results land in
  `model/training/benchmarks/results.md`. No "hilly" subset — GAMUS's AGL height maps normalize away broad terrain
  relief by construction, so it isn't recoverable without a separate bare-earth DEM (see the script's docstring).
  Latest run (59 tiles): mean MAE 3.93 m zero-shot → 2.71 m fine-tuned (production formula), r 0.35 → 0.75.

## Object Detection & Scene Chat

**Elevation-aware object detection** (`app/detect/objects.py`) runs after the DSM is assembled, so every
detection carries an elevation sampled from the scene's own height field. Results go to `objects.json`, the
`objects` array of `unity_scene.json`, and `GET /api/analysis/{job_id}/objects`.

- **Why a DOTA model, not COCO.** COCO weights are trained on ground-level photographs and hit the same nadir
  domain gap the depth backbones do. Measured on three held-out GAMUS tiles: COCO `yolov8s` found 6/19/5 objects
  and labelled rooftop clutter "refrigerator" and "tv"; DOTA `yolov8s-obb` found 300/186/215 vehicles with boxes
  aligned to the parking rows. Large images are tiled — downscaling a 4000 px scene to 1024 px shrinks a car to
  ~3 px and the detector stops seeing it.
- **Three height numbers, not equally trustworthy.** `surface_elevation` (median DSM in the footprint) is the
  object's elevation on the map and is always meaningful. `terrain_elevation` is the bare ground beneath it —
  0 by construction in `pseudo_metric` scenes, where the DSM already *is* height above ground. `height_above_ground`
  is only flagged `height_reliable` when it clears the model's ~2.5 m vertical noise floor **and** stays
  physically plausible for its class (`CLASS_MAX_PLAUSIBLE_M`). A car parked under a tree samples the canopy, so
  without that check it would be published as "a 7.8 m small vehicle"; with it, no small vehicle ever reports a
  reliable height — the honest outcome for a single-view model.

**Scene chat** — `POST /api/analyst/{job_id}/chat/stream` (SSE) answers follow-up questions about a scene,
streamed token by token, with the prior turns passed as `history`. The scene statistics are re-read through the
read-only tools on every turn, so answers track the latest hazard runs, and `guard_stats_only` still enforces
that only derived numbers ever leave the machine — never imagery. Set `OPENAI_API_KEY` to use a real model;
without one it falls back to the same offline template analyst the brief uses. The chat lives in the sidebar of
the **AI brief** screen, and `get_detected_objects` is exposed as a tool so it can answer "how many vehicles are
there?".

## Recent additions

### Unity 3D viewer (buildings, vehicles, trees)
- **Roofs show the real photo.** Each building samples the scene image under its roof (UV-mapped like the terrain);
  walls get a shaded facade colour. Detected **vehicles, trucks, tanks and pools** are drawn as sized, oriented,
  photo-coloured shapes, and **trees** as trunk + canopy. `backend/app/export/scene_assets.py` first removes
  footprints that are really vegetation, rail/road slivers or parked-car clusters from the building list.
- The disaster-zones overlay is **off until toggled on**.
- Rebuild: `AakashDrishti > Build WebGL` in Unity (or batch mode,
  `Unity -batchmode -quit -projectPath unity -executeMethod AakashDrishti.Viewer.Editor.ViewerSetup.BuildWebGL`), then copy
  `unity/Builds/WebGL/Build/WebGL.*` into `frontend/public/unity/Build/` as `Output.*`.
- Rebuild an existing job's Unity scene without re-running depth: `python backend/scripts/reexport_unity.py <job_dir>`.
- `ENABLE_DEPTH_PRO` now defaults to `false` (Depth Pro is reference-only and anti-correlated with height); set it to `true` to run it.

### Hand-verified 7.tif site scene (`backend/scripts/denver7/`, `backend/demo/denver7/`)
A GeoTIFF analysed **without any ML model**: roofs from smoothness + cast-shadow evidence, every review tile checked by eye,
vehicles by an oriented matched filter, trees from the canopy mask, **per-building heights from shadow length**
(`H = L / tan(sun elevation)`, sun measured from the image). The stored bundle is installed on startup as job
`site-denver-7` and shown as a second featured scene on the dashboard, with the full survey, hazards, AI brief and
`report.pdf`, plus `/site/site-denver-7` (3D scene + analysis tables). Rebuild order: `build_buildings.py`,
`run_cars.py`, `run_trees.py`, `build_scene.py`, `build_survey.py` (each prints what it wrote). Heights are estimates
(about +/-15-25%); no LiDAR reference was available, so no accuracy score is claimed.

### World map
`/map` plots every georeferenced job (`GET /api/pipeline/locations`) on a Leaflet map (Esri satellite / OpenStreetMap
tiles, internet needed). Hovering a pin shows a small image preview above it.

### Reports, history and robustness
- **PDF situation brief** (`GET /api/analyst/{id}/report.pdf`): KPI cover, clickable contents and bookmarks, charts
  (heights, slope, flood response curve, validation) and tables. `backend/app/analyst/pdf_report.py`.
- **History delete**: `DELETE /api/pipeline/{job_id}` and a delete button on each card (running jobs must be cancelled first).
- **Very large images**: inputs above 6000 px (long side) are processed at a capped size with the geotransform scaled, and
  previews are colourised through lookup tables, so a 183-megapixel GeoTIFF no longer exhausts RAM. Allow about 2 GB of free
  disk per large scene.
- **Tests**: `cd backend && python -m pytest tests -q` (job store, delete endpoint, validation metrics, PDF, scene assets);
  CI (`.github/workflows/ci.yml`) runs frontend lint/build and these tests.

---

## Notes

- Models are loaded and unloaded **sequentially** to stay within 8 GB VRAM
- Non-georeferenced images produce a **relative DSM (rDSM)** — no metric scale
- GeoTIFF inputs with valid CRS produce a **calibrated metric DSM** via SRTM
- `xFormers not available` warnings are harmless — xFormers is optional
- Never commit `.env`, `data/`, `context/`, or `test-data/` — these are gitignored

---

## License

This project is developed for Smart India Hackathon 2026 (SIH-26175).

---

## Survey workspace (added on top of the dashboard)

The dashboard, history and scenarios screens are unchanged. A finished job can be opened as a full **survey**
(`/survey/<job_id>`), styled with the same theme, with these sections:

| Section | What it does |
|---|---|
| Workspace | Layer toggles (optical, height, hillshade, slope, uncertainty, land cover), swipe/blend compare, hover and pinned readouts, calibration sources, run timings |
| Flythrough | Chunked-LOD terrain (RTIN meshes) with fly / walk / orbit, auto-tour, path record + replay, MP4 export, probe, elevation profile, distance/area measure, flood level, landing zones, viewshed |
| Validation lab | Score against a LiDAR/nDSM raster: RMSE, MAE, bias, NMAD, r, delta1 per class and landscape, scatter, error map, split view; measured benchmark table |
| Hazards | Flood (area, volume, buildings), landing-zone finder (8:1 approach check), slope hazard, viewshed; results become "findings" |
| AI brief | Situation report, ranked risks and response plan from derived statistics only (MCP tool server in `backend/app/analyst/mcp_server.py`); offline template analyst when no `OPENAI_API_KEY`; PDF export |
| Downloads | COG DSM/nDSM/uncertainty/slope/aspect, GLB/OBJ meshes, previews, JSON |

**Advanced Run** (`/expedition/new`) exposes GSD / CRS / sun overrides, DEM source, TTA, Depth Pro reference output, tile size,
GCP table/CSV, and bundled real GAMUS sample scenes (`python backend/scripts/fetch_gamus_samples.py`).

Backend additions: tiled inference with D4 test-time augmentation and an uncertainty map, DEM auto-fetch (SRTM), robust scale
calibration (DEM + GCP + shadow geometry), RTIN LOD chunks, live step/log progress over SSE with cancel and one automatic retry,
optional JWT auth with analyst/responder/viewer roles, and `docker compose up --build`.

**Honest limits:** single-view height error is metre-scale (very tall towers are compressed by the model), the shadow cross-check is
unreliable in dense urban canyons, landing zones are candidates for operator confirmation, and the land-cover classes are
heuristic (colour + height), not a trained segmentation head.
