# pdf_utils.py

from __future__ import annotations

from io import BytesIO
from typing import Dict, Any
from datetime import datetime
import json
import re

import pandas as pd
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    Flowable,
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app_config import OBJECTIVES_DF

JSON_PREFIX = "AB_SCORECARD_JSON:"

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
        return "\n\n".join(_to_plain_text(v) for v in val)
    if isinstance(val, dict):
        if "text" in val and isinstance(val["text"], str):
            return val["text"]
        try:
            return json.dumps(val, ensure_ascii=False, indent=2)
        except Exception:
            return str(val)
    return str(val)

def _build_embed_payload(
    meta: Dict[str, Any],
    questions_df: pd.DataFrame,
    ai_summary_text: str,
    overall_score: float | None = None,
    pillar_scores: Dict[str, float] | None = None,
    question_scores: Dict[str, float] | None = None,
) -> str:
    """
    Build the JSON object we embed into the PDF metadata.

    - `meta` is the same dict you already pass around (month, department, etc.)
    - `questions_df` is your question/answer table (we expect response_value to be included)
    - `ai_summary_text` is the main AI narrative text
    - overall_score / pillar_scores / question_scores can be passed explicitly
      (e.g. from AI header scoring). If they are None/empty, we fall back to
      deriving from a numeric 'score' column on questions_df, if present.
    """

    # Start from explicit scores if provided
    overall_score_val: float | None = overall_score
    pillar_scores_val: Dict[str, float] = dict(pillar_scores or {})
    question_scores_val: Dict[str, float] = dict(question_scores or {})

    # If no explicit scores, fall back to numeric 'score' column (if present)
    if overall_score_val is None and "score" in questions_df.columns:
        try:
            overall_score_val = float(questions_df["score"].mean())
        except Exception:
            overall_score_val = None

    if not pillar_scores_val and "strategic_pillar" in questions_df.columns and "score" in questions_df.columns:
        try:
            pillar_scores_val = (
                questions_df
                .groupby("strategic_pillar")["score"]
                .mean()
                .to_dict()
            )
        except Exception:
            pillar_scores_val = {}

    if not question_scores_val and "question_id" in questions_df.columns and "score" in questions_df.columns:
        try:
            question_scores_val = (
                questions_df.set_index("question_id")["score"].to_dict()
            )
        except Exception:
            question_scores_val = {}

    payload = {
        "schema_version": 1,
        "app_name": "ab_monthly_scorecard",
        "payload_type": "monthly_scorecard_pdf",
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "meta": meta,
        "scores": {
            "overall_score": overall_score_val,
            "pillar_scores": pillar_scores_val,
            "question_scores": question_scores_val,
        },
        "questions": questions_df.to_dict(orient="records"),
        "ai_interpretation": {
            "overall_summary": ai_summary_text,
        },
    }

    # Minified JSON to keep the Subject field shorter
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


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
    Split narrative into logical paragraphs.

    Priority:
    1) If value is a list: each item -> paragraph.
    2) If string: split on blank lines.
    3) If still one block: split into chunks of ~3 sentences.
    """
    # List case: treat each as paragraph
    if isinstance(raw_value, list):
        paras: list[str] = []
        for item in raw_value:
            txt = _strip_objective_codes(_to_plain_text(item)).strip()
            if txt:
                paras.append(txt)
        return paras

    # String case
    text = _strip_objective_codes(_to_plain_text(raw_value or "")).replace("\r\n", "\n")
    if not text.strip():
        return []

    # Try blank-line split first
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(parts) > 1:
        return parts

    # If we have single newlines, allow those to break paragraphs
    if "\n" in text:
        parts = [p.strip() for p in text.split("\n") if p.strip()]
        if len(parts) > 1:
            return parts

    # Fallback: sentence-based chunking (group ~3 sentences per paragraph)
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if len(sentences) <= 3:
        return [" ".join(sentences)] if sentences else []

    paras: list[str] = []
    chunk: list[str] = []
    for s in sentences:
        chunk.append(s)
        if len(chunk) >= 3:
            paras.append(" ".join(chunk))
            chunk = []
    if chunk:
        paras.append(" ".join(chunk))
    return paras


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
        fontName="Helvetica",
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
        hAlign="LEFT",
    )
    table.setStyle(TableStyle(style_cmds))
    return table

def build_strategic_index_appendix():
    """
    Build an appendix section (Appendix A) showing the strategic objectives index,
    excluding the 'plan_anchor' column.
    Returns a list of ReportLab flowables (PageBreak + heading + table).
    """
    styles = getSampleStyleSheet()
    heading_style = styles["Heading2"]
    body_style = styles["BodyText"]

    df = OBJECTIVES_DF.copy()

    # If nothing is configured, return a simple notice instead
    if df.empty:
        return [
            PageBreak(),
            Paragraph("Appendix A — Strategic Objectives Index", heading_style),
            Spacer(1, 0.2 * inch),
            Paragraph("No strategic objectives index is currently configured.", body_style),
        ]

    # Drop plan_anchor if present
    if "plan_anchor" in df.columns:
        df = df.drop(columns=["plan_anchor"])

    # Reorder columns for readability, only if they exist
    preferred_order = ["owner", "objective_id", "objective_title", "short_description"]
    columns = [c for c in preferred_order if c in df.columns]
    if columns:
        df = df[columns]

    # Header row + data rows, with wrapped Paragraph cells
    header_labels = [col.replace("_", " ").title() for col in df.columns]

    # Smaller table style for readability
    cell_style = ParagraphStyle(
        name="ObjectivesCell",
        parent=body_style,
        fontSize=8,
        leading=10,
    )
    header_style = ParagraphStyle(
        name="ObjectivesHeaderCell",
        parent=body_style,
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
    )

    # Build header row with Paragraphs
    header = [Paragraph(xml_escape(label), header_style) for label in header_labels]

    # Build data rows with Paragraphs so long text wraps
    data = [header]
    for _, row in df.iterrows():
        cells = []
        for val in row.tolist():
            text = "" if val is None else str(val)
            cells.append(Paragraph(xml_escape(text), cell_style))
        data.append(cells)

    table = Table(
        data,
        colWidths=[
            1.4 * inch,  # owner
            1.0 * inch,  # objective_id
            2.4 * inch,  # objective_title
            3.0 * inch,  # short_description
        ][: len(df.columns)],  # trim if fewer columns
        repeatRows=1,
    )


    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )

    return [
        PageBreak(),
        Paragraph("Appendix A — Strategic Objectives Index", heading_style),
        Spacer(1, 0.2 * inch),
        table,
    ]

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

    - Preserves your "Strategic Summary Scorecard" layout (header, executive summary,
      pillars, by production, risks/priorities, raw responses).
    - Embeds a JSON payload in the PDF metadata (Subject) including:
      * meta
      * questions (+ response_value)
      * AI overall summary
      * overall_score and pillar_scores derived from pillar_summaries.
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

    # ─────────────────────────────────────────────────────────────────────
    # Styles (your originals)
    # ─────────────────────────────────────────────────────────────────────
    styles.add(
        ParagraphStyle(
            name="ScorecardTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=26,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="MetaLabel",
            parent=styles["Normal"],
            fontName="Helvetica",
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
            fontName="Helvetica",
            fontSize=10,
            leading=12,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionHeading",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=14,
            spaceBefore=12,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SubHeading",
            parent=styles["Heading3"],
            fontName="Helvetica-Bold",
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
            fontName="Helvetica-Bold",
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
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=16,
        )
    )
    # Body style with explicit Helvetica (no italics)
    styles.add(
        ParagraphStyle(
            name="ReportBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=13,
        )
    )

    story: list[Flowable] = []

    # ─────────────────────────────────────────────────────────────────────
    # AI summary text (for layout + JSON)
    # ─────────────────────────────────────────────────────────────────────
    overall_value = ai_result.get("overall_summary", "") or ""
    ai_summary_text = _to_plain_text(overall_value)

    # ─────────────────────────────────────────────────────────────────────
    # Derive scores from pillar_summaries (same source as your header box)
    # ─────────────────────────────────────────────────────────────────────
    pillar_summaries = [ps for ps in (ai_result.get("pillar_summaries") or []) if isinstance(ps, dict)]

    score_values: list[float] = []
    pillar_score_map: Dict[str, float] = {}

    for ps in pillar_summaries:
        pillar_key = _to_plain_text(ps.get("strategic_pillar", "")).strip()
        score_val = _parse_score_hint(ps.get("score_hint", ""))

        if score_val is not None:
            score_values.append(score_val)

        if pillar_key and score_val is not None:
            # Use the raw strategic_pillar name as key so it matches questions
            pillar_score_map[pillar_key] = score_val

    total_score = sum(score_values) / len(score_values) if score_values else None

    # ─────────────────────────────────────────────────────────────────────
    # Enrich questions with response_value + pillar_score for JSON payload
    # ─────────────────────────────────────────────────────────────────────
    questions_for_payload = questions.copy()

    resp_values: list[str] = []
    pillar_scores_for_rows: list[float | None] = []
    overall_scores_for_rows: list[float | None] = []

    for _, row in questions_for_payload.iterrows():
        qid = row.get("question_id")
        qid_str = str(qid)

        raw_val = responses.get(qid_str, responses.get(qid, ""))

        # Same normalisation logic as _responses_table
        if isinstance(raw_val, dict):
            primary = raw_val.get("primary", "")
            desc = raw_val.get("description", "")
            if desc:
                if primary:
                    value_str = f"{primary} — {desc}"
                else:
                    value_str = desc
            else:
                value_str = str(primary)
        else:
            value_str = "" if raw_val is None else str(raw_val)

        resp_values.append(value_str)

        # Match this question’s pillar to the pillar_score_map we built above
        sp_key_raw = row.get("strategic_pillar", "")
        sp_key = _to_plain_text(sp_key_raw).strip()
        pillar_scores_for_rows.append(pillar_score_map.get(sp_key))

        # Every row from this PDF shares the same overall_score
        overall_scores_for_rows.append(total_score)

    questions_for_payload["response_value"] = resp_values
    questions_for_payload["pillar_score"] = pillar_scores_for_rows
    questions_for_payload["overall_score"] = overall_scores_for_rows


    # ─────────────────────────────────────────────────────────────────────
    # Build embedded JSON payload (meta + questions + scores + summary)
    # ─────────────────────────────────────────────────────────────────────
    embed_json_str = _build_embed_payload(
        meta=meta,
        questions_df=questions_for_payload,
        ai_summary_text=ai_summary_text,
        overall_score=total_score,
        pillar_scores=pillar_score_map,
        # No per-question numeric scores yet
        question_scores=None,
    )

    # ─────────────────────────────────────────────────────────────────────
    # Header: logo, title, total score (your original layout)
    # ─────────────────────────────────────────────────────────────────────
    reporting_period = meta.get("month", "")
    department = meta.get("department", "") or "—"

    total_colour = _score_to_colour(total_score)
    total_score_display = _score_display(total_score)
    total_value = f"{total_score_display} / 3" if total_score_display != "N/A" else "Not rated"

    total_table = Table(
        [
            [Paragraph("<b>Total score</b>", styles["MetaLabel"])],
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

    # Meta info: Department + Reporting period, left-aligned
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
        colWidths=[1.9 * inch, 3.0 * inch],
        hAlign="LEFT",
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
            img._restrictSize(2 * inch, 2 * inch)
            logo_flowable = img
        except Exception:
            logo_flowable = None

    # Title block
    title_table = Table(
        [[Paragraph("Strategic Summary Scorecard", styles["ScorecardTitle"])]],
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
        colWidths=[2.0 * inch, 4.0 * inch, 1.5 * inch],
        hAlign="LEFT",
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (0, 0), -4),
                ("RIGHTPADDING", (0, 0), (0, 0), 6),
                ("LEFTPADDING", (1, 0), (1, 0), 0),
                ("RIGHTPADDING", (1, 0), (1, 0), 12),
                ("LEFTPADDING", (2, 0), (2, 0), 6),
                ("RIGHTPADDING", (2, 0), (2, 0), 0),
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
    paragraphs = _split_paragraphs(overall_value)

    if paragraphs:
        story.append(Paragraph("Executive Summary", styles["SectionHeading"]))
        for idx, para in enumerate(paragraphs):
            story.append(_safe_paragraph(para, styles["ReportBody"]))
            if idx < len(paragraphs) - 1:
                story.append(Spacer(1, 4))
        story.append(Spacer(1, 10))

    # ─────────────────────────────────────────────────────────────────────
    # Strategic pillars – narrative
    # ─────────────────────────────────────────────────────────────────────
    if pillar_summaries:
        # For School, make the section heading explicitly about the three streams
        dept_lower = str(department).lower()
        if "school" in dept_lower:
            section_label = (
                "School Streams "
                "(Classical Training / Attracting Students / Student Accessibility)"
            )
        else:
            section_label = "Strategic Pillars"

        story.append(Paragraph(section_label, styles["SectionHeading"]))

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
                for p in _split_paragraphs(summary_text):
                    story.append(_safe_paragraph(p, styles["ReportBody"]))
            else:
                story.append(
                    _safe_paragraph(
                        "No narrative summary provided for this pillar.",
                        styles["ReportBody"],
                    )
                )

            story.append(Spacer(1, 6))

        story.append(Spacer(1, 6))

    # ─────────────────────────────────────────────────────────────────────
    # By Production / Programme
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
            summaries: list[str] = []
            for ps in pillars:
                if not isinstance(ps, dict):
                    continue
                summary_text_raw = _to_plain_text(ps.get("summary", "")).strip()
                summary_text = _strip_objective_codes(summary_text_raw)
                if summary_text:
                    summaries.append(summary_text)

            combined = " ".join(summaries).strip()
            if combined:
                combined_paras = _split_paragraphs(combined)
                for p in combined_paras:
                    story.append(_safe_paragraph(p, styles["ReportBody"]))
            else:
                story.append(_safe_paragraph("No summary provided.", styles["ReportBody"]))

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
            story.append(_safe_paragraph(f"• {r}", styles["ReportBody"]))

    priorities = [
        _strip_objective_codes(_to_plain_text(p)).strip()
        for p in (ai_result.get("priorities_next_month", []) or [])
        if _to_plain_text(p).strip()
    ]
    if priorities:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Priorities for Next Period", styles["SectionHeading"]))
        for p in priorities:
            story.append(_safe_paragraph(f"• {p}", styles["ReportBody"]))

    nfl_raw = _to_plain_text(ai_result.get("notes_for_leadership", "")).strip()
    nfl = _strip_objective_codes(nfl_raw)
    if nfl:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Notes for Leadership", styles["SectionHeading"]))
        for p in _split_paragraphs(nfl):
            story.append(_safe_paragraph(p, styles["ReportBody"]))

    # ─────────────────────────────────────────────────────────────────────
    # Raw responses on a fresh page
    # ─────────────────────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Raw Scorecard Responses", styles["SectionHeading"]))
    story.append(Spacer(1, 6))
    story.append(_responses_table(questions, responses, styles))

    # ─────────────────────────────────────────────────────────────────────
    # Footer + metadata (JSON in Subject)
    # ─────────────────────────────────────────────────────────────────────
    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        width, height = doc_.pagesize
        canvas.drawString(36, 20, "Alberta Ballet — Scorecard Report")
        canvas.drawRightString(width - 36, 20, f"Page {doc_.page}")

        pdf_title = f"Strategic Summary Scorecard — {department}"
        canvas.setTitle(pdf_title)
        canvas.setAuthor(str(meta.get("staff_name") or ""))
        canvas.setSubject(JSON_PREFIX + embed_json_str)

        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes

def build_overall_board_pdf(
    reporting_label: str,
    dept_overview: pd.DataFrame,
    ai_result: Dict[str, Any],
    logo_path: str | None = None,
) -> bytes:
    """
    Build a Board-facing PDF for the overall monthly scorecard.

    - reporting_label: e.g. "November 2025" or "2025-11"
    - dept_overview: DataFrame with at least columns:
        ["department", "month_label", "overall_score"]
    - ai_result: the dict returned by interpret_overall_scorecards(...)
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

    # Reuse / parallel your existing style language
    styles.add(
        ParagraphStyle(
            name="BoardTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BoardMetaLabel",
            parent=styles["Normal"],
            fontName="Helvetica",
            textColor=colors.grey,
            fontSize=9,
            leading=11,
            spaceAfter=1,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BoardMetaValue",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=12,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BoardSectionHeading",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=14,
            spaceBefore=12,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BoardBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=14,
        )
    )

    story: list[Flowable] = []

    # ── Header: logo + title (no reporting period in the table) ─────────────
    logo_flowable: Flowable | None = None
    if logo_path:
        try:
            img = Image(logo_path)
            img._restrictSize(2 * inch, 2 * inch)
            logo_flowable = img
        except Exception:
            logo_flowable = None

    header_cells: list[Flowable] = []
    if logo_flowable:
        header_cells.append(logo_flowable)
    else:
        header_cells.append(Spacer(0.5 * inch, 0.5 * inch))

    header_cells.append(Paragraph("Strategic Summary Scorecard", styles["BoardTitle"]))

    # Two-column header: logo + title only, full width = 7.5"
    header_table = Table(
        [header_cells],
        colWidths=[2.0 * inch, 5.5 * inch],
        hAlign="LEFT",
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (0, 0), -4),
                ("RIGHTPADDING", (0, 0), (0, 0), 6),
                ("LEFTPADDING", (1, 0), (1, 0), 0),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        ),
    )

    story.append(header_table)
    story.append(Spacer(1, 6))

    # ── Reporting period: left-aligned, below header ────────────────────────
    if reporting_label:
        story.append(Paragraph("REPORTING PERIOD", styles["BoardMetaLabel"]))
        story.append(Paragraph(str(reporting_label), styles["BoardMetaValue"]))
        story.append(Spacer(1, 12))

    # ─────────────────────────────────────────────────────────────────────
    # Departments overview table
    # ─────────────────────────────────────────────────────────────────────
    if not dept_overview.empty:
        story.append(Paragraph("Departments included", styles["BoardSectionHeading"]))

        display_cols = ["department", "month_label", "overall_score"]
        display_cols = [c for c in display_cols if c in dept_overview.columns]

        table_data = [
            [col.replace("_", " ").title() for col in display_cols]
        ]

        for _, row in dept_overview[display_cols].iterrows():
            table_data.append([str(row.get(c, "")) for c in display_cols])

        table = Table(
            table_data,
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
                    ("ALIGN", (0, 0), (-1, 0), "LEFT"),

                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 1), (-1, -1), 9),
                    ("VALIGN", (0, 1), (-1, -1), "TOP"),

                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ]
            ),
            hAlign="LEFT",
        )
        story.append(table)
        story.append(Spacer(1, 12))

    # ─────────────────────────────────────────────────────────────────────
    # Main Board narrative
    # ─────────────────────────────────────────────────────────────────────
    story.append(Paragraph("Board Narrative", styles["BoardSectionHeading"]))

    overall_text = (ai_result.get("overall_summary") or "").strip()

    if not overall_text:
        story.append(Paragraph("No Board report text was generated.", styles["BoardBody"]))
    else:
        text = overall_text.replace("\r\n", "\n")
        parts = [p.strip() for p in text.split("\n\n") if p.strip()]
        for idx, para in enumerate(parts):
            story.append(Paragraph(para, styles["BoardBody"]))
            if idx < len(parts) - 1:
                story.append(Spacer(1, 6))

    # ─────────────────────────────────────────────────────────────────────
    # Strategic Pillar risks / concerns
    # ─────────────────────────────────────────────────────────────────────
    risks = ai_result.get("risks") or []
    if risks:
        story.append(Spacer(1, 10))
        story.append(Paragraph("Strategic Pillar – Risks / Concerns", styles["BoardSectionHeading"]))
        for r in risks:
            story.append(Paragraph(f"• {str(r)}", styles["BoardBody"]))

    # Organisation-wide priorities
    priorities = ai_result.get("priorities_next_month") or []
    if priorities:
        story.append(Spacer(1, 10))
        story.append(Paragraph("Organisation-wide Priorities for Next Period", styles["BoardSectionHeading"]))
        for p in priorities:
            story.append(Paragraph(f"• {str(p)}", styles["BoardBody"]))

    # Notes for leadership
    notes = (ai_result.get("notes_for_leadership") or "").strip()
    if notes:
        story.append(Spacer(1, 10))
        story.append(Paragraph("Notes for Leadership", styles["BoardSectionHeading"]))
        parts = [p.strip() for p in notes.replace("\r\n", "\n").split("\n\n") if p.strip()]
        for idx, para in enumerate(parts):
            story.append(Paragraph(para, styles["BoardBody"]))
            if idx < len(parts) - 1:
                story.append(Spacer(1, 4))

    # ─────────────────────────────────────────────────────────────────────
    # Appendix A — Strategic Objectives Index
    # ─────────────────────────────────────────────────────────────────────
    story.extend(build_strategic_index_appendix())

    # Footer with page numbers
    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        width, height = doc_.pagesize
        canvas.drawString(36, 20, "Alberta Ballet — Overall Monthly Scorecard")
        canvas.drawRightString(width - 36, 20, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes

