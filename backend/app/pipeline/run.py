"""Pipeline orchestration for POST /api/pipeline/run/{job_id}.

Steps (each reported live): ingest -> tiling -> inference -> blending -> dem -> calibration ->
shadow -> mesh -> export. Any exception marks the job FAILED with the real error (one automatic
retry first); cancellation is honoured between and inside steps. Nothing is fabricated: when
scale evidence is missing the output is an honest relative DSM.
"""

from __future__ import annotations

import json
import shutil
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from scipy import ndimage

from app.buildings.disaster import (
    find_emergency_landing_zones,
    find_flood_risk_zones,
    find_highrise_fire_access_risk,
)
from app.buildings.height import compute_building_heights
from app.buildings.segment import BuildingSegmentation, segment_at_scale, segment_buildings, segment_buildings_agl
from app.buildings.shadow import analyze_shadows
from app.calibration.dem import build_dtm
from app.calibration.scale import CalibrationOutcome, calibrate_scene
from app.core.config import Settings
from app.core.logging import get_logger
from app.depth.da_v2_adapter import tile_grid
from app.depth.pipeline import inference_scale, run_depth_stack, segmentation_scale
from app.depth.visualize import save_depth_preview
from app.detect.objects import DetectionResult, detect_objects
from app.export import rasters
from app.export.unity import export_unity_bundle
from app.fusion.edge_aware import da_only_relative_height, uncertainty_from_std
from app.geospatial.raster_io import write_float32_geotiff
from app.input.detect import UnsupportedInputError, apply_overrides, detect_input, read_rgb_array
from app.jobs.models import JobStage, JobState, RunOptions
from app.jobs.reporter import JobCancelled, JobReporter
from app.jobs.store import JobStore
from app.landcover.classify import CLASS_NAMES, LandCover, class_color_image, classify_land_cover
from app.mesh.generate import generate_terrain_mesh
from app.mesh.rtin import build_scene_meshes
logger = get_logger(__name__)
cv2.ocl.setUseOpenCL(False)

MAX_ORTHO_PX = 4096
MAX_WORK_PX = 6000   # longest side the pipeline works at; larger inputs are downscaled at ingest
NATIVE_SCALE_PRIOR = 1.0  # rel_height is already multiplied by settings.da_v2_height_scale (empirical ~2.6)


def _url(job_id: str, filename: str) -> str:
    return f"/api/pipeline/output/{job_id}/{filename}"


def _stats(arr: np.ndarray) -> dict:
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return {"min": 0.0, "max": 0.0, "mean": 0.0}
    return {"min": float(finite.min()), "max": float(finite.max()), "mean": float(finite.mean())}


def _relative_scene_height(rel_height: np.ndarray) -> np.ndarray:
    """Relative DSM in scene units (1 px = 1 unit): range scaled to 10% of the longer side."""
    normalised = rasters.normalise(rel_height, 0.5, 99.5)
    return (normalised * 0.10 * max(rel_height.shape)).astype(np.float32)


def _pixel_to_lonlat(geo, col: float, row: float) -> Optional[tuple[float, float]]:
    """Pixel centre -> WGS84 lon/lat. Mirrors Scene.pixel_to_lonlat for stages that run before
    arrays.npz exists (and therefore before a Scene can be loaded)."""
    import rasterio
    from rasterio.warp import transform as warp_transform

    x, y = rasterio.Affine(*geo.transform) * (col + 0.5, row + 0.5)
    if geo.crs.upper().endswith("4326"):
        return float(x), float(y)
    lon, lat = warp_transform(geo.crs, "EPSG:4326", [x], [y])
    return float(lon[0]), float(lat[0])


def execute_pipeline(job_id: str, store: JobStore, settings: Settings) -> None:
    job = store.get(job_id)
    reporter = JobReporter(store, job)
    for attempt in (1, 2):
        job.attempts = attempt
        try:
            _run_once(job, store, settings, reporter)
            return
        except JobCancelled:
            job.stage = JobStage.FAILED
            job.error = "Cancelled by user."
            reporter.log("Job cancelled by user.", level="warn")
            store.update(job)
            return
        except Exception as exc:  # noqa: BLE001 - reported to the user, retried once
            logger.exception("Pipeline attempt %d failed for job %s", attempt, job_id)
            running = next((s.key for s in job.steps if s.status == "running"), None)
            reporter.fail(running, f"{type(exc).__name__}: {exc}")
            if attempt == 1 and not isinstance(exc, (UnsupportedInputError, FileNotFoundError)):
                reporter.log("Retrying once...", level="warn")
                for step in job.steps:
                    step.status, step.progress, step.detail = "pending", 0.0, None
                continue
            job.stage = JobStage.FAILED
            job.error = str(exc)
            store.update(job)
            return


def _run_once(job: JobState, store: JobStore, settings: Settings, rep: JobReporter) -> None:
    job_id = job.job_id
    job_dir = store.job_dir(job_id)
    options: RunOptions = job.options
    started_at = time.time()
    outputs = job.outputs
    timings: dict[str, float] = {}

    # ---------------- ingest ----------------
    rep.start("ingest", "Reading and validating the input image")
    source_path = Path(job.stored_path)
    if not source_path.exists():
        raise UnsupportedInputError(f"Uploaded source file is missing: {source_path}")
    descriptor = detect_input(source_path)
    descriptor = apply_overrides(
        descriptor, options.gsd_m, options.crs, options.origin_x, options.origin_y,
        options.sun_azimuth_deg, options.sun_elevation_deg,
    )
    geo = descriptor.geo
    job.is_georeferenced = descriptor.is_georeferenced
    job.mode = "absolute" if descriptor.is_georeferenced else "relative"
    rgb = read_rgb_array(source_path)
    height_px, width_px = rgb.shape[:2]
    # Very large scenes are processed at a capped working size. The height model already looks at the image at
    # ~0.25 m/px (see inference_scale below), so a 12688 x 14403 px (183 MP) scene held ~25 full-resolution rasters
    # in memory and exhausted a 16 GB machine without adding any information. The geotransform, pixel size and
    # sun metadata are scaled to match, so georeferencing stays exact.
    work_factor = max(height_px, width_px) / MAX_WORK_PX
    if work_factor > 1.0:
        new_w, new_h = max(2, round(width_px / work_factor)), max(2, round(height_px / work_factor))
        rgb = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)
        sx, sy = width_px / new_w, height_px / new_h
        if descriptor.geo is not None:
            g = descriptor.geo
            t = g.transform
            geo = replace(g, transform=(t[0] * sx, t[1] * sy, t[2], t[3] * sx, t[4] * sy, t[5]), width=new_w, height=new_h,
                          resolution=(g.resolution[0] * sx, g.resolution[1] * sy))
            descriptor = replace(descriptor, geo=geo)
        if descriptor.gsd_m:
            descriptor = replace(descriptor, gsd_m=descriptor.gsd_m * (sx + sy) / 2.0)
        rep.log(f"Large scene ({width_px}x{height_px} px): processing at {new_w}x{new_h} px (x{(sx + sy) / 2.0:.2f} coarser) to fit in memory",
                step="ingest")
        height_px, width_px = new_h, new_w
    px_m = rasters.pixel_size_m(geo, descriptor.gsd_m)
    have_metric_pixel = bool(descriptor.gsd_m or geo)
    rep.log(
        f"{descriptor.file_format.upper()} {width_px}x{height_px}, {descriptor.band_count} band(s), "
        f"{descriptor.bit_depth}-bit; mode={job.mode}; GSD={descriptor.gsd_m or 'unknown'} m/px; "
        f"CRS={geo.crs if geo else 'none'}; sun az/el="
        f"{descriptor.sun_azimuth_deg}/{descriptor.sun_elevation_deg}",
        step="ingest",
    )
    for note in descriptor.notes:
        rep.log(note, step="ingest")

    ortho = rgb
    if max(height_px, width_px) > MAX_ORTHO_PX:
        scale = MAX_ORTHO_PX / max(height_px, width_px)
        ortho = cv2.resize(rgb, (int(width_px * scale), int(height_px * scale)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(job_dir / "ortho.jpg"), cv2.cvtColor(ortho, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])
    thumb_scale = 512 / max(height_px, width_px)
    thumb = cv2.resize(rgb, (max(1, int(width_px * thumb_scale)), max(1, int(height_px * thumb_scale))), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(job_dir / "thumb.jpg"), cv2.cvtColor(thumb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
    outputs["original"] = _url(job_id, "ortho.jpg")
    outputs["ortho_jpg"] = _url(job_id, "ortho.jpg")
    outputs["thumb_jpg"] = _url(job_id, "thumb.jpg")
    rep.done("ingest", f"{job.mode.upper()} mode, {width_px}x{height_px} px")
    store.update(job)

    # ---------------- tiling ----------------
    rep.start("tiling", "Planning overlapping tiles")
    infer_gsd = px_m if have_metric_pixel else None
    infer_factor = inference_scale(infer_gsd)
    infer_h, infer_w = max(1, round(height_px * infer_factor)), max(1, round(width_px * infer_factor))
    windows = tile_grid(infer_h, infer_w, options.tile_size, options.overlap)
    resample_note = (f"; resampled to {infer_w}x{infer_h} (0.25 m/px, calibrated against reference house heights)"
                     if infer_factor < 1.0 else "")
    rep.done("tiling", f"{len(windows)} tile(s) of {options.tile_size}px, {int(options.overlap * 100)}% overlap, Hann blend{resample_note}")

    # ---------------- inference ----------------
    rep.start("inference", "Loading Depth Anything V2")
    infer_started = time.time()

    def on_progress(pct: float, detail: str) -> None:
        rep.check_cancel()
        rep.progress("inference", pct * 0.85, f"Depth Anything V2 {detail}")
        if pct >= 100 or int(pct) % 25 == 0:
            rep.log(f"Depth Anything V2 {detail} (TTA={'D4x8' if options.tta else 'off'})", step="inference")

    def on_depth_pro() -> None:
        rep.progress("inference", 88.0, "Depth Pro ensemble (edge guide)")
        rep.log("Running Depth Pro as edge-aware ensemble member", step="inference")

    stack = run_depth_stack(
        rgb=rgb,
        work_dir=job_dir,
        da_v2_checkpoint=settings.da_v2_checkpoint_path,
        da_v2_encoder=settings.depth_anything_v2_encoder,
        depth_pro_checkpoint=settings.depth_pro_checkpoint_path,
        depth_pro_precision=settings.depth_pro_precision,
        device_preference=settings.device,
        tile_size=options.tile_size,
        overlap=options.overlap,
        tta=options.tta,
        use_depth_pro=options.ensemble,
        on_da_progress=on_progress,
        on_depth_pro_start=on_depth_pro,
        gsd_m=infer_gsd,
    )
    timings["inference_s"] = time.time() - infer_started
    if stack.depth_pro_skipped_reason:
        rep.log(f"Depth Pro not used: {stack.depth_pro_skipped_reason}", level="warn", step="inference")
    rep.done("inference", f"{stack.da.tile_count} tiles x {stack.da.tta_variants} TTA views in {timings['inference_s']:.1f}s")

    # ---------------- blending ----------------
    rep.start("blending", "Blending tiles and computing per-pixel uncertainty")
    write_float32_geotiff(stack.da.mean, job_dir / "depth_anything_v2.tif", geo)
    outputs["depth_anything_v2_tif"] = _url(job_id, "depth_anything_v2.tif")

    if stack.depth_pro_metric_depth is not None:
        # Depth Pro is camera-distance based and anti-correlated with height on nadir imagery, so it is
        # kept as a reference output only and never feeds the height field.
        write_float32_geotiff(stack.depth_pro_metric_depth, job_dir / "depth_pro.tif", geo)
        outputs["depth_pro_tif"] = _url(job_id, "depth_pro.tif")

    height_scale = settings.da_v2_height_scale if stack.da.checkpoint_is_height else 1.0
    rel_height = (da_only_relative_height(stack.da.mean, stack.da.checkpoint_is_height) * height_scale).astype(np.float32)
    unc01 = (uncertainty_from_std(stack.da.std, rel_height) if options.tta else np.zeros_like(rel_height)).astype(np.float32)
    confidence = (1.0 - unc01).astype(np.float32)
    write_float32_geotiff(rel_height, job_dir / "fused_depth.tif", geo)
    outputs["fused_depth_tif"] = _url(job_id, "fused_depth.tif")
    fused_for_preview = rel_height
    write_float32_geotiff(confidence, job_dir / "confidence.tif", geo)
    save_depth_preview(fused_for_preview, job_dir / "fused_depth_preview.png", cmap_name="terrain")
    save_depth_preview(confidence, job_dir / "confidence_preview.png", cmap_name="viridis")
    outputs["confidence_tif"] = _url(job_id, "confidence.tif")
    outputs["fused_depth_preview_png"] = _url(job_id, "fused_depth_preview.png")
    outputs["confidence_preview_png"] = _url(job_id, "confidence_preview.png")
    rep.done("blending", "Seamless mosaic and per-pixel uncertainty ready")
    store.update(job)

    # ---------------- building footprints + land cover (feeds ground mask) ----------------
    # Best-effort: a heuristic classical-CV edge case here (watershed/contour degeneracies)
    # must degrade to "no buildings found", never fail the whole job.
    rep.start("dem", "Preparing terrain reference")
    height_is_agl = stack.da.checkpoint_is_height
    try:
        segmentation = segment_at_scale(
            (lambda img, hgt: segment_buildings_agl(img, hgt)) if height_is_agl
            else (lambda img, hgt: segment_buildings(img, hgt, confidence if confidence.shape == hgt.shape else None)),
            rgb, rel_height, segmentation_scale(infer_gsd),
        )
        land = classify_land_cover(rgb, rel_height, segmentation.mask, height_is_agl=height_is_agl)
        rep.log("Land cover: " + ", ".join(f"{k}={v:.0%}" for k, v in land.fractions().items() if v > 0.005), step="dem")
    except Exception as exc:  # noqa: BLE001 -- building/land-cover analysis is best-effort, must never fail the job
        logger.exception("Building segmentation / land-cover classification failed for job %s", job_id)
        rep.log(f"Building/land-cover analysis failed and was skipped: {exc}", level="warn", step="dem")
        segmentation = BuildingSegmentation(
            mask=np.zeros(rel_height.shape, dtype=bool), labels=np.zeros(rel_height.shape, dtype=np.int32),
            footprints=[], method_note=f"Building analysis failed and was skipped: {exc}",
        )
        land = LandCover(labels=np.zeros(rel_height.shape, dtype=np.uint8), counts={"ground": int(rel_height.size)})

    dtm: Optional[np.ndarray] = None
    dem_note = "Not georeferenced: no terrain reference is available."
    if geo is None:
        rep.skip("dem", "not georeferenced")
    elif options.dem_source == "none":
        rep.skip("dem", "DEM disabled by the user")
        dem_note = "DEM disabled by the user."
    else:
        dem = build_dtm(geo, rel_height.shape, settings.srtm_dir_path,
                        settings.dem_auto_download and options.dem_source == "auto", lambda m: rep.log(m, step="dem"))
        dem_note = dem.note
        if dem.status == "ok":
            dtm = dem.dem_on_grid
            rep.done("dem", dem.note)
        else:
            rep.skip("dem", dem.note)

    # ---------------- scale calibration (DEM + GCP) ----------------
    rep.start("calibration", "Fitting scale against DEM and control points")
    outcome = calibrate_scene(rel_height, land.labels, geo, dtm, job.gcps, [], NATIVE_SCALE_PRIOR if stack.da.checkpoint_is_height else None)
    rep.done("calibration", _calibration_summary(outcome))

    # ---------------- shadow cross-check ----------------
    rep.start("shadow", "Measuring shadows for an independent height estimate")
    sun_el = descriptor.sun_elevation_deg
    footprints_ready = len(segmentation.footprints) > 0
    shadow_analysis = analyze_shadows(rgb, segmentation.footprints, segmentation.labels, descriptor.sun_azimuth_deg,
                                      sun_el, px_m if have_metric_pixel else None)
    shadow_summary = "skipped"
    shadow_agreement: Optional[float] = None
    if sun_el is None or not have_metric_pixel:
        rep.skip("shadow", "needs a sun elevation and a metric pixel size (metadata or user override)")
        shadow_summary = "Needs sun elevation and GSD."
    elif not footprints_ready or shadow_analysis.measured_count < 3:
        rep.skip("shadow", f"only {shadow_analysis.measured_count} building shadow(s) measurable")
        shadow_summary = "Too few measurable shadows."
    else:
        trend = outcome.ground_trend_rel if outcome.ground_trend_rel is not None else np.zeros_like(rel_height)
        objects_rel = np.maximum(rel_height - trend, 0.0)
        pairs: list[tuple[float, float]] = []
        boxes = ndimage.find_objects(segmentation.labels.astype(np.int32))
        for estimate in shadow_analysis.estimates:
            if estimate.shadow_estimate_m is None or not 0 < estimate.building_id <= len(boxes):
                continue
            box = boxes[estimate.building_id - 1]
            if box is None:
                continue
            values = objects_rel[box][segmentation.labels[box] == estimate.building_id]
            if values.size:
                pairs.append((float(np.percentile(values, 90)), float(estimate.shadow_estimate_m)))
        previous_scale = outcome.scale
        outcome = calibrate_scene(rel_height, land.labels, geo, dtm, job.gcps, pairs,
                                  NATIVE_SCALE_PRIOR if stack.da.checkpoint_is_height else None)
        if previous_scale and outcome.scale:
            shadow_agreement = abs(outcome.scale / previous_scale - 1.0)
        shadow_summary = (f"{len(pairs)} shadow heights fused; azimuth {shadow_analysis.azimuth_deg:.0f} deg "
                          f"({shadow_analysis.azimuth_source})")
        rep.done("shadow", shadow_summary + _calibration_summary(outcome, prefix="; final: "))
    store.update(job)

    # ---------------- assemble DSM arrays ----------------
    gsd_assumed = False
    if outcome.is_metric and outcome.ndsm_m is not None and outcome.dsm is not None:
        dsm, ndsm, dsm_kind = outcome.dsm, outcome.ndsm_m, outcome.kind
        scale_m = float(outcome.scale or 1.0)
        if have_metric_pixel:
            px_for_analysis = px_m
        else:
            # Heights are metres, so the horizontal axis must be metres too or slopes, areas and the 3D
            # scene would be inconsistent. The height model was trained at ~0.5 m/px, so that is the
            # scale its output implicitly assumes; it is flagged as assumed, never as measured.
            px_for_analysis = settings.assumed_gsd_m
            gsd_assumed = True
            rep.log(f"No pixel size known: assuming {px_for_analysis:g} m/px (the scale the height model was trained at). "
                    "Heights and distances are approximate; enter the real GSD under Advanced options for accurate values.",
                    level="warn", step="calibration")
    else:
        dsm = _relative_scene_height(rel_height)
        trend = outcome.ground_trend_rel if outcome.ground_trend_rel is not None else np.zeros_like(rel_height)
        span = max(float(np.nanpercentile(rel_height, 99.5) - np.nanpercentile(rel_height, 0.5)), 1e-9)
        ndsm = (np.maximum(rel_height - trend, 0.0) / span * 0.10 * max(rel_height.shape)).astype(np.float32)
        dsm_kind, scale_m, px_for_analysis = "relative", None, 1.0
    dsm_is_metric = dsm_kind in ("absolute_dsm", "pseudo_metric")
    std_units = stack.da.std * (scale_m if scale_m else 1.0)
    uncertainty_m = np.where(np.isfinite(std_units), std_units, 0.0).astype(np.float32)
    if not options.tta:
        uncertainty_m = (unc01 * (np.nanpercentile(ndsm, 95) * 0.15 + 1e-6)).astype(np.float32)

    # ---------------- buildings, disaster zones (legacy GeoJSON), validation ----------------
    building_heights = compute_building_heights(segmentation.footprints, segmentation.labels, ndsm, confidence, dsm_is_metric)
    height_by_id = {bh.id: bh for bh in building_heights}
    shadow_by_id = {s.building_id: s for s in shadow_analysis.estimates}

    def _shadow_delta(building_id: int) -> Optional[float]:
        # shadow_analysis was computed before building_heights existed (it needs ndsm, which the
        # shadow step itself may refine), so the delta is derived here instead of trusting
        # ShadowEstimate.depth_vs_shadow_delta_m (always None at that point).
        estimate = shadow_by_id.get(building_id)
        bh = height_by_id.get(building_id)
        if estimate is None or estimate.shadow_estimate_m is None or bh is None:
            return None
        if not bh.is_metric or bh.height_value is None:
            return None
        return float(bh.height_value - estimate.shadow_estimate_m)

    buildings_payload = {
        "job_id": job_id, "count": len(building_heights),
        "buildings": [{
            "id": bh.id, "footprint": [list(pt) for pt in bh.footprint], "area_px": bh.area_px, "height_m": bh.height_value,
            "is_metric": bh.is_metric, "confidence": bh.mean_confidence,
            "shadow_estimate_m": shadow_by_id[bh.id].shadow_estimate_m if bh.id in shadow_by_id else None,
            "depth_vs_shadow_delta_m": _shadow_delta(bh.id),
        } for bh in building_heights],
        "note": segmentation.method_note,
    }
    (job_dir / "buildings.json").write_text(json.dumps(buildings_payload), encoding="utf-8")
    outputs["buildings_json"] = _url(job_id, "buildings.json")

    zones_payload = {"job_id": job_id, "count": 0, "zones": [], "note": ""}
    try:
        zone_features = find_emergency_landing_zones(dsm, segmentation.mask, geo=geo)
        zone_features += find_flood_risk_zones(dsm, geo=geo, building_mask=segmentation.mask, dsm_is_metric=dsm_is_metric)
        zone_features += find_highrise_fire_access_risk(building_heights, geo=geo)
        zones_payload = {
            "job_id": job_id, "count": len(zone_features),
            "zones": [{"type": f["properties"]["zone_type"], "geometry": f["geometry"], "risk_level": f["properties"].get("risk_level"),
                       "notes": f["properties"].get("note"), "properties": f["properties"]} for f in zone_features],
            "note": "Heuristic decision support, not certified surveys.",
        }
    except Exception as exc:  # noqa: BLE001 - optional legacy layer
        zones_payload["note"] = f"Zone analysis skipped: {exc}"
    (job_dir / "disaster_zones.json").write_text(json.dumps(zones_payload), encoding="utf-8")
    outputs["disaster_zones_json"] = _url(job_id, "disaster_zones.json")

    # ---------------- aerial object detection (elevation-aware) ----------------
    # Runs after the DSM arrays exist so every detection can carry a real elevation sampled from
    # this scene's own height field. Best-effort like the building/land-cover stage: a missing
    # dependency, missing weights or a detector error must never fail the job.
    rep.start("detect", "Detecting vehicles and other aerial objects")
    detection = DetectionResult(status="skipped", note="Object detection is disabled (ENABLE_OBJECT_DETECTION=false).")
    if settings.enable_object_detection:
        try:
            terrain_surface = (dsm - ndsm).astype(np.float32)
            detection = detect_objects(
                rgb=rgb, dsm=dsm, ndsm=ndsm, terrain=terrain_surface,
                weights=settings.object_detection_weights_path, device_preference=settings.device,
                conf=settings.object_detection_conf, imgsz=settings.object_detection_imgsz,
                dsm_is_metric=dsm_is_metric,
                to_lonlat=(lambda c, r: _pixel_to_lonlat(geo, c, r)) if geo is not None else None,
            )
        except Exception as exc:  # noqa: BLE001 -- detection is best-effort, must never fail the job
            logger.exception("Object detection failed for job %s", job_id)
            detection = DetectionResult(status="unavailable", note=f"Object detection failed and was skipped: {exc}")
    if detection.status == "ok":
        top = ", ".join(f"{name} x{count}" for name, count in sorted(detection.counts.items(), key=lambda kv: -kv[1])[:4])
        rep.done("detect", f"{len(detection.objects)} object(s): {top}" if top else "no objects found")
    else:
        rep.skip("detect", detection.note)
    objects_payload = detection.as_payload(job_id, "m" if dsm_is_metric else "relative units")
    (job_dir / "objects.json").write_text(json.dumps(objects_payload), encoding="utf-8")
    outputs["objects_json"] = _url(job_id, "objects.json")

    validation_result = {
        "status": "unavailable",
        "note": "Upload a reference LiDAR/DSM in the Validation lab to score this scene.",
        "rmse": None, "mae": None, "correlation": None, "valid_pixel_count": None, "reference_source": None,
    }
    (job_dir / "validation.json").write_text(json.dumps({"job_id": job_id, "result": validation_result}), encoding="utf-8")
    outputs["validation_json"] = _url(job_id, "validation.json")

    # ---------------- mesh ----------------
    rep.start("mesh", "Building adaptive RTIN mesh with three LOD levels")
    rep.check_cancel()
    mesh_started = time.time()
    scene_geometry, export_stats = build_scene_meshes(
        dsm, job_dir, px_for_analysis, dsm_is_metric, rgb, ortho,
    )
    timings["mesh_s"] = time.time() - mesh_started
    lod0 = sum(c["triangles"][0] for c in scene_geometry["chunks"])
    rep.done("mesh", f"{len(scene_geometry['chunks'])} chunk(s), {lod0:,} LOD0 triangles; export mesh {export_stats['triangles']:,} triangles")
    outputs["terrain_hires_glb"] = _url(job_id, "terrain_hires.glb")
    legacy_mesh = generate_terrain_mesh(dsm_height=dsm, rgb_image=rgb, geo=geo, dsm_is_metric=dsm_is_metric,
                                        assumed_pixel_size_m=px_for_analysis if gsd_assumed else None)
    (job_dir / "terrain.glb").write_bytes(legacy_mesh.glb_bytes)
    outputs["terrain_glb"] = _url(job_id, "terrain.glb")
    with zipfile.ZipFile(job_dir / "terrain_obj.zip", "w", zipfile.ZIP_DEFLATED) as bundle:
        obj_dir = job_dir / "terrain_obj"
        for path in obj_dir.glob("*"):
            bundle.write(path, path.name)
        bundle.write(job_dir / "ortho.jpg", "ortho.jpg")
    outputs["terrain_obj_zip"] = _url(job_id, "terrain_obj.zip")
    shutil.rmtree(job_dir / "terrain_obj", ignore_errors=True)

    # ---------------- export ----------------
    rep.start("export", "Writing COG rasters, previews and scene manifest")
    slope, aspect = rasters.slope_aspect(dsm, px_for_analysis)
    # The raster/PNG writes are independent and spend their time in GDAL/OpenCV/zlib (GIL released),
    # so they run concurrently instead of one after another.
    def _height_color() -> None:
        colored = rasters.height_color_image(dsm)
        rasters.save_png(colored, job_dir / "height_color.png")
        rasters.save_png(colored, job_dir / "dsm_preview.png")

    export_tasks = [
        lambda: rasters.write_cog(dsm, job_dir / "dsm.tif", geo),
        lambda: rasters.write_cog(ndsm, job_dir / "ndsm.tif", geo),
        lambda: rasters.write_cog(uncertainty_m, job_dir / "uncertainty.tif", geo),
        lambda: rasters.write_cog(slope, job_dir / "slope.tif", geo),
        lambda: rasters.write_cog(aspect, job_dir / "aspect.tif", geo),
        lambda: rasters.save_png(rasters.hillshade(dsm, px_for_analysis), job_dir / "hillshade.png"),
        _height_color,
        lambda: rasters.save_png(rasters.slope_color_image(slope), job_dir / "slope_color.png"),
        lambda: rasters.save_png(rasters.uncertainty_color_image(unc01), job_dir / "uncertainty_color.png"),
        lambda: rasters.save_png(class_color_image(land.labels), job_dir / "landcover.png"),
    ]
    with ThreadPoolExecutor(max_workers=3) as pool:
        for future in [pool.submit(task) for task in export_tasks]:
            future.result()
    height_meta = rasters.save_height_png16(dsm, job_dir / "height.png", job_dir / "height_meta.json")
    for name, array in (("height.f32", dsm), ("ndsm.f32", ndsm), ("uncertainty.f32", uncertainty_m)):
        np.nan_to_num(array, nan=float(np.nanmin(array)) if np.isfinite(array).any() else 0.0).astype("<f4").tofile(job_dir / name)
        outputs[name.replace(".", "_")] = _url(job_id, name)
    if dsm_kind == "relative":
        rasters.save_rdsm_png16(rel_height, job_dir / "rdsm.png", geo)
        outputs["rdsm_png"] = _url(job_id, "rdsm.png")
    elif dsm_kind == "pseudo_metric":
        rasters.save_rdsm_png16(rel_height, job_dir / "rdsm.png", geo)
        outputs["rdsm_png"] = _url(job_id, "rdsm.png")
    for key, name in (("dsm_tif", "dsm.tif"), ("ndsm_tif", "ndsm.tif"), ("uncertainty_tif", "uncertainty.tif"),
                      ("slope_tif", "slope.tif"), ("aspect_tif", "aspect.tif"), ("hillshade_png", "hillshade.png"),
                      ("height_color_png", "height_color.png"), ("slope_color_png", "slope_color.png"),
                      ("uncertainty_color_png", "uncertainty_color.png"), ("landcover_png", "landcover.png"),
                      ("dsm_preview_png", "dsm_preview.png"), ("height_png", "height.png"),
                      ("height_meta_json", "height_meta.json")):
        outputs[key] = _url(job_id, name)

    # Uncompressed: deflating ~2 GB of float rasters took minutes, and the same data is already stored
    # alongside as .f32/COG files, so disk size is not the constraint here.
    np.savez(
        job_dir / "arrays.npz", dsm=dsm.astype(np.float32), ndsm=ndsm.astype(np.float32), labels=land.labels,
        building_labels=segmentation.labels.astype(np.int32), slope=slope.astype(np.float32),
        uncertainty=uncertainty_m.astype(np.float32),
    )

    sun = {"azimuth": shadow_analysis.azimuth_deg, "elevation": sun_el}
    scene_json = {
        "projectId": job_id,
        "mode": "absolute" if dsm_kind == "absolute_dsm" else "relative",
        "kind": dsm_kind,
        "crs": geo.crs if geo else None,
        "sun": sun,
        "texture": "ortho.jpg",
        **scene_geometry,
        "overlays": {
            "optical": "ortho.jpg", "height": "height_color.png", "hillshade": "hillshade.png", "slope": "slope_color.png",
            "uncertainty": "uncertainty_color.png", "landcover": "landcover.png", "error": None, "flood": None,
        },
    }
    (job_dir / "scene.json").write_text(json.dumps(scene_json), encoding="utf-8")
    outputs["scene_json"] = _url(job_id, "scene.json")
    rep.done("export", "COG DSM/nDSM/uncertainty/slope/aspect, GLB, OBJ, hillshade and previews written")

    unity_scene = export_unity_bundle(
        out_dir=job_dir, job_id=job_id, dsm_height=dsm, rgb_image=rgb, geo=geo, dsm_is_metric=dsm_is_metric,
        buildings=buildings_payload["buildings"], zones=zones_payload["zones"], assumed_gsd_m=settings.assumed_gsd_m,
        objects=objects_payload["objects"], ndsm=ndsm, terrain=(dsm - ndsm).astype(np.float32), labels=land.labels,
    )
    for key, filename in (("unity_scene_json", "unity_scene.json"), ("unity_heightmap_r16", "heightmap.r16"), ("unity_texture_jpg", "texture.jpg")):
        outputs[key] = _url(job_id, filename)

    # ---------------- metadata ----------------
    finite_dsm = dsm[np.isfinite(dsm)]
    total_s = time.time() - started_at
    timings["total_s"] = total_s
    metadata = {
        "job_id": job_id,
        "source_filename": job.source_filename,
        "is_georeferenced": descriptor.is_georeferenced,
        "mode": job.mode,
        "dsm_kind": dsm_kind,
        "crs": geo.crs if geo else None,
        "geo": ({"crs": geo.crs, "transform": list(geo.transform), "width": geo.width, "height": geo.height,
                 "bounds": list(geo.bounds), "resolution": list(geo.resolution)} if geo else None),
        "bounds_wgs84": list(descriptor.bounds_wgs84) if descriptor.bounds_wgs84 else None,
        "width": width_px, "height": height_px,
        "band_count": descriptor.band_count, "bit_depth": descriptor.bit_depth, "file_format": descriptor.file_format,
        "gsd_m": descriptor.gsd_m, "pixel_size_m": px_for_analysis, "gsd_assumed": gsd_assumed,
        "sun_azimuth_deg": sun["azimuth"], "sun_elevation_deg": sun_el, "sun_azimuth_source": shadow_analysis.azimuth_source,
        "da_v2_encoder": settings.depth_anything_v2_encoder,
        "da_v2_checkpoint": settings.da_v2_checkpoint_path.name,
        "da_v2_stats": _stats(stack.da.mean),
        "depth_pro_stats": _stats(stack.depth_pro_metric_depth) if stack.depth_pro_metric_depth is not None else {"min": 0.0, "max": 0.0, "mean": 0.0},
        "depth_pro_used": stack.depth_pro_metric_depth is not None,
        "depth_pro_skipped_reason": stack.depth_pro_skipped_reason,
        "depth_pro_focallength_px": stack.depth_pro_focallength_px or 0.0,
        "tiles": stack.da.tile_count, "tta_variants": stack.da.tta_variants, "tile_size": options.tile_size, "overlap": options.overlap,
        "fusion_method": (
            "Height field from the GAMUS fine-tuned DA V2 (tiled, D4-TTA mean, ground = 1st percentile, empirical metre scale); "
            "uncertainty from TTA spread; Depth Pro is reference-only."
        ),
        "depth_pro_enabled": stack.depth_pro_metric_depth is not None,
        "height_scale_applied": height_scale,
        "objects_count": len(objects_payload["objects"]),
        "objects_counts_by_class": objects_payload["counts_by_class"],
        "objects_status": objects_payload["status"],
        "objects_model": objects_payload["model"],
        "confidence_available": True,
        "calibration_status": "calibrated" if outcome.is_metric else ("not_applicable" if geo is None else "unavailable"),
        "calibration_note": " | ".join([dem_note] + outcome.notes),
        "calibration_scale": scale_m,
        "calibration_sources": [{"name": s.name, "scale": s.scale, "weight": s.weight, "detail": s.detail} for s in outcome.sources],
        "calibration_scale_log_sigma": outcome.scale_log_sigma,
        "ground_residual_rmse_m": outcome.ground_residual_rmse_m,
        "gcp_residuals": outcome.gcp_residuals,
        "shadow_summary": shadow_summary,
        "shadow_agreement": shadow_agreement,
        "shadow_measured": shadow_analysis.measured_count,
        "dsm_is_metric": dsm_is_metric,
        "mesh_status": "ready",
        "mesh_vertex_count": legacy_mesh.vertex_count, "mesh_triangle_count": legacy_mesh.triangle_count,
        "mesh_hires_triangle_count": export_stats["triangles"],
        "mesh_source_dsm": "dsm.tif", "mesh_source_image": job.source_filename,
        "mesh_grid_rows": legacy_mesh.grid_rows, "mesh_grid_cols": legacy_mesh.grid_cols,
        "mesh_downsample_factor": legacy_mesh.downsample_factor,
        "mesh_elevation_min": legacy_mesh.elevation_min, "mesh_elevation_max": legacy_mesh.elevation_max,
        "mesh_texture_width": legacy_mesh.texture_width, "mesh_texture_height": legacy_mesh.texture_height,
        "mesh_horizontal_spacing_x": legacy_mesh.horizontal_spacing_x, "mesh_horizontal_spacing_z": legacy_mesh.horizontal_spacing_z,
        "mesh_vertical_exaggeration": legacy_mesh.vertical_exaggeration,
        "unity_horizontal_scale_source": unity_scene["horizontal_scale_source"], "unity_world_size_m": unity_scene["world_size_m"],
        "mesh_spacing_units": legacy_mesh.spacing_units,
        "mesh_chunks": len(scene_geometry["chunks"]), "mesh_lod0_triangles": lod0,
        "buildings_count": buildings_payload["count"],
        "disaster_zones_count": zones_payload["count"],
        "validation_status": validation_result["status"],
        "height_range": [float(finite_dsm.min()), float(finite_dsm.max())] if finite_dsm.size else [0.0, 0.0],
        "mean_height": float(np.nanmean(ndsm)) if np.isfinite(ndsm).any() else None,
        "height_unit": "m" if dsm_is_metric else "relative",
        "land_cover_fractions": land.fractions(),
        "land_cover_counts": land.counts,
        "timings": timings,
        "pixels_per_second": float(height_px * width_px / max(timings["inference_s"], 1e-6)),
        "started_at": started_at, "completed_at": time.time(),
        "options": options.model_dump(),
    }
    (job_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    outputs["metadata_json"] = _url(job_id, "metadata.json")

    job.summary = {
        "mode": job.mode, "kind": dsm_kind, "buildings": buildings_payload["count"], "seconds": round(total_s, 1),
        "max_height": metadata["height_range"][1] - metadata["height_range"][0] if finite_dsm.size else None,
        "width": width_px, "height": height_px,
    }
    job.stage = JobStage.READY
    job.error = None
    rep.log(f"Pipeline complete in {total_s:.1f}s", step="export")
    store.update(job)
    logger.info("Pipeline completed for job %s in %.1fs", job_id, total_s)


def _calibration_summary(outcome: CalibrationOutcome, prefix: str = "") -> str:
    if outcome.kind == "relative" or outcome.scale is None:
        return prefix + "no scale evidence: relative DSM"
    names = "+".join(s.name for s in outcome.sources)
    sigma = f", sigma(log s)={outcome.scale_log_sigma:.2f}" if outcome.scale_log_sigma is not None else ""
    return f"{prefix}{outcome.kind}: s={outcome.scale:.3f} from {names}{sigma}"
