# pdf_utils.py

from xml.sax.saxutils import escape as xml_escape

from io import BytesIO
from typing import Dict, Any

import json
import pandas as pd
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.units import inch
from reportlab.lib import colors

def _safe_paragraph(text: Any, style: ParagraphStyle, allow_markup: bool = False) -> Paragraph:
    """
    Create a Paragraph that won't blow up if the text contains '<', '>' or '&'.

    - If allow_markup is False, we escape XML chars so ReportLab treats it as plain text.
    - If allow_markup is True, we pass it through unchanged (for our own <b>, <font>, etc).
    """
    if text is None:
        text = ""
    s = _to_plain_text(text)
    if not allow_markup:
        s = xml_escape(s)
    return Paragraph(s, style)

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

        prod_label = row.get("production_title", "") or row.get("production", "")
        label = f"{row.get('strategic_pillar', '')} / {prod_label} / {row.get('metric', '')}"
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

def _parse_score_hint(score_hint: str | None) -> float | None:
    """Extract an approximate 0–3 score from a score_hint string."""

    if not score_hint:
        return None

    text = str(score_hint)

    # Try to find a fractional pattern like ``2/3`` or ``11 / 12``.
    import re

    frac_match = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", text)
    if frac_match:
        num = float(frac_match.group(1))
        den = float(frac_match.group(2))
        if den != 0:
            # Scale to the 0–3 range used in the Streamlit scorecard.
            return max(0.0, min(3.0, (num / den) * 3))

    # Otherwise fall back to the first standalone number.
    num_match = re.search(r"(\d+(?:\.\d+)?)", text)
    if num_match:
        value = float(num_match.group(1))
        # Clip to a sensible 0–3 range.
        return max(0.0, min(3.0, value))

    return None


def _score_to_colour(score: float | None) -> colors.Color:
    """Return a background colour based on score performance."""

    if score is None:
        return colors.Color(0.8, 0.82, 0.85)  # muted grey-blue

    if score >= 2.5:
        return colors.Color(0.40, 0.67, 0.63)  # teal/green
    if score >= 1.5:
        return colors.Color(0.93, 0.73, 0.39)  # amber
    return colors.Color(0.91, 0.44, 0.32)  # coral red

def _score_display(score: float | None) -> str:
    if score is None:
        return "N/A"
    return f"{score:.2f}"


def _chunked(iterable, size: int):
    chunk: list[Any] = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _build_pillar_card(styles, pillar_name: str, score_hint: str, summary: str) -> Flowable:
    score_value = _parse_score_hint(score_hint)
    header_bg = _score_to_colour(score_value)

    score_hint_text = _to_plain_text(score_hint).strip()

    header_parts = [f"<b>{pillar_name or 'Pillar'}</b>"]
    score_display = _score_display(score_value)
    header_parts.append(f"<font size=10>{score_display if score_display != 'N/A' else 'Not rated'}</font>")
    if score_hint_text and score_hint_text not in header_parts[-1]:
        header_parts.append(f"<font size=9>{score_hint_text}</font>")

    header = Paragraph("<br/>".join(header_parts), styles["CardHeader"])  # keep markup
    
    body = _safe_paragraph(summary or "No summary provided.", styles["CardBody"])

    card = Table(
        [[header], [body]],
        colWidths=[2.3 * inch],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), header_bg),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white if score_value is not None else colors.black),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("BACKGROUND", (0, 1), (-1, 1), colors.whitesmoke),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        ),
    )

    return card
                
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

    styles.add(
        ParagraphStyle(
            name="ScorecardTitle",
            parent=styles["Title"],
            fontSize=22,
            leading=26,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="MetaLine",
            parent=styles["Normal"],
            textColor=colors.grey,
            fontSize=10,
            leading=12,
        )
    )
    styles.add(
        ParagraphStyle(
            name="MetaLabel",
            parent=styles["Normal"],
            textColor=colors.grey,
            fontSize=9,
            leading=11,
            spaceAfter=1,
        )
    )
    styles.add(
        ParagraphStyle(
            name="MetaValue",
            parent=styles["BodyText"],
            fontSize=10,
            leading=12,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CardHeader",
            parent=styles["Heading4"],
            textColor=colors.white,
            alignment=1,
            leading=14,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CardBody",
            parent=styles["BodyText"],
            fontSize=9,
            leading=12,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionHeading",
            parent=styles["Heading2"],
            fontSize=14,
            spaceBefore=12,
            spaceAfter=6,
        )
    )

    story: list[Flowable] = []

    # Title block with total score call-out
    staff_name = meta.get("staff_name", "Staff")
    report_month = meta.get("month", "")
    title_text = f"{staff_name} — Monthly Scorecard"

    pillar_summaries = [ps for ps in (ai_result.get("pillar_summaries") or []) if isinstance(ps, dict)]
    scores = [_parse_score_hint(ps.get("score_hint")) for ps in pillar_summaries]
    scores = [s for s in scores if s is not None]
    total_score = sum(scores) / len(scores) if scores else None

    total_colour = _score_to_colour(total_score)

    total_score_display = _score_display(total_score)
    if total_score_display != "N/A":
        total_value = f"{total_score_display} / 3"
    else:
        total_value = "Not rated"

    total_table = Table(
        [
            [Paragraph("<b>Total score</b>", styles["Heading4"])],
            [Paragraph(total_value, styles["Heading1"])],
        ],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), total_colour),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.white if total_score is not None else colors.black),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.75, colors.black),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        ),
        colWidths=[2.2 * inch],
        rowHeights=[0.5 * inch, 0.9 * inch],
    )

    meta_pairs: list[tuple[str, str]] = [
        ("Staff", staff_name or "—"),
        ("Department", meta.get("department", "") or "—"),
        ("Role", meta.get("role", "") or "—"),
    ]

    # Month line separated so it can render with lighter label
    if report_month:
        meta_pairs.append(("Report month", str(report_month)))

    for optional_key, label in (
        ("location", "Location"),
        ("team", "Team"),
        ("manager", "Manager"),
    ):
        value = meta.get(optional_key)
        if value:
            meta_pairs.append((label, str(value)))

    meta_rows = [
        [
            Paragraph(label.upper(), styles["MetaLabel"]),
            Paragraph(str(value), styles["MetaValue"]),
        ]
        for label, value in meta_pairs
    ]

    meta_table = Table(
        meta_rows,
        colWidths=[1.4 * inch, 3.2 * inch],
        style=TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        ),
    )
    
    header_table = Table(
        [[Paragraph("Summary Scorecard", styles["ScorecardTitle"]), total_table]],
        colWidths=[4.8 * inch, 2.2 * inch],
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]
        ),
    )
    
    story.append(header_table)
    story.append(Paragraph(title_text, styles["MetaLine"]))
    story.append(Spacer(1, 6))
    story.append(meta_table)
    story.append(Spacer(1, 12))

    overall = _to_plain_text(ai_result.get("overall_summary", "") or "")
    if overall:
        story.append(Paragraph("Executive Summary", styles["SectionHeading"]))
        story.append(_safe_paragraph(overall, styles["BodyText"]))
        story.append(Spacer(1, 12))

    if pillar_summaries:
        story.append(Paragraph("Strategic Pillars", styles["SectionHeading"]))

        cards: list[Flowable] = []
        for ps in pillar_summaries:
            summary_text = _to_plain_text(ps.get("summary", ""))
            card = _build_pillar_card(
                styles,
                ps.get("strategic_pillar", "Pillar"),
                ps.get("score_hint", ""),
                summary_text,
            )
            cards.append(card)

        rows = []
        for row_cards in _chunked(cards, 3):
            # Pad row to always have three columns for consistent layout
            while len(row_cards) < 3:
                row_cards.append(Spacer(2.3 * inch, 0))
            rows.append(row_cards)

        pillar_grid = Table(
            rows,
            colWidths=[2.3 * inch, 2.3 * inch, 2.3 * inch],
            hAlign="LEFT",
            style=TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            ),
        )

        story.append(pillar_grid)
        story.append(Spacer(1, 12))

    production_summaries = ai_result.get("production_summaries", []) or []
    if production_summaries:
        story.append(Paragraph("By Production / Programme", styles["SectionHeading"]))
        for prod in production_summaries:
            if not isinstance(prod, dict):
                continue

            pname = _to_plain_text(prod.get("production") or "General")
            story.append(Paragraph(f"<b>{pname}</b>", styles["BodyText"]))

            pillars = prod.get("pillars") or []
            for ps in pillars:
                if not isinstance(ps, dict):
                    continue

                pillar_name = _to_plain_text(ps.get("pillar", "Category"))
                score_hint = _to_plain_text(ps.get("score_hint", ""))
                summary_text = _to_plain_text(ps.get("summary", ""))

                story.append(
                    Paragraph(
                        f"<b>{xml_escape(pillar_name)}</b> — {xml_escape(score_hint)}",
                        styles["Small"],
                    )
                )
                story.append(Paragraph(summary_text, styles["BodyText"]))

            story.append(Spacer(1, 6))

    risks = [
        _to_plain_text(r)
        for r in (ai_result.get("risks", []) or [])
        if _to_plain_text(r).strip()
    ]
    if risks:
        story.append(Paragraph("Key Risks / Concerns", styles["SectionHeading"]))
        for r in risks:
            story.append(_safe_paragraph(f"• {r}", styles["BodyText"]))

    priorities = [
        _to_plain_text(p)
        for p in (ai_result.get("priorities_next_month", []) or [])
        if _to_plain_text(p).strip()
    ]
    if priorities:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Priorities for Next Month", styles["SectionHeading"]))
        for p in priorities:
            story.append(_safe_paragraph(f"• {p}", styles["BodyText"]))

    nfl = _to_plain_text(ai_result.get("notes_for_leadership", ""))
    if nfl.strip():
        story.append(Spacer(1, 6))
        story.append(Paragraph("Notes for Leadership", styles["SectionHeading"]))
        story.append(_safe_paragraph(nfl, styles["BodyText"]))

    story.append(Spacer(1, 12))
    story.append(Paragraph("Raw Scorecard Responses", styles["SectionHeading"]))
    story.append(Spacer(1, 6))
    story.append(_responses_table(questions, responses))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
