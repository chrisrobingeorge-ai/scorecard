# ai_utils.py
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import pandas as pd
from app_config import OBJECTIVES_DF

def _get_openai_client():
    """
    Lazy-initialize the OpenAI client for SDK v1+.
    Reads API key from Streamlit secrets (preferred) or env.
    Raises RuntimeError with a helpful message if misconfigured.
    """
    # Try to read from Streamlit secrets if available
    api_key = None
    try:
        import streamlit as st  # lightweight import is fine
        api_key = st.secrets.get("OPENAI_API_KEY", None)
    except Exception:
        pass

    api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing OPENAI_API_KEY. Add it in Streamlit Secrets or as an environment variable."
        )

    # Import SDK v1+
    try:
        from openai import OpenAI
    except Exception as ie:
        raise RuntimeError(
            "OpenAI SDK not installed or too old. Add `openai>=1.51.0` to requirements.txt and redeploy."
        ) from ie

    return OpenAI(api_key=api_key)


def _is_empty_value(v: Any) -> bool:
    """Treat None or blank strings as empty; 0 or False are NOT empty."""
    if v is None:
        return True
    if isinstance(v, str) and v.strip() == "":
        return True
    return False


def _build_prompt(
    meta: Dict[str, Any],
    questions_df: pd.DataFrame,
    responses: Dict[str, Dict[str, Any]],
) -> str:
    """
    Build a minimal, structured input for the model.
    Skips questions that have no response and no notes.
    """
    items: List[Dict[str, Any]] = []

    for _, row in questions_df.iterrows():
        qid = str(row.get("question_id"))
        # Use question_text, else metric, else qid
        qtext = (row.get("question_text") or row.get("metric") or qid) or qid

        r = responses.get(qid) or {}
        primary = r.get("primary")
        notes = r.get("description")

        # Skip completely empty items so productions/programmes with no data are ignored
        if _is_empty_value(primary) and _is_empty_value(notes):
            continue

        # Normalise pillar and production labels
        pillar = str(row.get("strategic_pillar") or "").strip()
        # Prefer the per-answer production_title we built in app.py; fall back to any production column if present.
        production = str(row.get("production_title") or row.get("production") or "").strip()

        items.append(
            {
                "question_id": qid,
                "question": str(qtext),
                "response": primary,
                "notes": notes,
                "pillar": pillar,
                "production": production,
                "metric": str(row.get("metric") or ""),
                "type": str(row.get("response_type") or ""),
            }
        )

    payload = {"meta": meta, "items": items}

    dept_name = str(meta.get("department") or "this department")
    scope = str(meta.get("scope") or "").strip()
    if scope == "department_all_productions":
        scope_desc = f"for the entire {dept_name} department across all productions/programmes in the reporting period"
    else:
        scope_desc = f"for the {dept_name} department based only on the items provided"

    instruction = f"""
    You are an expert analyst preparing an executive summary of Alberta Ballet’s scorecard results {scope_desc}.

    CRITICAL SCOPE RULES:
    - You are analysing ONE department only: {dept_name}.
    - Do NOT assume you can see the whole organisation or other departments.
    - Do NOT invent additional departments or pillars that do not appear in the data.
    - Base everything strictly on the INPUT_JSON.

    Data fields:
    - Each item has:
      • pillar       (e.g., Innovation, Impact, Collaboration, Recruitment, Engagement, Financial, etc.)
      • production   (either blank, "General", or a human-facing production/programme name such as "Nijinsky",
                      "Once Upon a Time", "Community Programs", "Recreational Classes", etc.)
      • question, response, notes, metric, type.

    IMPORTANT ABOUT PRODUCTION LABELS:
    - The value of "production" is already the correct human-facing name to use.
    - When you return production names in production_summaries:
      • If production is non-empty, you MUST use it verbatim as the "production" value.
      • If production is empty, you may either:
        - Omit it from production_summaries entirely if there are no other production values, OR
        - Treat it as "General" when grouping general items alongside named productions.
    - Do NOT invent generic labels like "Productions this period" when explicit production names are present in the data.

    Grouping rules:
    - Use the content of "production" together with the text of responses/notes to decide how to group items.
    - If ALL production values are empty and you cannot infer any specific productions/programmes, then:
      • Set production_summaries to an empty array [].
      • Focus on pillar_summaries only.
    - For Artistic in particular:
      • Your goal is to produce a structure like:
          General → Recruitment, Engagement
          Once Upon a Time → Innovation, Impact, Collaboration, Financial
          Nijinsky → Innovation, Impact, Collaboration, Financial
        based on the productions you can detect in the text and the pillars attached to their items.

    Task:
    Analyse the provided scorecard data and produce a narrative summary for THIS department that includes:

    1) overall_summary (string):
       - High-level performance this period.
       - Major achievements and constructive challenges.

    2) production_summaries (array):
       - If there is at least some signal of productions/programmes:
         • For EACH identified production/programme (including a synthetic "General" if needed), create one object:
           {{
             "production": "<production or programme name, or 'General'>",
             "pillars": [
               {{
                 "pillar": "<pillar name>",
                 "score_hint": "<short hint like '2/3 – steady progress', '1/3 – needs improvement', or 'N/A – limited data'>",
                 "summary": "<2–4 sentences focused on THIS production/programme and THIS pillar>"
               }},
               ...
             ]
           }}
         • Ignore hypothetical productions/programmes for which there is effectively no data (no items).
       - If there are no productions/programmes in the data and you cannot infer any from the text:
         • Set production_summaries to an empty array [].

    3) pillar_summaries (array):
       - A department-wide, cross-cutting view by pillar, ignoring production:
         • For EACH distinct pillar actually present in the data, create:
           {{
             "strategic_pillar": "<pillar name>",
             "score_hint": "<short hint as above>",
             "summary": "<2–4 sentences summarising this pillar across the whole department>"
           }}
       - Do NOT mention pillars that are not present in the data.

    4) risks (array of strings):
       - Cross-cutting risks or concerns that affect THIS department.
       - Each entry is a short, clear sentence.

    5) priorities_next_month (array of strings):
       - 3–6 concrete priorities for THIS department for the coming month.
       - Each entry is a short, action-oriented sentence.

    6) notes_for_leadership (string):
       - A short paragraph with advice for the executive team focused on THIS department only.

    Output Contract (strict):
    - Respond with JSON only, no prose before or after.
    - Use exactly these keys at the top level:
      - overall_summary (string)
      - pillar_summaries (array of objects with keys: strategic_pillar, score_hint, summary)
      - production_summaries (array of objects with keys: production (string), pillars (array as specified above))
      - risks (array of strings)
      - priorities_next_month (array of strings)
      - notes_for_leadership (string)
    - Do not include markdown, backticks, comments, or any extra keys.
    - Base your output ONLY on INPUT_JSON.
    """

    user_content = f"{instruction}\n\nINPUT_JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    return user_content

def _build_prompt_objective_aware(
    meta: Dict[str, Any],
    questions_df: pd.DataFrame,
    responses: Dict[str, Dict[str, Any]],
) -> str:
    """
    Build a strategy-aware prompt by joining:
    - question metadata
    - responses (primary / description)
    - strategic objectives via primary_objective_id -> OBJECTIVES_DF
    """

    import textwrap

    # ── 1) Normalise question IDs and attach answers ─────────────────────────
    q_df = questions_df.copy()
    q_df["question_id"] = q_df["question_id"].astype(str)

    resp_rows = []
    for qid, ans in (responses or {}).items():
        resp_rows.append(
            {
                "question_id": str(qid),
                "answer_primary": ans.get("primary"),
                "answer_description": ans.get("description"),
            }
        )
    if resp_rows:
        resp_df = pd.DataFrame(resp_rows)
    else:
        resp_df = pd.DataFrame(columns=["question_id", "answer_primary", "answer_description"])

    merged = q_df.merge(resp_df, on="question_id", how="left")

    # ── 2) Join strategic objectives via primary_objective_id ────────────────
    if "primary_objective_id" in merged.columns and not OBJECTIVES_DF.empty:
        merged = merged.merge(
            OBJECTIVES_DF,
            left_on="primary_objective_id",
            right_on="objective_id",
            how="left",
            suffixes=("", "_obj"),
        )
    else:
        merged["objective_id"] = None
        merged["owner"] = None
        merged["objective_title"] = None
        merged["short_description"] = None

    dept = meta.get("department") or "Unknown department"

    # Fallback labels for any unmapped items
    merged["objective_id"] = merged["objective_id"].fillna("UNMAPPED")
    merged["objective_title"] = merged["objective_title"].fillna("Unmapped / unspecified objective")
    merged["owner"] = merged["owner"].fillna(dept)
    merged["short_description"] = merged["short_description"].fillna(
        "No strategic objective mapping was provided for these items."
    )

        # Ensure ai_weight exists and is numeric: 1=LOW, 2=MEDIUM, 3=HIGH
    if "ai_weight" in merged.columns:
        merged["ai_weight"] = pd.to_numeric(merged["ai_weight"], errors="coerce").fillna(2).astype(int)
    else:
        merged["ai_weight"] = 2  # default MEDIUM

    # ── 3) Build text grouped by strategic objective ─────────────────────────
    objective_blocks: list[str] = []

    for obj_id, group in merged.groupby("objective_id"):
        first = group.iloc[0]
        owner = str(first.get("owner") or "").strip()
        obj_title = str(first.get("objective_title") or "").strip()
        obj_desc = str(first.get("short_description") or "").strip()

        lines: list[str] = []
        header = f"Objective {obj_id} ({owner}): {obj_title}" if obj_title else f"Objective {obj_id} ({owner})"
        lines.append(header)
        if obj_desc:
            lines.append(f"Description: {obj_desc}")

        lines.append("Scorecard items and answers:")

        for _, row in group.iterrows():
            q_text = str(row.get("question_text") or "").strip()
            pillar = str(row.get("strategic_pillar") or "").strip()
            metric = str(row.get("metric") or "").strip()

            prod = str(row.get("production_title") or "").strip()
            if not prod and meta.get("production"):
                prod = str(meta["production"])

            ans_primary = row.get("answer_primary")
            ans_desc = row.get("answer_description")
            ans_primary_str = "" if ans_primary is None else str(ans_primary)
            ans_desc_str = "" if ans_desc is None else str(ans_desc)

            # Tag department-wide vs production-specific for the model
            if prod:
                scope_tag = "Production-specific"
            else:
                scope_tag = "DEPARTMENT-WIDE (not tied to a single production)"

            context_bits = [pillar or None, metric or None, prod or None, scope_tag]
            context_bits = [b for b in context_bits if b]
            context_label = " / ".join(context_bits) if context_bits else ""

            # Map ai_weight to an importance label
            w = int(row.get("ai_weight", 2) or 2)
            if w <= 1:
                importance = "LOW"
            elif w >= 3:
                importance = "HIGH"
            else:
                importance = "MEDIUM"

            line = q_text or f"Question ID {row.get('question_id')}"
            if context_label:
                line = f"[{context_label}] {line}"

            lines.append(f"- {line}")
            lines.append(f"  Importance: {importance} (ai_weight={w})")
            lines.append(f"  Primary answer: {ans_primary_str}")
            if ans_desc_str:
                lines.append(f"  Detail: {ans_desc_str}")

        objective_blocks.append("\n".join(lines))

    objectives_text = "\n\n".join(objective_blocks)

    # ── 4) Wrap in richer instructions for the model ────────────────────────
    period = meta.get("month") or ""
    scope = meta.get("scope") or (meta.get("production") or "current scope")

    prompt = textwrap.dedent(
        f"""
        You analyse Alberta Ballet's monthly scorecards.

        You are given questions, their answers, and their mapping to strategic objectives
        from the 2025–2030 strategic plan.

        **CRITICAL CONTEXT: This is a FIVE-YEAR strategic plan (2025–2030).**
        Each monthly scorecard is one snapshot in a multi-year transformation journey.
        Strategic initiatives are expected to unfold gradually over multiple years.
        Not everything needs to be accomplished at once, and absence of immediate progress
        on a particular objective in a given month is not necessarily a cause for concern.
        
        Different objectives will naturally progress at different paces:
        - Some may be in planning or foundation-building stages for months
        - Others may show bursts of activity followed by integration periods
        - Many will demonstrate steady, incremental progress rather than dramatic leaps
        
        Your assessment should reflect this reality. Avoid creating false urgency or suggesting
        that slow-and-steady progress is somehow inadequate. In strategic transformation work,
        patience and sustained effort over years are more valuable than rushed activity.
        
        Assess progress with patience and a long-term perspective.

        Reporting context:
        - Department: {dept}
        - Period: {period}
        - Scope: {scope}

        Your task is to produce a **deep, interpretive analysis**, not just a recap of answers.

        Please respond with a single valid JSON object with the following keys:

        1) "overall_summary":
           A **coherent narrative of 2–4 paragraphs**, written in prose (no bullet points).
           - Link explicitly to strategic objectives by ID and title (e.g., "ART1 – Elevate the Art of Dance").
           - Diagnose what seems **on track**, **mixed**, or **developing**, and why.
           - Frame progress in the context of a FIVE-YEAR strategic plan. Recognize that:
             • Some objectives are in early stages and may show limited activity this month—that's expected.
             • Strategic initiatives take time to mature; assess momentum and direction, not immediate completion.
             • Absence of progress in one month doesn't indicate failure—it may simply reflect timing or sequencing.
           - Go beyond restating answers: infer patterns, tensions, and trade-offs
             (e.g., strong innovation but recruitment building gradually; strong community impact with capacity developing).
           - Where evidence is thin or missing, acknowledge it neutrally—don't interpret lack of data as negative performance.
           - Avoid urgent or alarmist language. Prefer terms like "developing," "building momentum," "early stage," 
             "area to watch over time," rather than "at risk" or "needs immediate attention."
           - Do not assume that a production is weak in visual or artistic quality unless the answers explicitly indicate that. 
             Absence of evidence is not evidence of weakness.
           - **CRITICAL**: Focus your assessment primarily on HIGH-importance items (ai_weight=3), with MEDIUM items (ai_weight=2) 
             as supporting context. NEVER base strong negative conclusions primarily on LOW-importance items (ai_weight=1), 
             which are optional or seasonal signals meant only to add nuance.

        2) "pillar_summaries":
           An array of objects, each with:
             - "strategic_pillar": the pillar name (from the data)
             - "score_hint": a string in the form "<n>/3 label", where n is 0, 1, 2, or 3.
               Examples: "3/3 Strong progress", "2/3 Steady development", "1/3 Early stage", "0/3 Inactive this period".
             - "summary": a short paragraph (3–6 sentences).
        
           For each pillar, explain:
             - what the answers suggest about progress over the long term,
             - how this relates to specific strategic objectives and productions/programmes,
             - and any underlying causes or dependencies you can infer.
        
           Use the 0–3 scale with a multi-year perspective:
             - 3/3 only when evidence shows sustained, multi-dimensional progress toward long-term goals.
             - 2/3 as the default for steady development or work-in-progress—this is positive for a 5-year plan.
             - 1/3 when work is in early stages or building foundations—not necessarily a problem.
             - 0/3 only when there is clear evidence of inactivity or abandonment (rare in strategic work).
           
           Remember: In a 5-year plan, most objectives will show gradual, incremental progress month-to-month.
           A "2/3 Steady development" is a perfectly healthy status for strategic work in progress.

            Each scorecard item is also tagged with an "Importance" level derived from ai_weight:
             - Importance: HIGH  (ai_weight=3)   → core strategic levers.
             - Importance: MEDIUM (ai_weight=2) → important context.
             - Importance: LOW   (ai_weight=1)   → optional or seasonal signals.

           When drawing strong conclusions (especially 0/3 or 3/3):
             - Rely primarily on HIGH-importance items, supported by MEDIUM where helpful.
             - NEVER base a 0/3 or a harsh negative judgement solely on LOW-importance items
               such as festivals, residencies, or optional contemporary-issues content.
             - LOW-importance items should only colour the narrative (nuance, examples), not
               drive the overall assessment.


        3) "production_summaries":
           An array of objects, each with:
             - "production": the production/programme name (or "General")
             - "pillars": an array of objects with:
                 - "pillar": pillar name
                 - "score_hint": again in the form "<n>/3 label" using the same 0–3 scale.
                 - "summary" (2–4 sentences).
           Focus on **differences between productions/programmes** and what they imply
           for strategic objectives (e.g., one show strongly supports ART2 but not ART3).
           When comparing productions or programmes, do not let a single metric (e.g., reuse of assets, a missing collaboration, or one weak answer) completely dominate your judgment. Look across all available answers before calling a production clearly strong or weak for a given objective.
           
           **CRITICAL IMPORTANCE WEIGHTING FOR PRODUCTION SUMMARIES**:
           - When scoring productions/programmes, base your assessment primarily on HIGH-importance items (ai_weight=3), supported by MEDIUM-importance items (ai_weight=2).
           - NEVER lower a production's score or make harsh negative judgments based primarily or solely on LOW-importance items (ai_weight=1).
           - LOW-importance items (such as festival participation, artist residencies, or optional contemporary-issues questions) are seasonal/optional and should only add context or examples to your narrative—they must NOT drive the core assessment or scoring.

           Some questions are followed by "Why not?" explanations when the answer is "No".
           When these explanations indicate that the timing or artistic focus was intentional
           (e.g., "auditions are in spring", "this work is designed as a classic fairy-tale"),
           treat the "No" as neutral rather than negative. In these cases, you may note future
           opportunities, but do not mark the objective or production as off track solely
           because the activity did not occur this month.

           Some questions are marked as "DEPARTMENT-WIDE (not tied to a single production)".
           These describe the company or department overall (e.g., recruitment, auditions,
           contracts) and MUST NOT be treated as attributes of any specific production.
           When writing "production_summaries", completely ignore these questions for both
           scoring and narrative. Do not create pillars or comments in a production summary
           that are based on DEPARTMENT-WIDE items (for example, do NOT mention recruitment
           or "Build a World-Class Ballet Company" inside a specific production’s summary).
           You may refer to these items only in "overall_summary" and "pillar_summaries",
           using department-level language ("the company", "the department") rather than
           naming individual productions.

        4) "risks":
           An array of concise bullet-style strings labeled as "Areas to Watch" or "Considerations."
           These should identify **strategic considerations** worth monitoring over time, not immediate crises.
           In a 5-year plan, many initiatives will show variable progress month-to-month—that's normal.
           Only flag items that, if unaddressed over multiple periods, could impact long-term strategic success.
           Use measured language: "Worth monitoring," "Consider tracking," "May need attention over time."
           Avoid alarmist framing. Tie observations to specific objectives and, where relevant, to productions or pillars.
           **CRITICAL**: Base observations primarily on HIGH-importance items (ai_weight=3), supported by MEDIUM items (ai_weight=2). 
           Do NOT identify concerns based solely on LOW-importance items (ai_weight=1), which are optional or seasonal signals.

        5) "priorities_next_month":
           An array of concise, action-oriented bullet strings framed as "Next Steps in the Strategic Journey."
           Each item should represent a **logical next step** in advancing long-term objectives, recognizing that
           strategic work unfolds gradually. These are not urgent fixes but rather incremental progress points.
           Frame each priority as continuing momentum, building foundations, or advancing a strategic initiative.
           Reference the objective(s) each supports (e.g., "Continue building momentum on ART5 by...").
           Avoid language that suggests immediate pressure or crisis response.

        6) "notes_for_leadership":
           A **single narrative paragraph or two (4–8 sentences)** in prose (no bullets),
           written as if for the CEO and Board with a long-term strategic lens. Highlight:
             - the most important strategic signals from this month in the context of multi-year progress,
             - how this month's activities fit into the broader 5-year transformation journey,
             - any trade-offs or dependencies they should understand as strategic initiatives mature,
             - where sustained attention (not immediate crisis response) may support long-term success.
           Use measured, strategic language appropriate for guiding a multi-year transformation, 
           not language that creates false urgency or suggests immediate problems.

        Style guidelines:
        - Use clear, direct language suitable for a Board / senior leadership report.
        - Avoid generic consulting clichés ("leverage synergies", "unlock potential").
        - Do not simply repeat question text; instead, synthesise what the answers
          imply for strategy.
        - It is acceptable to point out unknowns, contradictions, or data gaps.

        Here is the scorecard data grouped by strategic objective:

        {objectives_text}
        """
    ).strip()

    return prompt

def interpret_scorecard(
    meta: Dict[str, Any],
    questions_df: pd.DataFrame,
    responses: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Call OpenAI to produce a structured interpretation of the scorecard.
    Returns a dict with keys that app.py expects.
    """

    # Build a strategy-aware prompt that joins questions + answers + objectives
    prompt = _build_prompt_objective_aware(meta, questions_df, responses)

    # Make the call
    try:
        client = _get_openai_client()
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior strategy analyst for Alberta Ballet. "
                        "You interpret monthly scorecards in the context of the 2025–2030 strategic plan—"
                        "a FIVE-YEAR journey of transformation. "
                        "Each monthly scorecard represents one step in a multi-year process. "
                        "Not everything needs to be accomplished immediately. "
                        "Your role is to assess incremental progress toward long-term goals, "
                        "recognizing that strategic initiatives unfold gradually over years. "
                        "Avoid creating false urgency around issues that are simply at early stages. "
                        "You produce deep, board-ready narrative summaries in JSON format."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        text = completion.choices[0].message.content if completion.choices else ""
        try:
            data = json.loads(text)
        except Exception:
            # Try to salvage JSON object if model returned text around it
            import re

            # ✅ back to the correct pattern: look for a single JSON object
            m = re.search(r"\{.*\}", text, re.S)
            data = json.loads(m.group(0)) if m else {}
    except Exception as e:
        # Propagate as RuntimeError so app.py can show a friendly message
        raise RuntimeError(str(e))
 
    # ── Optional safety filter: remove recruitment from production_summaries ──
    prod_summaries = data.get("production_summaries") or []
    cleaned_prod_summaries = []

    for prod in prod_summaries:
        if not isinstance(prod, dict):
            continue

        pillars = prod.get("pillars") or []
        cleaned_pillars = []
        for ps in pillars:
            if not isinstance(ps, dict):
                continue
            pillar_name = str(ps.get("pillar", "")).lower()

            # Strip anything clearly about recruitment / world-class company
            if "recruit" in pillar_name:
                continue
            if "build a world-class ballet company" in pillar_name:
                continue

            cleaned_pillars.append(ps)

        prod["pillars"] = cleaned_pillars
        cleaned_prod_summaries.append(prod)

    data["production_summaries"] = cleaned_prod_summaries

    # Normalize the output shape so app.py rendering is resilient
    return {
        "overall_summary": data.get("overall_summary", ""),
        "pillar_summaries": data.get("pillar_summaries", []) or [],
        "production_summaries": data.get("production_summaries", []) or [],
        "risks": data.get("risks", []) or [],
        "priorities_next_month": data.get("priorities_next_month", []) or [],
        "notes_for_leadership": data.get("notes_for_leadership", "") or "",
    }

from typing import List, Dict, Any
from textwrap import dedent


def _build_overall_prompt_for_board(dept_summaries: List[Dict[str, Any]]) -> str:
    """
    Build a single text prompt for an organisation-wide Board report
    from department-level summaries extracted in overall_scorecard_app.py.

    dept_summaries items are expected to look like:
    {
        "department": str,
        "month": str | None,
        "month_label": str | None,
        "overall_score": float | None,
        "pillar_scores": dict[str, float] | {},
        "summary_text": str,
        ...
    }
    """

    header = dedent(
        """
        You are a senior strategy analyst for Alberta Ballet. You interpret *cross-department*
        monthly scorecards in the context of the 2025–2030 strategic plan—a FIVE-YEAR
        journey of transformation.

        You will receive department-level scorecard summaries, each with:
        - Department name
        - Reporting month
        - Overall 0–3 score (higher is better)
        - Any available pillar scores (0–3)
        - A narrative summary produced from that department's detailed scorecard responses

        Using these inputs, write a single, integrated Board report that:

        1. Summarises overall organisational performance this month, referencing departments by name.
        2. Comments on progress against major strategic aims (e.g., artistic excellence, community impact,
           financial resilience, talent development), based on what you can infer from the departmental summaries.
        3. Identifies cross-cutting risks, tensions, or capacity constraints that the Board should be aware of.
        4. Highlights notable strengths, achievements, or momentum.
        5. Recommends 3–6 organisation-wide priorities for the next reporting period, phrased as clear actions
           (e.g., "Consolidate…", "Invest further in…", "Stabilise…").

        Write in a formal, Board-facing tone (not academic, not marketing copy). Assume the Board already knows
        the organisation well; you don't need to reintroduce Alberta Ballet, only to interpret this month's results.

        Here are the department summaries:
        ────────────────────────────────────────────────────────
        """
    ).strip()

    blocks: List[str] = []

    for ds in dept_summaries:
        dept = ds.get("department") or "Unknown department"
        month_label = ds.get("month_label") or ds.get("month") or "Reporting period not specified"
        overall_score = ds.get("overall_score")
        pillar_scores = ds.get("pillar_scores") or {}
        summary_text = (ds.get("summary_text") or "").strip()

        if pillar_scores:
            pillar_lines = [
                f"- {name}: {float(val):.2f} / 3"
                for name, val in pillar_scores.items()
                if isinstance(val, (int, float))
            ]
            pillar_block = "\n".join(pillar_lines)
        else:
            pillar_block = "(No explicit pillar scores provided.)"

        block = dedent(
            f"""
            === Department: {dept} ===
            Reporting period: {month_label}
            Overall score: {overall_score if overall_score is not None else 'N/A'} / 3
            Pillar scores:
            {pillar_block}

            Department summary:
            {summary_text or '[No summary text provided]'}
            ────────────────────────────────────────────────────────
            """
        ).strip()

        blocks.append(block)

    return header + "\n\n" + "\n\n".join(blocks)


def interpret_overall_scorecards(
    dept_summaries: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Call OpenAI to produce a structured, Board-facing interpretation
    of the *overall* monthly scorecard (across departments).

    Returns a dict shaped similarly to interpret_scorecard, so you can
    reuse patterns in your app and pdf_utils if you wish.
    """

    # Build the cross-department prompt
    prompt = _build_overall_prompt_for_board(dept_summaries)

    # Make the call – mirrors your interpret_scorecard pattern
    try:
        client = _get_openai_client()
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior strategy analyst for Alberta Ballet. "
                        "You interpret *cross-department* monthly scorecards in the context of the "
                        "2025–2030 strategic plan—a FIVE-YEAR journey of transformation. "
                        "Each monthly report represents one step in a multi-year process. "
                        "Not everything needs to be accomplished immediately. "
                        "Your role is to assess incremental progress toward long-term goals, "
                        "recognising that strategic initiatives unfold gradually over years. "
                        "Avoid creating false urgency around issues that are simply at early stages. "
                        "You produce deep, Board-ready narrative summaries in JSON format."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        text = completion.choices[0].message.content if completion.choices else ""
        try:
            data = json.loads(text)
        except Exception:
            import re

            # Same salvage pattern you use above: try to extract a JSON object
            m = re.search(r"\{.*\}", text, re.S)
            data = json.loads(m.group(0)) if m else {}
    except Exception as e:
        raise RuntimeError(str(e))

    # Normalise the output so the overall app can treat it like a scorecard-style result.
    # You can keep the keys the same as interpret_scorecard to make life easy.
    return {
        # This is your Board-level narrative:
        "overall_summary": data.get("overall_summary", ""),
        # Optionally allow the model to return sections like:
        #   { "organisation_pillars": [...], "cross_cutting_risks": [...], ... }
        "pillar_summaries": data.get("pillar_summaries", []) or [],
        "production_summaries": data.get("production_summaries", []) or [],
        "risks": data.get("risks", []) or [],
        "priorities_next_month": data.get("priorities_next_month", []) or [],
        "notes_for_leadership": data.get("notes_for_leadership", "") or "",
        # And, if you ever want to debug:
        "raw": data,
        "prompt": prompt,
    }

