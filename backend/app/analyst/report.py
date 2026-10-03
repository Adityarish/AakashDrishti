"""AI analyst: situation report, ranked risk areas and response plan from scene statistics.

Online mode sends only the JSON produced by the read-only tools (never imagery) to an
OpenAI-compatible endpoint and streams the answer; every number in it is checked against the tool
outputs. Offline (no key / no network) a deterministic template writes the same three sections
from the same statistics - clearly labelled, and the rest of the system is unaffected (FR-44).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Iterator, Optional

import httpx

from app.analyst import tools
from app.core.config import Settings

SYSTEM_PROMPT = (
    "You are a disaster-response terrain analyst. You are given JSON statistics derived from a single-view "
    "satellite height model. Write three markdown sections: '## Situation report', '## Ranked risk areas', "
    "'## Response plan' (access routes, relief-camp siting, landing-zone recommendations, evacuation priority). "
    "Rules: use ONLY numbers that appear in the JSON, never invent figures, name areas only as given, present "
    "landing sites as 'candidate sites for operator confirmation', and end with an explicit uncertainty note: "
    "single-view vertical error is metre-scale and surface strength is not assessed."
)
QA_PROMPT = (
    "Answer the user's question about the scene using only the JSON statistics provided. If the statistics do not "
    "contain the answer, say so. Be concise and cite the numbers."
)


def findings_path(job_dir: Path) -> Path:
    return job_dir / "findings.json"


def load_findings(job_dir: Path) -> list[dict]:
    path = findings_path(job_dir)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def save_findings(job_dir: Path, findings: list[dict]) -> None:
    findings_path(job_dir).write_text(json.dumps(findings[-40:]), encoding="utf-8")


def gather_context(job_dir: Path) -> tuple[dict[str, Any], list[str]]:
    findings = load_findings(job_dir)
    flood_level: Optional[float] = None
    for item in reversed(findings):
        if item.get("tool") == "flood" and isinstance(item.get("data", {}).get("level"), (int, float)):
            flood_level = float(item["data"]["level"])
            break
    context: dict[str, Any] = {}
    called: list[str] = []
    for name in ("get_scene_summary", "get_detected_objects", "get_flood_result", "get_landing_zones",
                 "get_slope_stats", "get_validation_metrics"):
        try:
            context[name] = tools.get_flood_result(job_dir, flood_level) if name == "get_flood_result" else tools.TOOLS[name](job_dir)
            called.append(name)
        except FileNotFoundError:
            continue
    context["operator_findings"] = [{"tool": f.get("tool"), "text": f.get("text")} for f in findings[-12:]]
    return context, called


# ---------------------------------------------------------------- offline template

def _fmt(value: Any, digits: int = 2, unit: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value:,.{digits}f}{unit}"


def template_report(context: dict[str, Any]) -> str:
    scene = context.get("get_scene_summary", {})
    flood = context.get("get_flood_result", {})
    zones = context.get("get_landing_zones", {})
    slope = context.get("get_slope_stats", {})
    valid = context.get("get_validation_metrics", {})
    unit = "m" if scene.get("height_unit") == "m" else " relative units"
    classes = scene.get("class_area_km2", {})
    top_class = sorted(classes.items(), key=lambda kv: kv[1], reverse=True)[:3]

    lines = ["## Situation report", ""]
    lines.append(
        f"The scene covers {_fmt(scene.get('scene_area_km2'), 3)} km2 at {_fmt(scene.get('pixel_size_m'), 2)} m per pixel "
        f"({scene.get('mode', 'unknown')} height model). Surface heights range from {_fmt(scene.get('height_min'), 1)} to "
        f"{_fmt(scene.get('height_max'), 1)}{unit}; the mean height above ground is {_fmt(scene.get('height_above_ground_mean'), 1)}{unit} "
        f"and the 95th percentile is {_fmt(scene.get('height_above_ground_p95'), 1)}{unit}."
    )
    lines.append(
        f"{scene.get('building_count', 0)} building footprints were detected. Dominant surfaces: "
        + ", ".join(f"{name.replace('_', ' ')} ({_fmt(area, 3)} km2)" for name, area in top_class)
        + "."
    )
    if slope:
        lines.append(
            f"Slopes reach {_fmt(slope.get('max_slope_deg'), 1)} degrees (mean {_fmt(slope.get('mean_slope_deg'), 1)}); "
            f"{_fmt(slope.get('area_km2_above_30deg'), 4)} km2 exceeds 30 degrees and {_fmt(slope.get('area_km2_above_15deg'), 4)} km2 exceeds 15 degrees."
        )
    lines += ["", "## Ranked risk areas", ""]
    rank = 1
    if flood:
        lines.append(
            f"{rank}. Flooding at a water level of {_fmt(flood.get('water_level_above_reference'), 1)}{unit} above the reference inundates "
            f"{_fmt(flood.get('inundated_area_km2'), 4)} km2 ({_fmt((flood.get('inundated_fraction') or 0) * 100, 1)}% of the scene) and affects "
            f"{flood.get('affected_buildings', 0)} of {flood.get('total_buildings', 0)} buildings."
        )
        rank += 1
        for area in flood.get("worst_hit_areas", [])[:3]:
            lines.append(
                f"{rank}. The {area['area']} sector is worst hit: {_fmt(area['flooded_fraction'] * 100, 1)}% flooded, mean depth {_fmt(area['mean_depth'], 2)}{unit}."
            )
            rank += 1
    if slope and (slope.get("area_km2_above_30deg") or 0) > 0:
        lines.append(f"{rank}. Steep terrain above 30 degrees ({_fmt(slope.get('area_km2_above_30deg'), 4)} km2) is a landslide-prone risk.")
        rank += 1
    if rank == 1:
        lines.append("No hazard statistics were available yet. Run the flood, slope or landing-zone tools on the Hazards screen.")

    lines += ["", "## Response plan", ""]
    sites = zones.get("sites", [])
    if sites:
        lines.append("Landing and relief-drop options (candidate sites for operator confirmation):")
        for site in sites[:3]:
            road = f", {_fmt(site.get('nearest_road_m'), 0)} m from a road" if site.get("nearest_road_m") is not None else ""
            lines.append(
                f"- Site {site['rank']}: clear radius {_fmt(site.get('clear_radius_m'), 1)} m, mean slope {_fmt(site.get('mean_slope_deg'), 1)} degrees, "
                f"score {_fmt(site.get('score'), 2)}{road}."
            )
        lines.append(f"- Total flat, obstacle-free candidate area: {_fmt(zones.get('candidate_area_km2'), 4)} km2. Use the highest-scoring sites outside the flood extent for camps and drops.")
    else:
        lines.append("No qualifying landing sites were found with the current criteria; relax the radius or slope limit.")
    if flood:
        lines.append(f"- Evacuate the most-flooded sectors first; {flood.get('affected_buildings', 0)} buildings need priority checks at the modelled level.")
        lines.append("- Prefer access routes outside the inundated area; verify roads on the ground before dispatch.")
    if valid.get("available"):
        g = valid["global"]
        lines.append(f"- Height accuracy against the supplied reference: RMSE {_fmt(g.get('rmse'), 2)} m, MAE {_fmt(g.get('mae'), 2)} m, r = {_fmt(g.get('pearson_r'), 2)}.")

    lines += ["", "**Uncertainty note.** Heights come from a single image: vertical error is metre-scale "
              f"(mean modelled uncertainty {_fmt(scene.get('mean_uncertainty'), 2)}{unit}), surface strength (mud vs tarmac) is not assessed, "
              "and landing sites are decision support for a pilot to confirm, not a clearance.",
              "", "_Generated offline by the template analyst from computed statistics; no language model was used._"]
    return "\n".join(lines)


# ---------------------------------------------------------------- verification

_NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*\.?\d*")


def _collect_numbers(value: Any, out: set[float]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        out.add(float(value))
        out.add(float(value) * 100.0)
    elif isinstance(value, dict):
        for v in value.values():
            _collect_numbers(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _collect_numbers(v, out)


def unverified_numbers(text: str, context: dict[str, Any]) -> list[str]:
    known: set[float] = set()
    _collect_numbers(context, known)
    bad: list[str] = []
    for match in _NUMBER.findall(text):
        try:
            number = float(match.replace(",", ""))
        except ValueError:
            continue
        if number in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10) and "." not in match:
            continue
        if not any(abs(number - k) <= max(0.06 * abs(k), 0.06) for k in known):
            bad.append(match)
    return bad[:20]


# ---------------------------------------------------------------- online

def stream_llm(settings: Settings, system: str, user_payload: str,
               history: Optional[list[dict[str, str]]] = None) -> Iterator[str]:
    headers = {"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"}
    messages = [{"role": "system", "content": system}]
    messages += history or []
    messages.append({"role": "user", "content": user_payload})
    body = {"model": settings.openai_model, "stream": True, "temperature": 0.2, "messages": messages}
    with httpx.stream("POST", f"{settings.openai_base_url.rstrip('/')}/chat/completions", headers=headers,
                      json=body, timeout=httpx.Timeout(60.0, connect=8.0)) as response:
        if response.status_code != 200:
            raise RuntimeError(f"LLM endpoint returned HTTP {response.status_code}")
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                delta = json.loads(data)["choices"][0]["delta"].get("content")
            except (KeyError, IndexError, json.JSONDecodeError):
                continue
            if delta:
                yield delta


def report_events(settings: Settings, job_dir: Path, force_offline: bool = False) -> Iterator[dict[str, Any]]:
    """Yield {'event': 'tool'|'text'|'done'|'notice', ...} dictionaries for SSE streaming."""
    context, called = gather_context(job_dir)
    for name in called:
        yield {"event": "tool", "name": name, "label": tools.TOOL_LABELS[name]}

    text_parts: list[str] = []
    mode = "offline_template"
    notice: Optional[str] = None
    streamed_partial = False
    if settings.analyst_available and not force_offline:
        try:
            for token in stream_llm(settings, SYSTEM_PROMPT, json.dumps(context)):
                text_parts.append(token)
                streamed_partial = True
                yield {"event": "text", "text": token}
            mode = "online"
        except Exception as exc:  # noqa: BLE001 - offline or endpoint failure: fall back cleanly
            notice = f"Online analyst unavailable ({type(exc).__name__}); using the offline template analyst."
            text_parts.clear()
    elif not settings.analyst_available:
        notice = "No OPENAI_API_KEY is configured; using the offline template analyst."
    if notice:
        yield {"event": "notice", "text": notice}
    if mode != "online":
        if streamed_partial:
            # Partial online tokens were already sent to the client before the stream failed;
            # tell it to discard them before the offline template's text events arrive.
            yield {"event": "reset"}
        report = template_report(context)
        for chunk in re.findall(r"\S+\s*|\n", report):
            text_parts.append(chunk)
            yield {"event": "text", "text": chunk}

    full = "".join(text_parts)
    unverified = unverified_numbers(full, context) if mode == "online" else []
    record = {"text": full, "mode": mode, "generated_at": time.time(), "unverified_numbers": unverified, "tools": called,
              "notice": notice}
    (job_dir / "brief.json").write_text(json.dumps(record), encoding="utf-8")
    yield {"event": "done", "mode": mode, "unverified_numbers": unverified, "generated_at": record["generated_at"]}


def load_cached_report(job_dir: Path) -> Optional[dict]:
    path = job_dir / "brief.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


# ---------------------------------------------------------------- Q&A

def _offline_answer(question: str, context: dict[str, Any]) -> str:
    q = question.lower()
    scene = context.get("get_scene_summary", {})
    unit = "m" if scene.get("height_unit") == "m" else " relative units"
    if re.search(r"flood|water|inundat|submerg", q) and context.get("get_flood_result"):
        f = context["get_flood_result"]
        return (f"At a water level of {_fmt(f.get('water_level_above_reference'), 1)}{unit} above the reference, "
                f"{_fmt(f.get('inundated_area_km2'), 4)} km2 is inundated ({_fmt((f.get('inundated_fraction') or 0) * 100, 1)}%) and "
                f"{f.get('affected_buildings')} of {f.get('total_buildings')} buildings are affected. "
                + (f"The worst-hit sector is {f['worst_hit_areas'][0]['area']}." if f.get("worst_hit_areas") else ""))
    if re.search(r"object|vehicle|car|truck|ship|boat|plane|aircraft|helicopter pad|detect|count|how many", q) and context.get("get_detected_objects", {}).get("available"):
        o = context["get_detected_objects"]
        classes = ", ".join(f"{count} x {name}" for name, count in
                            sorted(o.get("counts_by_class", {}).items(), key=lambda kv: -kv[1]))
        tallest = o.get("tallest_reliable") or []
        extra = ""
        if tallest:
            extra = (f" The tallest object with a height above the model's noise floor is a {tallest[0]['label']} at "
                     f"{_fmt(tallest[0]['height_above_ground'], 1)}{unit}.")
        else:
            extra = (" No detected object is tall enough for its height to be above this single-view model's "
                     "metre-scale vertical noise floor, so per-object heights are indicative only.")
        return f"{o.get('total_count', 0)} object(s) were detected by {o.get('model')}: {classes}.{extra}"
    if re.search(r"land|helicopter|uav|drone|relief|camp|drop", q) and context.get("get_landing_zones"):
        z = context["get_landing_zones"]
        if not z.get("sites"):
            return "No candidate landing sites met the criteria (flat, obstacle-free, clear radius)."
        s = z["sites"][0]
        return (f"The best candidate site (for operator confirmation) has a clear radius of {_fmt(s.get('clear_radius_m'), 1)} m, "
                f"mean slope {_fmt(s.get('mean_slope_deg'), 1)} degrees and score {_fmt(s.get('score'), 2)}; {len(z['sites'])} candidates are ranked. "
                "Surface strength is not assessed.")
    if re.search(r"slope|landslide|steep", q) and context.get("get_slope_stats"):
        sl = context["get_slope_stats"]
        return (f"Maximum slope is {_fmt(sl.get('max_slope_deg'), 1)} degrees; {_fmt(sl.get('area_km2_above_30deg'), 4)} km2 is above 30 degrees "
                f"and {_fmt(sl.get('area_km2_above_15deg'), 4)} km2 above 15 degrees.")
    if re.search(r"accura|error|rmse|valid|reliab|trust", q):
        v = context.get("get_validation_metrics", {})
        if v.get("available"):
            g = v["global"]
            return f"Against the supplied reference: RMSE {_fmt(g.get('rmse'), 2)} m, MAE {_fmt(g.get('mae'), 2)} m, r = {_fmt(g.get('pearson_r'), 2)}."
        return f"No reference data was scored yet. The mean modelled uncertainty is {_fmt(scene.get('mean_uncertainty'), 2)}{unit}; vertical error is metre-scale."
    return (f"The scene spans {_fmt(scene.get('scene_area_km2'), 3)} km2 with heights from {_fmt(scene.get('height_min'), 1)} to {_fmt(scene.get('height_max'), 1)}{unit} "
            f"and {scene.get('building_count', 0)} detected buildings. Ask about flooding, landing zones, slopes or accuracy for specifics.")


MAX_HISTORY_TURNS = 12
MAX_MESSAGE_CHARS = 2000

CHAT_PROMPT = (
    "You are the AakashDrishti scene analyst, answering an operator's questions about ONE scene reconstructed "
    "from a single satellite image. You are given JSON statistics derived from that scene: height model summary, "
    "detected aerial objects, flood simulation, landing zones, slope and validation metrics.\n"
    "Rules: use ONLY numbers present in the JSON and never invent figures. If the statistics do not answer the "
    "question, say exactly what is missing and which screen would produce it (Hazards for flood/landing/slope, "
    "Validation lab for accuracy). Keep answers short and conversational -- a few sentences, no headings unless "
    "asked. Quote units. When you cite a per-object height, note that objects below 2.5 m sit at this single-view "
    "model's vertical noise floor. Landing sites are always 'candidate sites for operator confirmation'."
)


def chat_events(
    settings: Settings,
    job_dir: Path,
    question: str,
    history: Optional[list[dict[str, str]]] = None,
) -> Iterator[dict[str, Any]]:
    """Yield {'event': 'tool'|'text'|'notice'|'done'} dicts for a streamed, multi-turn chat answer.

    Same contract and the same offline fallback as `report_events`: the scene statistics are
    gathered through the read-only tools, so raw imagery is never sent anywhere.
    """
    context, called = gather_context(job_dir)
    for name in called:
        yield {"event": "tool", "name": name, "label": tools.TOOL_LABELS[name]}

    turns: list[dict[str, str]] = []
    for message in (history or [])[-MAX_HISTORY_TURNS:]:
        role = message.get("role")
        content = (message.get("content") or "")[:MAX_MESSAGE_CHARS]
        if role in ("user", "assistant") and content:
            turns.append({"role": role, "content": content})

    parts: list[str] = []
    mode = "offline_template"
    notice: Optional[str] = None
    streamed_partial = False
    if settings.analyst_available:
        payload = json.dumps({"question": question, "statistics": context})
        try:
            for token in stream_llm(settings, CHAT_PROMPT, payload, history=turns):
                parts.append(token)
                streamed_partial = True
                yield {"event": "text", "text": token}
            mode = "online"
        except Exception as exc:  # noqa: BLE001 -- offline or endpoint failure falls back cleanly
            notice = f"Online analyst unavailable ({type(exc).__name__}); answered offline."
            parts.clear()
    else:
        notice = "No OPENAI_API_KEY configured; answered offline from the computed statistics."
    if notice:
        yield {"event": "notice", "text": notice}
    if mode != "online":
        if streamed_partial:
            yield {"event": "reset"}
        answer = _offline_answer(question, context)
        for chunk in re.findall(r"\S+\s*|\n", answer):
            parts.append(chunk)
            yield {"event": "text", "text": chunk}

    full = "".join(parts)
    yield {
        "event": "done",
        "mode": mode,
        "tools": called,
        "unverified_numbers": unverified_numbers(full, context) if mode == "online" else [],
    }


def answer_question(settings: Settings, job_dir: Path, question: str) -> dict[str, Any]:
    context, called = gather_context(job_dir)
    if settings.analyst_available:
        try:
            text = "".join(stream_llm(settings, QA_PROMPT, json.dumps({"question": question, "statistics": context})))
            return {"answer": text, "mode": "online", "tools": called, "unverified_numbers": unverified_numbers(text, context)}
        except Exception as exc:  # noqa: BLE001
            note = f"Online analyst unavailable ({type(exc).__name__}); answered offline."
            return {"answer": _offline_answer(question, context), "mode": "offline_template", "tools": called, "notice": note,
                    "unverified_numbers": []}
    return {"answer": _offline_answer(question, context), "mode": "offline_template", "tools": called,
            "notice": "No OPENAI_API_KEY configured; answered offline from the computed statistics.", "unverified_numbers": []}
