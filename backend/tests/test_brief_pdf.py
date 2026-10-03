"""The situation-brief PDF builds from the bundled featured scene and carries bookmarks + links."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.analyst import report as analyst
from app.analyst.pdf_report import build_brief_pdf

JOB_DIR = Path(__file__).resolve().parents[1] / "demo" / "featured" / "job"
pymupdf = pytest.importorskip("pymupdf")


@pytest.mark.skipif(not (JOB_DIR / "arrays.npz").is_file(), reason="featured demo scene not bundled")
def test_brief_pdf_has_outline_links_and_pages():
    context, _ = analyst.gather_context(JOB_DIR)
    brief = {"text": analyst.template_report(context), "mode": "offline_template", "unverified_numbers": []}
    meta = json.loads((JOB_DIR / "metadata.json").read_text(encoding="utf-8"))

    pdf = build_brief_pdf(JOB_DIR.parent.name, JOB_DIR, brief, meta, "http://localhost:3000")

    doc = pymupdf.open(stream=pdf, filetype="pdf")
    assert doc.page_count >= 6
    titles = [entry[1] for entry in doc.get_toc()]
    assert any("Height and terrain analytics" in t for t in titles)
    assert any(link.get("uri", "").startswith("http://localhost:3000/survey/") for page in doc for link in page.get_links())
