"""Application configuration, loaded from environment variables / .env.

Paths are resolved relative to the repository root so the backend can be
started from any working directory.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


def _resolve(path_str: str) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    return path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Depth Anything V2
    # Default points at the GAMUS-fine-tuned checkpoint (measured RMSE 3.94m -> 2.40m improvement over the
    # stock pretrained weights on held-out remote-sensing AGL-height data -- see
    # ml/training/runs/da_v2_gamus_full/train_log.jsonl and context/research-notes.md). This .env value
    # is normally set explicitly (see .env.example); this default only applies if unset.
    depth_anything_v2_encoder: str = "vitb"
    depth_anything_v2_checkpoint: str = "./ml/depth_anything_v2_vitb_gamus_best.pth"

    # Depth Pro
    depth_pro_checkpoint: str = "./ml/ml-depth-pro-main/checkpoints/depth_pro.pt"
    depth_pro_precision: str = "float16"
    # Depth Pro is reference-only (it does not feed the height field); disable to save ~60% runtime.
    enable_depth_pro: bool = False

    # Model-output -> approximate metres. Empirical median slope of true AGL vs the fine-tuned DA V2
    # output over 6 held-out GAMUS test tiles (range 1.8-3.1, one tall-building outlier at 8.4).
    da_v2_height_scale: float = 2.6

    # Horizontal metres-per-pixel assumed for non-georeferenced images in the Unity export
    # (an assumption, reported as "assumed_gsd" in unity_scene.json -- not measured).
    assumed_gsd_m: float = 0.5

    # Aerial object detection (FR-50). DOTA-trained oriented-box weights: COCO weights hit the same
    # nadir domain gap the depth backbones do (measured: 6 vs 300 detections on the same tile).
    enable_object_detection: bool = True
    object_detection_weights: str = "./ml/yolo/yolov8s-obb.pt"
    object_detection_conf: float = 0.3
    object_detection_imgsz: int = 1024

    # Device
    device: str = "cuda"

    # Reference elevation data
    srtm_data_dir: str = "./data/reference"

    # Storage
    upload_dir: str = "./data/uploads"
    output_dir: str = "./data/outputs"

    # API
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    # Input limits (FR-01)
    max_upload_bytes: int = 2 * 1024 * 1024 * 1024

    # Tiled inference (FR-06): tile edge in px and fractional overlap
    tile_size: int = 1024
    tile_overlap: float = 0.25

    # DEM handling: fetch missing SRTM-derived 1-arcsec tiles (public AWS terrain tiles)
    # when a georeferenced input has no local DEM. Disable for air-gapped deployments.
    dem_auto_download: bool = True

    # Auth (FR-48). When AUTH_REQUIRED is false every request is treated as an analyst.
    auth_required: bool = False
    auth_secret: str = "change-me-in-env"
    auth_token_ttl_hours: int = 24 * 7

    # AI analyst (optional, network-gated). Any OpenAI-compatible endpoint works.
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    @property
    def samples_dir_path(self) -> Path:
        return _resolve("./data/samples")

    @property
    def benchmarks_dir_path(self) -> Path:
        return _resolve("./data/benchmarks")

    @property
    def users_file_path(self) -> Path:
        return _resolve("./data/users.json")

    @property
    def analyst_available(self) -> bool:
        return bool(self.openai_api_key.strip())

    @property
    def object_detection_weights_path(self) -> Path:
        return _resolve(self.object_detection_weights)

    @property
    def da_v2_checkpoint_path(self) -> Path:
        return _resolve(self.depth_anything_v2_checkpoint)

    @property
    def depth_pro_checkpoint_path(self) -> Path:
        return _resolve(self.depth_pro_checkpoint)

    @property
    def srtm_dir_path(self) -> Path:
        return _resolve(self.srtm_data_dir)

    @property
    def upload_dir_path(self) -> Path:
        return _resolve(self.upload_dir)

    @property
    def output_dir_path(self) -> Path:
        return _resolve(self.output_dir)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.auth_required and settings.auth_secret == "change-me-in-env":
        raise RuntimeError(
            "AUTH_REQUIRED is true but AUTH_SECRET is still the default placeholder. "
            "Set AUTH_SECRET to a unique random value in .env before enabling auth."
        )
    settings.upload_dir_path.mkdir(parents=True, exist_ok=True)
    settings.output_dir_path.mkdir(parents=True, exist_ok=True)
    return settings
