# pdf_utils.py

from xml.sax.saxutils import escape as xml_escape

from io import BytesIO
from typing import Dict, Any

import json
import re
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
    """
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        # Join list items as separate paragraphs
        return "\n\n".join(_to_plain_text(v) for v in val)
    if isinstance(val, dict):
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
    """
    if text is None:
        text = ""
    s = _to_plain_text(text)
    if not allow_markup:
        s = xml_escape(s)
    return Paragraph(s, style)


def _strip_objective_codes(text: str) -> str:
    """
    Remove internal objective codes like ART1 / ART2 / ART3 and
    clean up some odd dash list framing.
    """
    if not text:
        return ""
    # Remove "(ART1)" style codes
    s = re.sub(r"\(ART[0-9]+\)", "", text)
    # Remove bare ART1 / ART2 tokens
    s = re.sub(r"\bART[0-9]+\b", "", s)
    # Replace en-dash bullet fragments " – " with a space
    s = s.replace(" – ", " ")
    # Normalise excess whitespace
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def _split_paragraphs(raw_value: Any) -> list[str]:
    """
    Split the exec summary into logical paragraphs.

    - If it's a list, treat each item as a paragraph.
    - If it's a string, split on blank lines; if none, split on single newlines.
    """
    # If AI returned a list of chunks
    if isinstance(raw_value, list):
        paras: list[str] = []
        for item in raw_value:
            txt = _strip_objective_codes(_to_plain_text(item)).strip()
            if txt:
                paras.append(txt)
        return paras

    # Otherwise treat as string
    text = _strip_objective_codes(_to_plain_text(raw_value or "")).replace("\r\n", "\n")
    if not text.strip():
        return []

    # First try splitting on blank lines
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(parts) > 1:
        return parts

    # Fall back to splitting on single newlines if there were no blank lines
    if "\n" in text:
        return [p.strip() for p in text.split("\n") if p.strip()]

    return [text.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# Score utilities
# ─────────────────────────────────────────────────────────────────────────────
def _parse_score_hint(score_hint: str | None) -> float | None:
    """Extract an approximate 0–3 score from a score_hint string."""
    if not score_hint:
        return None

    text = str(score_hint)
    frac_match = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", text)
    if frac_match:
        num = float(frac_match.group(1))
        den = float(frac_match.group(2))
        if den != 0:
            return max(0.0, min(3.0, (num / den) * 3))

    num_match = re.search(r"(\d+(?:\.\d+)?)", text)
    if num_match:
        value = float(num_match.group(1))
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
def _responses_table(questions: pd.DataFrame, responses: Dict[str, Any], styles) -> Table:
    """
    Build a 2-column table of metric vs response with wrapped text.
    """
    body_style = ParagraphStyle(
        name="TableBody",
        parent=styles["BodyText"],
        fontSize=8,
        leading=10,
    )

    data: list[list[Any]] = [
        [
            Paragraph("Pillar / Production / Metric", body_style),
            Paragraph("Response", body_style),
        ]
    ]

    for _, row in questions.sort_values("display_order").iterrows():
        qid = row["question_id"]
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

        label_p = Paragraph(xml_escape(label), body_style)
        value_p = Paragraph(xml_escape(value_str), body_style)
        data.append([label_p, value_p])

    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]

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
    styles.add(
        ParagraphStyle(
            name="ScoreValue",
            parent=styles["Title"],
            fontSize=14,
            leading=16,
        )
    )

    story: list[Flowable] = []

    # ─────────────────────────────────────────────────────────────────────
    # Header: logo, title, total score
    # ─────────────────────────────────────────────────────────────────────
    reporting_period = meta.get("month", "")  # still coming in as 'month' from upstream
    department = meta.get("department", "") or "—"

    pillar_summaries = [ps for ps in (ai_result.get("pillar_summaries") or []) if isinstance(ps, dict)]
    scores = [_parse_score_hint(ps.get("score_hint")) for ps in pillar_summaries]
    scores = [s for s in scores if s is not None]
    total_score = sum(scores) / len(scores) if scores else None

    total_colour = _score_to_colour(total_score)
    total_score_display = _score_display(total_score)
    total_value = f"{total_score_display} / 3" if total_score_display != "N/A" else "Not rated"

    total_table = Table(
        [
            [Paragraph("<b>Total score</b>", styles["Small"])],
            [Paragraph(total_value, styles["ScoreValue"])],
        ],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), total_colour),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.white if total_score is not None else colors.black),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        ),
        colWidths=[1.7 * inch],
        rowHeights=[0.28 * inch, 0.45 * inch],
    )

    # Meta info: only Department + Reporting period
    meta_rows = [
        [
            Paragraph("DEPARTMENT", styles["MetaLabel"]),
            Paragraph(str(department), styles["MetaValue"]),
        ],
        [
            Paragraph("REPORTING PERIOD", styles["MetaLabel"]),
            Paragraph(str(reporting_period) if reporting_period else "—", styles["MetaValue"]),
        ],
    ]

    meta_table = Table(
        meta_rows,
        colWidths=[1.7 * inch, 3.0 * inch],
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

    # Logo
    logo_flowable: Flowable | None = None
    if logo_path:
        try:
            img = Image(logo_path)
            img._restrictSize(1.5 * inch, 1.5 * inch)  # larger logo
            logo_flowable = img
        except Exception:
            logo_flowable = None

    # Title block: just "Summary Scorecard"
    title_table = Table(
        [[Paragraph("Summary Scorecard", styles["ScorecardTitle"])]],
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

    header_cells: list[Flowable] = []
    if logo_flowable:
        header_cells.append(logo_flowable)
    else:
        header_cells.append(Spacer(0.5 * inch, 0.5 * inch))

    header_cells.append(title_table)
    header_cells.append(total_table)

    header_table = Table(
        [header_cells],
        colWidths=[1.8 * inch, 3.5 * inch, 1.7 * inch],
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
    # Executive summary – preserve paragraphs
    # ─────────────────────────────────────────────────────────────────────
    overall_value = ai_result.get("overall_summary", "")
    paragraphs = _split_paragraphs(overall_value)

    if paragraphs:
        story.append(Paragraph("Executive Summary", styles["SectionHeading"]))
        for idx, para in enumerate(paragraphs):
            story.append(_safe_paragraph(para, styles["BodyText"]))
            if idx < len(paragraphs) - 1:
                story.append(Spacer(1, 4))
        story.append(Spacer(1, 10))

    # ─────────────────────────────────────────────────────────────────────
    # Strategic pillars – narrative
    # ─────────────────────────────────────────────────────────────────────
    if pillar_summaries:
        story.append(Paragraph("Strategic Pillars", styles["SectionHeading"]))

        for ps in pillar_summaries:
            pillar_name_raw = _to_plain_text(ps.get("strategic_pillar", "Pillar")).strip() or "Pillar"
            pillar_name = _strip_objective_codes(pillar_name_raw)

            score_hint_raw = _to_plain_text(ps.get("score_hint", "")).strip()
            score_hint_clean = _strip_objective_codes(score_hint_raw)

            summary_text_raw = _to_plain_text(ps.get("summary", "")).strip()
            summary_text = _strip_objective_codes(summary_text_raw)

            score_value = _parse_score_hint(score_hint_raw)
            score_str = _score_display(score_value)
            if score_str != "N/A":
                heading_text = f"{pillar_name} — {score_str} / 3"
            else:
                heading_text = pillar_name

            if score_hint_clean:
                heading_text = f"{heading_text} ({score_hint_clean})"

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

            pname_raw = _to_plain_text(prod.get("production") or "General").strip() or "General"
            pname = _strip_objective_codes(pname_raw)
            story.append(Paragraph(xml_escape(pname), styles["SubHeading"]))

            pillars = prod.get("pillars") or []
            for ps in pillars:
                if not isinstance(ps, dict):
                    continue

                pillar_name_raw = _to_plain_text(ps.get("pillar", "Category")).strip() or "Category"
                pillar_name = _strip_objective_codes(pillar_name_raw)

                score_hint_raw = _to_plain_text(ps.get("score_hint", "")).strip()
                score_hint_clean = _strip_objective_codes(score_hint_raw)

                summary_text_raw = _to_plain_text(ps.get("summary", "")).strip()
                summary_text = _strip_objective_codes(summary_text_raw)

                label_parts = [pillar_name]
                if score_hint_clean:
                    label_parts.append(score_hint_clean)
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
        _strip_objective_codes(_to_plain_text(r)).strip()
        for r in (ai_result.get("risks", []) or [])
        if _to_plain_text(r).strip()
    ]
    if risks:
        story.append(Paragraph("Key Risks / Concerns", styles["SectionHeading"]))
        for r in risks:
            story.append(_safe_paragraph(f"• {r}", styles["BodyText"]))

    priorities = [
        _strip_objective_codes(_to_plain_text(p)).strip()
        for p in (ai_result.get("priorities_next_month", []) or [])
        if _to_plain_text(p).strip()
    ]
    if priorities:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Priorities for Next Period", styles["SectionHeading"]))
        for p in priorities:
            story.append(_safe_paragraph(f"• {p}", styles["BodyText"]))

    nfl_raw = _to_plain_text(ai_result.get("notes_for_leadership", "")).strip()
    nfl = _strip_objective_codes(nfl_raw)
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
    story.append(_responses_table(questions, responses, styles))

    # ─────────────────────────────────────────────────────────────────────
    # Footer
    # ─────────────────────────────────────────────────────────────────────
    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        width, height = doc_.pagesize
        canvas.drawString(36, 20, "Alberta Ballet — Scorecard Report")
        canvas.drawRightString(width - 36, 20, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
