"""Advanced situation-brief PDF: KPI cover, linked contents + bookmarks, charts and data tables.

Everything is computed from the job's own persisted artifacts (arrays.npz, metadata.json,
buildings.json, validation_lab.json, findings.json) through the same hazard functions the app
screens use, so the PDF can never say something the rest of the app doesn't. Sections whose data is
missing (no validation reference, no DEM for flood, ...) are skipped or explain why, never invented.

"Interactive" here means what a PDF can honestly do: a clickable contents page, a bookmark outline
in the reader's sidebar, per-page header links, and "open in app" links back to the live scene.
"""

from __future__ import annotations

import html
import json
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Optional

import matplotlib
import numpy as np
from matplotlib.figure import Figure
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

from app.analysis import hazards
from app.analysis.scene import Scene, load_scene
from app.core.logging import get_logger
from app.landcover.classify import CLASS_COLORS, CLASS_NAMES

matplotlib.use("Agg")
logger = get_logger(__name__)

NIGHT = "#0B2545"
ICE = "#1F5F8B"
MUTED = "#5C7188"
LINE = "#A9CDE6"
ORANGE = "#F26B21"
GREEN = "#5F8A45"
RED = "#A3392C"
PAGE_W = A4[0] - 36 * mm  # usable width between the margins


# ------------------------------------------------------------------ small helpers

def _num(value: Any, digits: int = 2, unit: str = "") -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "n/a"
    return f"{value:,.{digits}f}{unit}"


def _markup(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    return re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"<i>\1</i>", escaped)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _chart(draw: Callable[[Figure], None], width_mm: float = 170, height_mm: float = 68) -> Image:
    """Render a matplotlib figure (no pyplot, so it is thread-safe) to a crisp PNG flowable."""
    fig = Figure(figsize=(width_mm / 25.4, height_mm / 25.4), dpi=200, facecolor="white")
    draw(fig)
    buffer = BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight", pad_inches=0.05)
    buffer.seek(0)
    return Image(buffer, width=width_mm * mm, height=height_mm * mm, kind="proportional")


def _style_axes(ax, xlabel: str = "", ylabel: str = "") -> None:
    ax.set_xlabel(xlabel, fontsize=7.5, color=MUTED)
    ax.set_ylabel(ylabel, fontsize=7.5, color=MUTED)
    ax.tick_params(labelsize=7, colors=MUTED, length=2.5)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(LINE)
    ax.grid(axis="y", color="#E6EEF5", linewidth=0.6)
    ax.set_axisbelow(True)


class Heading(Paragraph):
    """A heading that registers itself in the contents page and the PDF bookmark outline."""

    def __init__(self, text: str, style: ParagraphStyle, level: int, key: str):
        super().__init__(text, style)
        self.level, self.key, self.plain = level, key, re.sub(r"<[^>]+>", "", text)


class BriefDoc(SimpleDocTemplate):
    def afterFlowable(self, flowable) -> None:  # noqa: N802 - reportlab hook name
        if isinstance(flowable, Heading):
            self.canv.bookmarkPage(flowable.key)
            self.canv.addOutlineEntry(flowable.plain, flowable.key, flowable.level, closed=0)
            self.notify("TOCEntry", (flowable.level, flowable.plain, self.page, flowable.key))


# ------------------------------------------------------------------ the report

class _Builder:
    def __init__(self, job_id: str, job_dir: Path, brief: dict, meta: dict, app_url: Optional[str]):
        self.job_id, self.dir, self.brief, self.meta = job_id, job_dir, brief, meta
        self.app = (app_url or "").rstrip("/") or None
        self.scene: Optional[Scene] = None
        try:
            self.scene = load_scene(job_dir)
        except FileNotFoundError:
            logger.info("PDF for %s built without analysis arrays", job_id)
        self.validation = _read_json(job_dir / "validation_lab.json")
        self.buildings = (_read_json(job_dir / "buildings.json") or {}).get("buildings", [])
        self.findings = _read_json(job_dir / "findings.json") or []
        self._section = 0
        self.flood_sweep: Optional[list[dict]] = None

        styles = getSampleStyleSheet()
        self.s_title = ParagraphStyle("title", parent=styles["Title"], textColor=colors.white, fontSize=26, leading=30, alignment=0)
        self.s_sub = ParagraphStyle("sub", parent=styles["BodyText"], textColor=colors.HexColor("#CFE3F2"), fontSize=10.5, leading=14)
        self.s_h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=colors.HexColor(NIGHT), fontSize=16, spaceBefore=4, spaceAfter=6, keepWithNext=1)
        self.s_h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=colors.HexColor(ICE), fontSize=11.5, spaceBefore=10, spaceAfter=3, keepWithNext=1)
        self.s_body = ParagraphStyle("body", parent=styles["BodyText"], textColor=colors.HexColor(NIGHT), fontSize=9.4, leading=13.2)
        self.s_small = ParagraphStyle("small", parent=self.s_body, fontSize=7.8, leading=10.5, textColor=colors.HexColor(MUTED))
        self.s_cap = ParagraphStyle("cap", parent=self.s_small, alignment=TA_CENTER, spaceBefore=1, spaceAfter=8)
        self.s_kpi_n = ParagraphStyle("kpin", parent=self.s_body, fontSize=17, leading=20, textColor=colors.HexColor(NIGHT), fontName="Helvetica-Bold")
        self.s_kpi_l = ParagraphStyle("kpil", parent=self.s_small, fontSize=7.6, textColor=colors.HexColor(MUTED))
        self.s_cell = ParagraphStyle("cell", parent=self.s_body, fontSize=8.2, leading=10.5)

    # ---- structure helpers
    def h1(self, text: str) -> Heading:
        self._section += 1
        return Heading(f"{self._section}. {html.escape(text)}", self.s_h1, 0, f"sec{self._section}")

    def link(self, label: str, path: str) -> Optional[Paragraph]:
        if not self.app:
            return None
        url = f"{self.app}/survey/{self.job_id}{path}"
        return Paragraph(f'<link href="{url}" color="{ICE}"><u>{html.escape(label)}</u></link>', self.s_small)

    def table(self, rows: list[list[Any]], widths: list[float], header: bool = True, zebra: bool = True) -> Table:
        th = ParagraphStyle("th", parent=self.s_cell, textColor=colors.white, fontName="Helvetica-Bold")
        data = [[c if not isinstance(c, str) else Paragraph(_markup(c), th if header and r == 0 else self.s_cell) for c in row]
                for r, row in enumerate(rows)]
        table = Table(data, colWidths=widths, repeatRows=1 if header else 0)
        style = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor(LINE)),
                 ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        if header:
            style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NIGHT)), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
        if zebra:
            style += [("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [colors.white, colors.HexColor("#F3F8FC")])]
        table.setStyle(TableStyle(style))
        return table

    def figure(self, image: Image, caption: str) -> KeepTogether:
        return KeepTogether([image, Paragraph(html.escape(caption), self.s_cap)])

    # ---- cover
    def cover(self) -> list:
        scene, meta = self.scene, self.meta
        unit = "m" if meta.get("dsm_is_metric") else " rel"
        story: list = [Spacer(1, 52 * mm)]  # the dark band is drawn by the page callback behind this
        story.append(Paragraph("AakashDrishti", self.s_title))
        story.append(Paragraph("Situation brief and terrain analytics", self.s_sub))
        story.append(Paragraph(f"{html.escape(str(meta.get('source_filename', self.job_id)))} &nbsp;|&nbsp; "
                               f"{html.escape(str(meta.get('dsm_kind', 'scene')).replace('_', ' '))} &nbsp;|&nbsp; job {self.job_id[:8]}", self.s_sub))
        story.append(Spacer(1, 26 * mm))

        tiles: list[tuple[str, str]] = []
        if scene is not None:
            area = scene.shape[0] * scene.shape[1] * scene.px_m ** 2 / 1e6
            tiles += [(_num(area, 3, " km²"), "Scene area"), (str(len(np.unique(scene.building_labels[scene.building_labels > 0]))), "Buildings detected"),
                      (_num(float(np.nanpercentile(scene.ndsm, 95)), 1, unit), "Height above ground (p95)"),
                      (_num(scene.px_m, 2, " m/px"), "Ground resolution"),
                      (_num(float(np.nanmean(scene.uncertainty_m)), 2, unit), "Mean modelled uncertainty"),
                      (_num(float(np.nanmax(scene.slope)), 1, "°"), "Maximum slope")]
        if self.validation and self.validation.get("global"):
            tiles.append((_num(self.validation["global"].get("rmse"), 2, " m"), "Validation RMSE"))
        else:
            tiles.append((str(meta.get("calibration_status", "n/a")).title(), "Scale calibration"))
        tiles.append((self._flood_headline(), "Buildings in flood zone"))
        rows = []
        for i in range(0, len(tiles), 4):
            chunk = tiles[i:i + 4]
            rows.append([[Paragraph(n, self.s_kpi_n), Paragraph(label, self.s_kpi_l)] for n, label in chunk])
        table = Table(rows, colWidths=[PAGE_W / 4] * 4, rowHeights=[22 * mm] * len(rows))
        table.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(LINE)), ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor(LINE)),
                                   ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F8FC")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 9)]))
        story += [table, Spacer(1, 8)]
        mode = "AI analyst (online)" if self.brief.get("mode") == "online" else "offline template analyst"
        story.append(Paragraph(f"Narrative written by the {mode} from computed scene statistics. Single-view vertical error is metre-scale; "
                               "surface strength is not assessed. Decision support only, not a survey or an aviation clearance.", self.s_small))
        story.append(PageBreak())

        story.append(Paragraph("Contents", self.s_h1))
        toc = TableOfContents()
        toc.levelStyles = [ParagraphStyle("toc0", parent=self.s_body, fontSize=10.5, leading=17, leftIndent=0, textColor=colors.HexColor(NIGHT))]
        story += [toc, Spacer(1, 6),
                  Paragraph("Click an entry to jump to it. The bookmark panel of your PDF reader lists the same sections.", self.s_small)]
        if self.app:
            story += [Spacer(1, 10), Paragraph("Open this scene in the live app", self.s_h2)]
            links = [self.link(label, path) for label, path in
                     (("Workspace (3D view)", ""), ("Hazards and scenarios", "/hazards"), ("Validation lab", "/validate"),
                      ("AI brief", "/brief"), ("Downloads", "/downloads"))]
            story.append(Table([[l for l in links if l]], colWidths=[PAGE_W / 5] * len([l for l in links if l])))
        story.append(PageBreak())
        return story

    def _flood_headline(self) -> str:
        sweep = self._sweep()
        if not sweep:
            return "n/a"
        return f"{sweep[len(sweep) // 2]['buildings']} of {sweep[0]['total']}"

    def _sweep(self) -> list[dict]:
        """Flood simulated at evenly spaced water levels (cached): the data behind the flood chart."""
        if self.flood_sweep is not None:
            return self.flood_sweep
        self.flood_sweep = []
        scene = self.scene
        if scene is None or not hazards.has_bare_earth_terrain(scene):
            return self.flood_sweep
        lo, hi = hazards.flood_level_range(scene)
        for level in np.linspace(max(lo, hi * 0.05), hi * 0.9, 9):
            try:
                r = hazards.simulate_flood(scene, float(level))
            except Exception:  # noqa: BLE001 - one bad level must not drop the whole report
                logger.exception("flood sweep level %s failed", level)
                continue
            self.flood_sweep.append({"level": float(level), "area_pct": float(r["area_fraction"]) * 100, "buildings": int(r["affected_buildings"]),
                                     "total": int(r["total_buildings"]), "volume": r.get("volume_m3"), "worst": r.get("worst_hit_areas", [])})
        return self.flood_sweep

    # ---- sections
    def narrative(self) -> list:
        story = [self.h1("Situation report and response plan")]
        for line in self.brief["text"].split("\n"):
            if line.startswith("## "):
                story.append(Paragraph(_markup(line[3:]), self.s_h2))
            elif line.strip():
                stripped = line.strip()
                bullet = stripped.startswith(("- ", "* "))
                story.append(Paragraph(_markup(stripped[2:] if bullet else stripped), self.s_body,
                                       bulletText="•" if bullet else None))
        story.append(Spacer(1, 4))
        if self.brief.get("unverified_numbers"):
            story.append(Paragraph("Numbers in the AI text that could not be matched to computed statistics: "
                                   + html.escape(", ".join(self.brief["unverified_numbers"])), self.s_small))
        if (link := self.link("Regenerate or edit this brief in the app", "/brief")):
            story.append(link)
        return story

    def scene_overview(self) -> list:
        m = self.meta
        story = [self.h1("Scene overview")]
        sources = ", ".join(s.get("name", "?") for s in m.get("calibration_sources", [])) or "none (relative scale)"
        facts = [["Property", "Value"],
                 ["Image", f"{m.get('width')} × {m.get('height')} px, {m.get('file_format', 'n/a')}"],
                 ["Georeferenced", f"yes, {m.get('crs')}" if m.get("is_georeferenced") else "no"],
                 ["Height model", f"{m.get('da_v2_encoder', 'n/a')}, {m.get('tta_variants', 'n/a')} TTA variants, {m.get('tiles', 'n/a')} tiles"],
                 ["Scale calibration", f"{m.get('calibration_status', 'n/a')}; sources: {sources}"],
                 ["Calibration note", html.escape(str(m.get("calibration_note", "")))[:300] or "n/a"],
                 ["Sun (shadow geometry)", f"azimuth {_num(m.get('sun_azimuth_deg'), 1, '°')}, elevation {_num(m.get('sun_elevation_deg'), 1, '°')} ({m.get('sun_azimuth_source', 'n/a')})"],
                 ["Processing time", f"{_num((m.get('timings') or {}).get('total_s'), 1, ' s')} total, {_num((m.get('timings') or {}).get('inference_s'), 1, ' s')} inference"]]
        story.append(self.table(facts, [42 * mm, PAGE_W - 42 * mm]))
        story.append(Spacer(1, 8))

        previews = [(self.dir / n, cap) for n, cap in (("ortho.jpg", "Optical image"), ("height_color.png", "Estimated height"),
                                                       ("landcover.png", "Land cover"), ("hillshade.png", "Hillshade"))
                    if (self.dir / n).is_file()]
        if previews:
            size = (PAGE_W - 6 * mm) / 2
            cells = [[Image(str(p), width=size, height=size * 0.78, kind="proportional"), Paragraph(cap, self.s_cap)] for p, cap in previews]
            grid = [cells[i][:1] + cells[i + 1][:1] if i + 1 < len(cells) else cells[i][:1] for i in range(0, len(cells), 2)]
            caps = [[cells[i][1], cells[i + 1][1]] if i + 1 < len(cells) else [cells[i][1]] for i in range(0, len(cells), 2)]
            for pics, labels in zip(grid, caps):
                t = Table([pics, labels], colWidths=[size + 3 * mm] * len(pics))
                t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
                story.append(t)
        if (link := self.link("Explore the interactive 3D scene", "")):
            story.append(link)
        return story

    def height_analytics(self) -> list:
        scene = self.scene
        if scene is None:
            return []
        unit = "m" if scene.is_metric else "relative units"
        story = [self.h1("Height and terrain analytics")]

        def heights(fig: Figure) -> None:
            ax = fig.add_subplot(111)
            values = scene.ndsm[np.isfinite(scene.ndsm)].ravel()
            values = values[:: max(1, values.size // 400_000)]
            ax.hist(values, bins=60, color=ICE, alpha=0.9)
            ax.set_yscale("log")
            for q, color in ((50, GREEN), (95, ORANGE)):
                v = float(np.percentile(values, q))
                ax.axvline(v, color=color, linewidth=1.2)
                ax.text(v, ax.get_ylim()[1], f" p{q} = {v:.1f}", fontsize=7, color=color, va="top")
            _style_axes(ax, f"height above ground ({unit})", "pixels (log)")

        story.append(self.figure(_chart(heights), "Distribution of height above local ground across the whole scene."))

        def landcover(fig: Figure) -> None:
            ax = fig.add_subplot(111)
            counts = np.bincount(scene.labels.ravel(), minlength=len(CLASS_NAMES)) * scene.px_m ** 2 / 1e6
            order = np.argsort(counts)
            ax.barh([CLASS_NAMES[i].replace("_", " ") for i in order], counts[order],
                    color=[tuple(c / 255 for c in CLASS_COLORS[i]) for i in order])
            total = counts.sum() or 1
            for y, i in enumerate(order):
                ax.text(counts[i], y, f"  {counts[i]:.3f} km² ({counts[i] / total * 100:.0f}%)", va="center", fontsize=7, color=NIGHT)
            ax.set_xlim(0, counts.max() * 1.35)
            _style_axes(ax, "area (km²)")
            ax.grid(axis="x", color="#E6EEF5", linewidth=0.6)

        story.append(self.figure(_chart(landcover, height_mm=58), "Land-cover composition (colour and height heuristics: indicative, not surveyed)."))

        slope = scene.slope[np.isfinite(scene.slope)]
        thresholds = {t: hazards.slope_hazard(scene, float(t))["area_km2"] for t in (15, 30, 45)}

        def slopes(fig: Figure) -> None:
            ax = fig.add_subplot(111)
            ax.hist(slope[:: max(1, slope.size // 400_000)], bins=60, color=GREEN, alpha=0.9)
            ax.set_yscale("log")
            for t, color in ((15, ORANGE), (30, RED), (45, NIGHT)):
                ax.axvline(t, color=color, linewidth=1.1, linestyle="--")
                ax.text(t, ax.get_ylim()[1], f" >{t}°: {thresholds[t]:.4f} km²", fontsize=6.8, color=color, va="top", rotation=90)
            _style_axes(ax, "slope (degrees)", "pixels (log)")

        story.append(self.figure(_chart(slopes), "Slope distribution with the area above the 15°, 30° and 45° hazard thresholds."))

        def uncertainty(fig: Figure) -> None:
            ax = fig.add_subplot(111)
            u = scene.uncertainty_m[np.isfinite(scene.uncertainty_m)]
            ax.hist(u[:: max(1, u.size // 400_000)], bins=60, color=ORANGE, alpha=0.9)
            mean = float(np.mean(u))
            ax.axvline(mean, color=NIGHT, linewidth=1.2)
            ax.text(mean, ax.get_ylim()[1], f" mean {mean:.2f}", fontsize=7, color=NIGHT, va="top")
            _style_axes(ax, f"modelled height uncertainty ({unit})", "pixels")

        story.append(self.figure(_chart(uncertainty, height_mm=55), "Per-pixel uncertainty from test-time-augmentation spread (not a measured error)."))
        return story

    def building_section(self) -> list:
        usable = [b for b in self.buildings if b.get("height_m") is not None]
        if not usable:
            return []
        unit = "m" if self.meta.get("dsm_is_metric") else "rel"
        story = [self.h1("Buildings")]
        heights = np.array([b["height_m"] for b in usable], dtype=float)
        conf = np.array([b.get("confidence") or 0.0 for b in usable], dtype=float)
        story.append(Paragraph(f"{len(usable)} building footprints with a height estimate. Median {np.median(heights):.1f} {unit}, "
                               f"90th percentile {np.percentile(heights, 90):.1f} {unit}, tallest {heights.max():.1f} {unit}.", self.s_body))

        def draw(fig: Figure) -> None:
            ax1, ax2 = fig.subplots(1, 2)
            ax1.hist(heights, bins=24, color=ICE, alpha=0.9)
            _style_axes(ax1, f"building height ({unit})", "buildings")
            scatter = ax2.scatter(heights, conf, c=conf, cmap="viridis", s=14, edgecolors="none")
            ax2.set_ylim(0, 1)
            _style_axes(ax2, f"height ({unit})", "confidence")
            fig.colorbar(scatter, ax=ax2, fraction=0.04, pad=0.02).ax.tick_params(labelsize=6)
            fig.tight_layout()

        story.append(self.figure(_chart(draw, height_mm=62), "Height distribution (left) and per-building confidence against height (right)."))
        top = sorted(usable, key=lambda b: b["height_m"], reverse=True)[:10]
        rows = [["ID", f"Height ({unit})", "Footprint (px)", "Confidence", "Shadow check"]]
        for b in top:
            rows.append([str(b["id"]), _num(b["height_m"], 1), f"{b.get('area_px', 0):,}", _num(b.get("confidence"), 2),
                         _num(b.get("shadow_estimate_m"), 1) if b.get("shadow_estimate_m") is not None else "-"])
        story += [Paragraph("Ten tallest detected buildings", self.s_h2), self.table(rows, [20 * mm, 32 * mm, 38 * mm, 32 * mm, PAGE_W - 122 * mm])]
        return story

    def flood_section(self) -> list:
        sweep = self._sweep()
        story = [self.h1("Flood exposure")]
        if not sweep:
            story.append(Paragraph(html.escape(hazards.NO_TERRAIN_NOTE), self.s_body))
            return story
        unit = "m" if self.scene.is_metric else "rel"
        total = sweep[0]["total"]

        def draw(fig: Figure) -> None:
            ax = fig.add_subplot(111)
            levels = [s["level"] for s in sweep]
            ax.plot(levels, [s["area_pct"] for s in sweep], color=ICE, marker="o", markersize=3.5, linewidth=1.6, label="area inundated (%)")
            ax2 = ax.twinx()
            ax2.plot(levels, [s["buildings"] for s in sweep], color=RED, marker="s", markersize=3.5, linewidth=1.6, label="buildings affected")
            ax2.set_ylim(0, max(total, 1))
            ax2.set_ylabel(f"buildings affected (of {total})", fontsize=7.5, color=RED)
            ax2.tick_params(labelsize=7, colors=RED, length=2.5)
            ax2.spines["top"].set_visible(False)
            _style_axes(ax, f"water level above reference ({unit})", "area inundated (%)")
            ax.set_ylim(0, 100)
            handles = ax.get_lines() + ax2.get_lines()
            ax.legend(handles, [h.get_label() for h in handles], fontsize=7, frameon=False, loc="upper left")

        story.append(self.figure(_chart(draw, height_mm=66), "Flood response curve: the scene flooded at nine water levels (hydraulically connected to the lowest edge or water body)."))
        rows = [["Water level", "Area inundated", "Buildings affected", "Volume"]]
        for s in sweep:
            rows.append([f"{s['level']:.1f} {unit}", f"{s['area_pct']:.1f}%", f"{s['buildings']} of {s['total']}",
                         _num(s["volume"], 0, " m³") if s["volume"] is not None else "n/a"])
        story.append(self.table(rows, [35 * mm, 38 * mm, 45 * mm, PAGE_W - 118 * mm]))
        worst = sweep[len(sweep) // 2]["worst"][:5]
        if worst:
            story += [Paragraph(f"Worst-hit sectors at {sweep[len(sweep) // 2]['level']:.1f} {unit}", self.s_h2),
                      self.table([["Sector", "Flooded", "Mean depth"]] + [[w["area"], f"{w['flooded_fraction'] * 100:.1f}%", _num(w["mean_depth"], 2, f" {unit}")] for w in worst],
                                 [60 * mm, 40 * mm, PAGE_W - 100 * mm])]
        if (link := self.link("Run the flood slider interactively", "/hazards")):
            story.append(link)
        return story

    def landing_section(self) -> list:
        if self.scene is None:
            return []
        try:
            result = hazards.landing_zones(self.scene, top_n=5)
        except Exception:  # noqa: BLE001
            logger.exception("landing zones failed for PDF")
            return []
        story = [self.h1("Landing and relief-drop sites")]
        sites = result.get("sites", [])
        if not sites:
            story.append(Paragraph("No site met the flat, obstacle-free criteria.", self.s_body))
            return story

        def draw(fig: Figure) -> None:
            ax = fig.add_subplot(111)
            labels = [f"Site {s['rank']}" for s in sites]
            ax.bar(labels, [s["clear_radius_m"] for s in sites], color=GREEN, alpha=0.9)
            ax2 = ax.twinx()
            ax2.plot(labels, [s["mean_slope_deg"] for s in sites], color=RED, marker="o", linewidth=1.4)
            ax2.set_ylabel("mean slope (°)", fontsize=7.5, color=RED)
            ax2.tick_params(labelsize=7, colors=RED, length=2.5)
            ax2.spines["top"].set_visible(False)
            _style_axes(ax, "", "clear radius (m)")

        story.append(self.figure(_chart(draw, height_mm=52), "Candidate sites: clear radius (bars) and mean slope (line). Higher radius and lower slope are better."))
        rows = [["Rank", "Clear radius", "Mean slope", "Nearest road", "Score"]]
        for s in sites:
            rows.append([str(s["rank"]), _num(s.get("clear_radius_m"), 1, " m"), _num(s.get("mean_slope_deg"), 1, "°"),
                         _num(s.get("nearest_road_m"), 0, " m"), _num(s.get("score"), 2)])
        story += [self.table(rows, [20 * mm, 36 * mm, 36 * mm, 40 * mm, PAGE_W - 132 * mm]),
                  Paragraph(html.escape(str(result.get("disclaimer", ""))), self.s_small)]
        return story

    def validation_section(self) -> list:
        v = self.validation
        story = [self.h1("Accuracy validation")]
        if not v or not v.get("global"):
            story.append(Paragraph("No reference elevation data has been scored for this scene, so no accuracy figure is claimed. "
                                   "Add a LiDAR DSM/nDSM in the Validation lab to score RMSE, MAE, bias, NMAD, Pearson r and δ1.", self.s_body))
            if (link := self.link("Open the Validation lab", "/validate")):
                story.append(link)
            return story
        g = v["global"]
        unit = v.get("unit", "m")
        rows = [["Metric", "Value", "Meaning"],
                ["RMSE", _num(g.get("rmse"), 2, f" {unit}"), "Root-mean-square height error"],
                ["MAE", _num(g.get("mae"), 2, f" {unit}"), "Mean absolute error"],
                ["Bias", _num(g.get("bias"), 2, f" {unit}"), "Mean signed error (+ = over-predicts)"],
                ["NMAD", _num(g.get("nmad"), 2, f" {unit}"), "Outlier-robust spread"],
                ["Pearson r", _num(g.get("pearson_r"), 3), "Agreement of shape"],
                ["δ1", _num(g.get("delta1"), 3), "Share of pixels within 25% of reference"],
                ["Pixels scored", f"{g.get('n', 0):,}", "Valid overlap with the reference"]]
        story.append(self.table(rows, [30 * mm, 36 * mm, PAGE_W - 66 * mm]))
        story.append(Spacer(1, 6))

        scatter = np.array(v.get("scatter") or [], dtype=float)
        hist = v.get("error_histogram") or {}

        def draw(fig: Figure) -> None:
            ax1, ax2 = fig.subplots(1, 2)
            if scatter.size:
                ax1.scatter(scatter[:, 0], scatter[:, 1], s=4, color=ICE, alpha=0.35, edgecolors="none")
                lim = [float(np.min(scatter)), float(np.max(scatter))]
                ax1.plot(lim, lim, color=ORANGE, linewidth=1.1, linestyle="--", label="1:1")
                ax1.legend(fontsize=7, frameon=False)
            _style_axes(ax1, f"reference ({unit})", f"predicted ({unit})")
            if hist.get("counts"):
                edges = np.array(hist["edges"])
                ax2.bar((edges[:-1] + edges[1:]) / 2, hist["counts"], width=np.diff(edges), color=ORANGE, alpha=0.9)
                ax2.axvline(0, color=NIGHT, linewidth=1)
            _style_axes(ax2, f"error, predicted - reference ({unit})", "pixels")
            fig.tight_layout()

        story.append(self.figure(_chart(draw, height_mm=64), "Predicted against reference height (left) and the error distribution (right)."))

        groups = {**{f"class: {k}": m for k, m in (v.get("per_class") or {}).items()},
                  **{f"landscape: {k}": m for k, m in (v.get("per_landscape") or {}).items()}}
        groups = {k: m for k, m in groups.items() if m.get("rmse") is not None}
        if groups:
            def bars(fig: Figure) -> None:
                ax = fig.add_subplot(111)
                names = list(groups)
                ax.barh(names, [groups[n]["rmse"] for n in names], color=[ICE if n.startswith("class") else GREEN for n in names])
                for y, n in enumerate(names):
                    ax.text(groups[n]["rmse"], y, f"  {groups[n]['rmse']:.2f}", va="center", fontsize=7, color=NIGHT)
                ax.invert_yaxis()
                _style_axes(ax, f"RMSE ({unit})")
                ax.grid(axis="x", color="#E6EEF5", linewidth=0.6)

            story.append(self.figure(_chart(bars, height_mm=max(45, 8 * len(groups) + 20)), "RMSE per land-cover class (blue) and per landscape type (green)."))
        for caveat in v.get("caveats", []):
            story.append(Paragraph("• " + html.escape(caveat), self.s_small))
        if (link := self.link("Explore the live error map", "/validate")):
            story.append(link)
        return story

    def findings_section(self) -> list:
        if not self.findings:
            return []
        story = [self.h1("Operator findings")]
        rows = [["Tool", "Finding"]] + [[str(f.get("tool", "")), str(f.get("text", ""))] for f in self.findings[-15:]]
        story.append(self.table(rows, [28 * mm, PAGE_W - 28 * mm]))
        return story

    def method_section(self) -> list:
        return [self.h1("Method and limitations"),
                Paragraph("Heights come from a single optical image: a fine-tuned monocular depth model (with test-time augmentation and tiling) "
                          "produces a height field, which is scaled to metres from shadow geometry, ground control points and/or a reference DEM "
                          "(see Scene overview for the sources used on this scene).", self.s_body),
                Paragraph("Limitations: vertical error is metre-scale and larger over dense vegetation and very tall structures; land cover, "
                          "building footprints and hazard zones are heuristic; flood assumes water spreads only to connected low ground; surface strength "
                          "(mud, tarmac, load-bearing) is not assessed; landing sites are candidates for a pilot to confirm. This report is decision "
                          "support and not a certified survey.", self.s_body)]

    # ---- assembly
    def build(self) -> bytes:
        story = self.cover()
        for section in (self.narrative, self.scene_overview, self.height_analytics, self.building_section, self.flood_section,
                        self.landing_section, self.validation_section, self.findings_section, self.method_section):
            try:
                part = section()
            except Exception:  # noqa: BLE001 - a failing section is dropped, the rest of the PDF still ships
                logger.exception("PDF section %s failed for job %s", section.__name__, self.job_id)
                self._section = max(0, self._section - 1)
                continue
            if part:
                story += part + [Spacer(1, 10)]

        title = str(self.meta.get("source_filename", self.job_id))
        app_url = f"{self.app}/survey/{self.job_id}" if self.app else None

        def cover_page(canvas, doc) -> None:
            canvas.saveState()
            canvas.setFillColor(colors.HexColor(NIGHT))
            canvas.rect(0, A4[1] - 118 * mm, A4[0], 118 * mm, stroke=0, fill=1)
            canvas.setFillColor(colors.HexColor(ORANGE))
            canvas.rect(0, A4[1] - 120 * mm, A4[0], 2 * mm, stroke=0, fill=1)
            canvas.restoreState()

        def body_page(canvas, doc) -> None:
            canvas.saveState()
            canvas.setFont("Helvetica", 7.5)
            canvas.setFillColor(colors.HexColor(MUTED))
            canvas.drawString(18 * mm, A4[1] - 10 * mm, f"AakashDrishti situation brief  |  {title}"[:90])
            canvas.drawRightString(A4[0] - 18 * mm, 9 * mm, f"Page {doc.page}")
            canvas.drawString(18 * mm, 9 * mm, "Decision support, not a certified survey")
            canvas.setStrokeColor(colors.HexColor(LINE))
            canvas.line(18 * mm, A4[1] - 12 * mm, A4[0] - 18 * mm, A4[1] - 12 * mm)
            if app_url:
                canvas.setFillColor(colors.HexColor(ICE))
                label = "Open in app"
                canvas.drawRightString(A4[0] - 18 * mm, A4[1] - 10 * mm, label)
                canvas.linkURL(app_url, (A4[0] - 18 * mm - canvas.stringWidth(label, "Helvetica", 7.5), A4[1] - 11 * mm, A4[0] - 18 * mm, A4[1] - 7 * mm))
            canvas.restoreState()

        buffer = BytesIO()
        doc = BriefDoc(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=16 * mm,
                       title=f"AakashDrishti situation brief - {title}", author="AakashDrishti", subject="Terrain and hazard analysis")
        doc.multiBuild(story, onFirstPage=cover_page, onLaterPages=body_page)
        return buffer.getvalue()


def build_brief_pdf(job_id: str, job_dir: Path, brief: dict, meta: dict, app_url: Optional[str] = None) -> bytes:
    return _Builder(job_id, job_dir, brief, meta, app_url).build()
