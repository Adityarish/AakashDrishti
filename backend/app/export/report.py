"""PDF situation-report export for one job (PRD.md P2 "PDF report export").

Uses matplotlib's PdfPages so no new dependency is needed (matplotlib is
already a backend requirement for the depth/DSM preview colormaps). Every
number on the report is read directly from the job's own persisted
artifacts (metadata.json, buildings.json, disaster_zones.json,
validation.json) -- nothing here is computed or estimated fresh, so the
report can never say something the rest of the app doesn't already say.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any, Optional

import matplotlib
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure

matplotlib.use("Agg")


def _title_page(pdf: PdfPages, job_id: str, metadata: dict[str, Any], validation: dict[str, Any]) -> None:
    fig = Figure(figsize=(8.27, 11.69))  # A4 portrait
    ax = fig.add_axes((0.08, 0.05, 0.84, 0.92))
    ax.axis("off")

    lines = [
        ("AakashDrishti -- Situation Report", 20, "bold"),
        (f"Job {job_id}", 11, "normal"),
        ("", 10, "normal"),
        (f"Source image: {metadata.get('source_filename', '-')}", 12, "normal"),
        (f"Image size: {metadata.get('width', '-')} x {metadata.get('height', '-')} px", 12, "normal"),
        (f"Georeferenced: {metadata.get('is_georeferenced', False)}", 12, "normal"),
        (f"CRS: {metadata.get('crs') or 'n/a'}", 12, "normal"),
        ("", 10, "normal"),
        ("Height field", 14, "bold"),
        (f"  Source: {metadata.get('fusion_method', '-')}", 10, "normal"),
        (f"  DSM is metric: {metadata.get('dsm_is_metric', False)}", 12, "normal"),
        (f"  Calibration: {metadata.get('calibration_status', '-')}", 12, "normal"),
        (f"  {metadata.get('calibration_note', '')}", 9, "italic"),
        (f"  Shadow cross-check: {metadata.get('shadow_calibration_status', '-')}", 12, "normal"),
        (f"  {metadata.get('shadow_calibration_note', '')}", 9, "italic"),
        ("", 10, "normal"),
        ("Validation (RMSE/MAE/correlation vs. reference DEM)", 14, "bold"),
        (f"  Status: {validation.get('status', '-')}", 12, "normal"),
    ]
    if validation.get("status") == "calibrated":
        lines.append((f"  RMSE: {validation.get('rmse'):.2f}  MAE: {validation.get('mae'):.2f}  r: {validation.get('correlation'):.3f}", 12, "normal"))
    else:
        lines.append((f"  {validation.get('note', '')}", 9, "italic"))
    lines += [
        ("", 10, "normal"),
        ("Detections", 14, "bold"),
        (f"  Buildings: {metadata.get('buildings_count', 0)}", 12, "normal"),
        (f"  Disaster zones: {metadata.get('disaster_zones_count', 0)}", 12, "normal"),
        (f"  Mesh: {metadata.get('mesh_vertex_count', '-')} vertices, {metadata.get('mesh_triangle_count', '-')} triangles", 12, "normal"),
    ]

    # Pre-wrap long lines ourselves (matplotlib's `wrap=True` reflows text but does not
    # report the extra height back, which made a wrapped line overlap the one below it)
    # and give each wrapped sub-line the same fixed row height as everything else.
    wrapped: list[tuple[str, int, str]] = []
    for text, size, weight in lines:
        chars_per_line = max(20, int(95 * 11 / size))
        for sub in (textwrap.wrap(text, width=chars_per_line) or [""]):
            wrapped.append((sub, size, weight))

    y = 1.0
    for text, size, weight in wrapped:
        style = "italic" if weight == "italic" else "normal"
        fontweight = "bold" if weight == "bold" else "normal"
        ax.text(0.0, y, text, fontsize=size, fontweight=fontweight, fontstyle=style, va="top", transform=ax.transAxes)
        y -= 0.021 * (size / 11.0 + 0.4)

    # Figure-level (not axes-relative), so it's pinned to the physical page bottom
    # regardless of how much content the axes above ends up holding.
    fig.text(
        0.08, 0.015,
        "Heuristic decision-support output -- see the in-app notes on each figure. Not a certified survey.",
        fontsize=8, color="0.4",
    )
    pdf.savefig(fig)


def _preview_page(pdf: PdfPages, title: str, image_path: Path, caption: str) -> None:
    from PIL import Image

    fig = Figure(figsize=(8.27, 11.69))
    ax = fig.add_axes((0.06, 0.10, 0.88, 0.78))
    with Image.open(image_path) as im:
        ax.imshow(np.asarray(im))
    ax.axis("off")
    fig.text(0.5, 0.94, title, fontsize=16, fontweight="bold", ha="center")
    fig.text(0.06, 0.05, caption, fontsize=8, color="0.3", wrap=True)
    pdf.savefig(fig)


def _table_page(pdf: PdfPages, title: str, columns: list[str], rows: list[list[str]], note: str) -> None:
    fig = Figure(figsize=(8.27, 11.69))
    ax = fig.add_axes((0.06, 0.06, 0.88, 0.86))
    ax.axis("off")
    fig.text(0.5, 0.94, title, fontsize=16, fontweight="bold", ha="center")

    if rows:
        table = ax.table(cellText=rows, colLabels=columns, loc="upper center", cellLoc="left")
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        table.scale(1, 1.3)
    else:
        ax.text(0.5, 0.5, "(none)", ha="center", va="center", fontsize=12, transform=ax.transAxes)

    fig.text(0.06, 0.02, note, fontsize=8, color="0.3", wrap=True)
    pdf.savefig(fig)


def generate_pdf_report(
    job_id: str,
    job_dir: Path,
    metadata: dict[str, Any],
    buildings: list[dict[str, Any]],
    zones: list[dict[str, Any]],
    validation: dict[str, Any],
    out_path: Path,
    dsm_preview_path: Optional[Path] = None,
    fused_depth_preview_path: Optional[Path] = None,
) -> None:
    with PdfPages(out_path) as pdf:
        _title_page(pdf, job_id, metadata, validation)

        if dsm_preview_path is not None and dsm_preview_path.is_file():
            _preview_page(
                pdf, "DSM / rDSM (terrain colormap)", dsm_preview_path,
                "Height field: brighter = higher. See the title page for whether this is a metric DSM or a relative rDSM.",
            )
        if fused_depth_preview_path is not None and fused_depth_preview_path.is_file():
            _preview_page(
                pdf, "Height field preview", fused_depth_preview_path,
                "The pipeline's height field before geospatial calibration/shadow cross-check.",
            )

        tallest = sorted(
            (b for b in buildings if b.get("height_m") is not None),
            key=lambda b: b["height_m"],
            reverse=True,
        )[:25]
        _table_page(
            pdf,
            "Tallest detected buildings",
            ["ID", "Height", "Metric?", "Confidence", "Shadow est.", "Depth-shadow delta"],
            [
                [
                    str(b["id"]),
                    f"{b['height_m']:.2f}",
                    "yes" if b.get("is_metric") else "no",
                    f"{b['confidence']:.2f}" if b.get("confidence") is not None else "-",
                    f"{b['shadow_estimate_m']:.2f}" if b.get("shadow_estimate_m") is not None else "-",
                    f"{b['depth_vs_shadow_delta_m']:.2f}" if b.get("depth_vs_shadow_delta_m") is not None else "-",
                ]
                for b in tallest
            ],
            f"Showing up to 25 of {len(buildings)} detected buildings, tallest first. Heuristic footprint "
            "extraction + p90 in-footprint height (app/buildings/segment.py,height.py) -- not a certified survey.",
        )

        zone_counts: dict[tuple[str, str], int] = {}
        for z in zones:
            key = (z.get("type") or "unknown", z.get("risk_level") or "-")
            zone_counts[key] = zone_counts.get(key, 0) + 1
        _table_page(
            pdf,
            "Disaster-zone summary",
            ["Type", "Level", "Count"],
            [[t, lvl, str(n)] for (t, lvl), n in sorted(zone_counts.items())],
            "Heuristic decision-support only (app/buildings/disaster.py) -- flags candidate zones for "
            "operator confirmation, not a certified hazard assessment.",
        )
