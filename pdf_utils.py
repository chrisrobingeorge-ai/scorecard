# pdf_utils.py

from io import BytesIO
from typing import Dict, Any

import json
import pandas as pd
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.units import inch
from reportlab.lib import colors


def _to_plain_text(val: Any) -> str:
    """
    Normalise various AI output types to a human-readable string.

    - If already a string, return as-is.
    - If list, join items with double newlines.
    - If dict, try 'text' key, otherwise JSON-dump / str().
    - If None, return empty string.
    """
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        # Join list items as separate paragraphs
        return "\n\n".join(_to_plain_text(v) for v in val)
    if isinstance(val, dict):
        # Common pattern: {"text": "..."}
        if "text" in val and isinstance(val["text"], str):
            return val["text"]
        try:
            return json.dumps(val, ensure_ascii=False, indent=2)
        except Exception:
            return str(val)
    return str(val)


def _responses_table(questions: pd.DataFrame, responses: Dict[str, Any]):
    """
    Build a simple 2-column table of metric vs response (primary + description).
    """
    data = [["Pillar / Production / Metric", "Response"]]
    for _, row in questions.sort_values("display_order").iterrows():
        qid = row["question_id"]

        # Ensure we look up using string key, since the app stores qids as strings
        qid_str = str(qid)

        label = f"{row.get('strategic_pillar', '')} / {row.get('production', '')} / {row.get('metric', '')}"
        raw_val = responses.get(qid_str, responses.get(qid, ""))

        if isinstance(raw_val, dict):
            primary = raw_val.get("primary", "")
            desc = raw_val.get("description", "")
            if desc:
                value_str = f"{primary} — {desc}"
            else:
                value_str = str(primary)
        else:
            value_str = str(raw_val)

        data.append([label, value_str])

    table = Table(
        data,
        colWidths=[3.5 * inch, 3.5 * inch],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def build_scorecard_pdf(
    meta: Dict[str, Any],
    questions: pd.DataFrame,
    responses: Dict[str, Any],
    ai_result: Dict[str, Any],
) -> bytes:
    """
    Build and return the PDF as raw bytes.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small", fontSize=9, leading=11))

    story = []

    # Title
    title = f"{meta.get('staff_name', 'Staff')} — Monthly Scorecard ({meta.get('month', '')})"
    story.append(Paragraph(title, styles["Title"]))
    story.append(Spacer(1, 6))

    # Meta line
    meta_line = f"{meta.get('department', '')} — {meta.get('role', '')}"
    story.append(Paragraph(meta_line, styles["Normal"]))
    story.append(Spacer(1, 12))

    # Overall summary
    summary = _to_plain_text(ai_result.get("overall_summary", ""))
    if summary.strip():
        story.append(Paragraph("Overall Summary", styles["Heading2"]))
        for para in summary.split("\n\n"):
            if para.strip():
                story.append(Paragraph(para.strip(), styles["BodyText"]))
                story.append(Spacer(1, 6))
        story.append(Spacer(1, 12))

    # Strategic Summary (overall line + pillar view)
    pillar_summaries = ai_result.get("pillar_summaries", []) or []
    overall = ai_result.get("overall_summary", "") or ""

    if overall or pillar_summaries:
        story.append(Paragraph("Strategic Summary", styles["Heading2"]))
        story.append(Spacer(1, 6))

        # Overall line first
        if overall:
            story.append(Paragraph(_to_plain_text(overall), styles["BodyText"]))
            story.append(Spacer(1, 8))

        # Then the per-pillar entries
        for ps in pillar_summaries:
            if not isinstance(ps, dict):
                ps = {"strategic_pillar": "", "score_hint": "", "summary": _to_plain_text(ps)}

            heading = f"{ps.get('strategic_pillar', 'Pillar')} — {ps.get('score_hint', '')}"
            story.append(Paragraph(_to_plain_text(heading), styles["Heading4"]))

            pillar_summary_text = _to_plain_text(ps.get("summary", ""))
            story.append(Paragraph(pillar_summary_text, styles["BodyText"]))
            story.append(Spacer(1, 6))

        story.append(Spacer(1, 12))

    # Production / programme summaries (if available)
    production_summaries = ai_result.get("production_summaries", []) or []
    if production_summaries:
        story.append(Paragraph("By Production / Programme", styles["Heading2"]))
        story.append(Spacer(1, 6))

        for prod in production_summaries:
            # Ensure dict shape
            if not isinstance(prod, dict):
                continue

            pname = prod.get("production") or "General"
            story.append(Paragraph(_to_plain_text(pname), styles["Heading3"]))
            story.append(Spacer(1, 4))

            pillars = prod.get("pillars") or []
            for ps in pillars:
                if not isinstance(ps, dict):
                    ps = {"pillar": "", "score_hint": "", "summary": _to_plain_text(ps)}

                pillar_name = ps.get("pillar", "Category")
                score_hint = ps.get("score_hint", "")
                heading = pillar_name
                if score_hint:
                    heading = f"{pillar_name} — {score_hint}"

                story.append(Paragraph(_to_plain_text(heading), styles["Heading4"]))

                pillar_text = _to_plain_text(ps.get("summary", ""))
                story.append(Paragraph(pillar_text, styles["BodyText"]))
                story.append(Spacer(1, 4))

            story.append(Spacer(1, 8))

        story.append(Spacer(1, 12))

    # Risks
    risks = ai_result.get("risks", []) or []
    if risks:
        story.append(Paragraph("Key Risks / Concerns", styles["Heading2"]))
        for r in risks:
            story.append(Paragraph(f"• {_to_plain_text(r)}", styles["BodyText"]))
        story.append(Spacer(1, 12))

    # Priorities
    priorities = ai_result.get("priorities_next_month", []) or []
    if priorities:
        story.append(Paragraph("Priorities for Next Month", styles["Heading2"]))
        for p in priorities:
            story.append(Paragraph(f"• {_to_plain_text(p)}", styles["BodyText"]))
        story.append(Spacer(1, 12))

    # Notes for leadership
    nfl = _to_plain_text(ai_result.get("notes_for_leadership", ""))
    if nfl.strip():
        story.append(Paragraph("Notes for Leadership", styles["Heading2"]))
        story.append(Paragraph(nfl, styles["BodyText"]))
        story.append(Spacer(1, 12))

    # Responses table
    story.append(Paragraph("Raw Scorecard Responses", styles["Heading2"]))
    story.append(Spacer(1, 6))
    story.append(_responses_table(questions, responses))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
