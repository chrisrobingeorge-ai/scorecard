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
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    Image,
    PageBreak,
)
from reportlab.lib.units import inch
from reportlab.lib import colors


# ─────────────────────────────────────────────────────────────────────────────
# Helper text utilities
# ─────────────────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
# Score utilities
# ─────────────────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
# Tables
# ─────────────────────────────────────────────────────────────────────────────
def _responses_table(questions: pd.DataFrame, responses: Dict[str, Any]) -> Table:
    """
    Build a simple 2-column table of metric vs response (primary + description).
    """
    data: list[list[Any]] = [["Pillar / Production / Metric", "Response"]]

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

    # Base styling
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]

    # Alternate row shading for readability
    for i in range(1, len(data)):
        if i % 2 == 1:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), colors.whitesmoke))

    table = Table(
        data,
        colWidths=[3.5 * inch, 3.5 * inch],
        repeatRows=1,
    )
    table.setStyle(TableStyle(style_cmds))
    return table


# ─────────────────────────────────────────────────────────────────────────────
# Main PDF builder
# ─────────────────────────────────────────────────────────────────────────────
def build_scorecard_pdf(
    meta: Dict[str, Any],
    questions: pd.DataFrame,
    responses: Dict[str, Any],
    ai_result: Dict[str, Any],
    logo_path: str | None = None,
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
            spaceAfter=4,
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
            name="SectionHeading",
            parent=styles["Heading2"],
            fontSize=14,
            spaceBefore=12,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SubHeading",
            parent=styles["Heading3"],
            fontSize=11,
            leading=14,
            spaceBefore=8,
            spaceAfter=2,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SubHeadingSmall",
            parent=styles["Heading4"],
            fontSize=9.5,
            leading=12,
            spaceBefore=4,
            spaceAfter=1,
        )
    )

    story: list[Flowable] = []

    # ─────────────────────────────────────────────────────────────────────
    # Title block with total score call-out
    # ─────────────────────────────────────────────────────────────────────
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
            [Paragraph("<b>Total score</b>", styles["Small"])],
            [Paragraph(total_value, styles["Title"])],
        ],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), total_colour),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.white if total_score is not None else colors.black),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.75, colors.black),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        ),
        colWidths=[2.0 * inch],
        rowHeights=[0.4 * inch, 0.9 * inch],
    )

    # Meta info
    meta_pairs: list[tuple[str, str]] = [
        ("Staff", staff_name or "—"),
        ("Department", meta.get("department", "") or "—"),
        ("Role", meta.get("role", "") or "—"),
    ]

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

    # Optional logo
    logo_flowable: Flowable | None = None
    if logo_path:
        try:
            img = Image(logo_path)
            img._restrictSize(1.1 * inch, 1.1 * inch)
            logo_flowable = img
        except Exception:
            logo_flowable = None

    # Title + subtitle block as its own small table (for better alignment)
    title_block = [
        Paragraph("Summary Scorecard", styles["ScorecardTitle"]),
        Paragraph(title_text, styles["MetaLine"]),
    ]
    title_table = Table(
        [[title_block[0]], [title_block[1]]],
        colWidths=[4.0 * inch],
        style=TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        ),
    )

    # Build header row: [logo] [title+subtitle] [total score]
    header_cells: list[Flowable] = []
    if logo_flowable:
        header_cells.append(logo_flowable)
    else:
        header_cells.append(Spacer(0.5 * inch, 0.5 * inch))

    header_cells.append(title_table)
    header_cells.append(total_table)

    header_table = Table(
        [header_cells],
        colWidths=[1.2 * inch, 3.6 * inch, 2.2 * inch],
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        ),
    )

    story.append(header_table)
    story.append(Spacer(1, 6))
    story.append(meta_table)
    story.append(Spacer(1, 12))

    # ─────────────────────────────────────────────────────────────────────
    # Executive summary
    # ─────────────────────────────────────────────────────────────────────
    overall = _to_plain_text(ai_result.get("overall_summary", "") or "")
    if overall:
        story.append(Paragraph("Executive Summary", styles["SectionHeading"]))
        story.append(_safe_paragraph(overall, styles["BodyText"]))
        story.append(Spacer(1, 12))

    # ─────────────────────────────────────────────────────────────────────
    # Strategic pillars – narrative format
    # ─────────────────────────────────────────────────────────────────────
    if pillar_summaries:
        story.append(Paragraph("Strategic Pillars", styles["SectionHeading"]))

        for ps in pillar_summaries:
            pillar_name = _to_plain_text(ps.get("strategic_pillar", "Pillar")).strip() or "Pillar"
            score_hint_raw = _to_plain_text(ps.get("score_hint", "")).strip()
            summary_text = _to_plain_text(ps.get("summary", "")).strip()

            # Parse numeric score to display as X.XX / 3 but show original hint label too
            score_value = _parse_score_hint(score_hint_raw)
            score_str = _score_display(score_value)
            if score_str != "N/A":
                heading_text = f"{pillar_name} — {score_str} / 3"
            else:
                heading_text = pillar_name

            if score_hint_raw:
                heading_text = f"{heading_text} ({score_hint_raw})"

            story.append(Paragraph(xml_escape(heading_text), styles["SubHeading"]))
            if summary_text:
                story.append(_safe_paragraph(summary_text, styles["BodyText"]))
            else:
                story.append(_safe_paragraph("No narrative summary provided for this pillar.", styles["BodyText"]))

            story.append(Spacer(1, 6))

        story.append(Spacer(1, 6))

    # ─────────────────────────────────────────────────────────────────────
    # By Production / Programme – narrative
    # ─────────────────────────────────────────────────────────────────────
    production_summaries = ai_result.get("production_summaries", []) or []
    if production_summaries:
        story.append(Paragraph("By Production / Programme", styles["SectionHeading"]))

        for prod in production_summaries:
            if not isinstance(prod, dict):
                continue

            pname = _to_plain_text(prod.get("production") or "General").strip() or "General"
            story.append(Paragraph(xml_escape(pname), styles["SubHeading"]))

            pillars = prod.get("pillars") or []
            for ps in pillars:
                if not isinstance(ps, dict):
                    continue

                pillar_name = _to_plain_text(ps.get("pillar", "Category")).strip() or "Category"
                score_hint = _to_plain_text(ps.get("score_hint", "")).strip()
                summary_text = _to_plain_text(ps.get("summary", "")).strip()

                label_parts = [pillar_name]
                if score_hint:
                    label_parts.append(score_hint)
                label_text = " — ".join(label_parts)

                story.append(Paragraph(xml_escape(label_text), styles["SubHeadingSmall"]))
                if summary_text:
                    story.append(_safe_paragraph(summary_text, styles["BodyText"]))
                else:
                    story.append(_safe_paragraph("No summary provided.", styles["BodyText"]))

            story.append(Spacer(1, 8))

    # ─────────────────────────────────────────────────────────────────────
    # Risks, priorities, notes
    # ─────────────────────────────────────────────────────────────────────
    risks = [
        _to_plain_text(r).strip()
        for r in (ai_result.get("risks", []) or [])
        if _to_plain_text(r).strip()
    ]
    if risks:
        story.append(Paragraph("Key Risks / Concerns", styles["SectionHeading"]))
        for r in risks:
            story.append(_safe_paragraph(f"• {r}", styles["BodyText"]))

    priorities = [
        _to_plain_text(p).strip()
        for p in (ai_result.get("priorities_next_month", []) or [])
        if _to_plain_text(p).strip()
    ]
    if priorities:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Priorities for Next Month", styles["SectionHeading"]))
        for p in priorities:
            story.append(_safe_paragraph(f"• {p}", styles["BodyText"]))

    nfl = _to_plain_text(ai_result.get("notes_for_leadership", "")).strip()
    if nfl:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Notes for Leadership", styles["SectionHeading"]))
        story.append(_safe_paragraph(nfl, styles["BodyText"]))

    # ─────────────────────────────────────────────────────────────────────
    # Raw responses on a fresh page
    # ─────────────────────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Raw Scorecard Responses", styles["SectionHeading"]))
    story.append(Spacer(1, 6))
    story.append(_responses_table(questions, responses))

    # ─────────────────────────────────────────────────────────────────────
    # Footer (page x, label)
    # ─────────────────────────────────────────────────────────────────────
    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        width, height = doc_.pagesize
        canvas.drawString(36, 20, "Alberta Ballet — Monthly Scorecard")
        canvas.drawRightString(width - 36, 20, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
