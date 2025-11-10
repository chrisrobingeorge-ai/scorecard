# pdf_utils.py

from io import BytesIO
from typing import Dict, Any

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


def _responses_table(questions: pd.DataFrame, responses: Dict[str, Any]):
    """
    Build a simple 2-column table of metric/question vs response.
    """
    data = [["Pillar / Production / Metric", "Response"]]
    for _, row in questions.sort_values("display_order").iterrows():
        qid = row["question_id"]
        label = f"{row.get('strategic_pillar', '')} / {row.get('production', '')} / {row.get('metric', '')}"
        value = responses.get(qid, "")
        data.append([label, str(value)])

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
    summary = ai_result.get("overall_summary", "")
    if summary:
        story.append(Paragraph("Overall Summary", styles["Heading2"]))
        for para in summary.split("\n\n"):
            if para.strip():
                story.append(Paragraph(para.strip(), styles["BodyText"]))
                story.append(Spacer(1, 6))
        story.append(Spacer(1, 12))

    # Pillar summaries
    pillar_summaries = ai_result.get("pillar_summaries", []) or []
    if pillar_summaries:
        story.append(Paragraph("By Strategic Pillar", styles["Heading2"]))
        for ps in pillar_summaries:
            heading = f"{ps.get('strategic_pillar', 'Pillar')} — {ps.get('score_hint', '')}"
            story.append(Paragraph(heading, styles["Heading4"]))
            story.append(Paragraph(ps.get("summary", ""), styles["BodyText"]))
            story.append(Spacer(1, 6))
        story.append(Spacer(1, 12))

    # Risks
    risks = ai_result.get("risks", []) or []
    if risks:
        story.append(Paragraph("Key Risks / Concerns", styles["Heading2"]))
        for r in risks:
            story.append(Paragraph(f"• {r}", styles["BodyText"]))
        story.append(Spacer(1, 12))

    # Priorities
    priorities = ai_result.get("priorities_next_month", []) or []
    if priorities:
        story.append(Paragraph("Priorities for Next Month", styles["Heading2"]))
        for p in priorities:
            story.append(Paragraph(f"• {p}", styles["BodyText"]))
        story.append(Spacer(1, 12))

    # Notes for leadership
    nfl = ai_result.get("notes_for_leadership", "")
    if nfl:
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
