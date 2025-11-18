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
    - strategic objectives via strategic_objectives_id -> OBJECTIVES_DF
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

    # ── 2) Join strategic objectives via strategic_objectives_id ────────────────
    if "strategic_objectives_id" in merged.columns and not OBJECTIVES_DF.empty:
        merged = merged.merge(
            OBJECTIVES_DF,
            left_on="strategic_objectives_id",
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

    # ── 4) Build objective inventory for output structure ──────────────
    # Collect unique strategic objectives present in the data
    objectives_present = []
    seen_obj_ids = set()
    for obj_id, group in merged.groupby("objective_id"):
        if obj_id == "UNMAPPED":
            continue
        if obj_id not in seen_obj_ids:
            first = group.iloc[0]
            objectives_present.append({
                "objective_id": str(obj_id),
                "objective_title": str(first.get("objective_title") or "").strip(),
                "owner": str(first.get("owner") or "").strip(),
            })
            seen_obj_ids.add(obj_id)
    
    objectives_list_text = ", ".join([f"{o['objective_id']} ({o['objective_title']})" for o in objectives_present]) if objectives_present else "none"

    dept_lower = str(dept).lower()
    school_extra = ""
    if "school" in dept_lower and objectives_present:
        # For the School department, make the structure very explicit
        school_extra = (
            "For this School department, you MUST treat each strategic objective as a distinct stream of work.\\n"
            f"The objectives you must use are: {objectives_list_text}.\\n"
            "You MUST return one and only one 'objective_summaries' entry for EACH of these objective IDs.\\n"
            "Do not invent new objective IDs and do not merge them into a single generic objective.\\n"
            "In your 'overall_summary', start with a short integrative paragraph about the School overall,\\n"
            "then include one paragraph for EACH of these objectives, clearly signposted in the narrative.\\n"
            "Where evidence is thin for an objective, say so neutrally rather than assuming poor performance.\\n"
        )

    # ── 5) Wrap in richer instructions for the model ────────────────────────
    period = meta.get("month") or ""
    scope = meta.get("scope") or (meta.get("production") or "current scope")

    prompt = textwrap.dedent(
        f"""
        You analyse Alberta Ballet's monthly scorecards.

        You are given questions, their answers, and their mapping to strategic objectives
        from the 2025–2030 strategic plan.

        COMPREHENSIVENESS MANDATE:
        Your primary responsibility is to ensure that the information gathered through the scorecard
        process is preserved and communicated effectively in your analysis. Many questions have been
        answered by staff, and it is critical that these answers are reflected in your summaries,
        not lost through over-aggressive abstraction. When in doubt, include more detail rather than
        less, while still maintaining clear, professional prose suitable for Board review.
        
        Be particularly attentive to:
        - Specific metrics, numbers, or data points provided in answers
        - Follow-up questions (identified by "Detail:" lines) that provide important context
        - Activities, partnerships, or initiatives mentioned in responses
        - Challenges, barriers, or concerns explicitly stated by respondents
        - Plans, intentions, or next steps described in the responses
        
        Your summaries should demonstrate that you have carefully reviewed ALL the answered questions
        and incorporated their key content, not just sampled or cherry-picked a few.

        CRITICAL CONTEXT: This is a FIVE-YEAR strategic plan (2025–2030).
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

        The strategic objectives present in this department's data are:
        {objectives_list_text}

        IMPORTANT: Strategic objectives (e.g., ART1, ART2, SCH1, COM1) are the actual strategic goals from 
        the 2025-2030 plan. Do NOT confuse these with organizational categories like "Innovation", 
        "Collaboration", or "Recruitment" which are just ways questions are grouped.

        For ALL departments:
        - You MUST return one 'objective_summaries' entry for EACH strategic objective ID listed above.
        - Do not invent new objective IDs and do not merge these objectives.
        - If no objectives are present, return an empty list for 'objective_summaries'.

        {school_extra}

        Your task is to produce a deep, interpretive analysis as a single JSON object
        with exactly these keys:
        - "overall_summary" (string)
        - "objective_summaries" (array of objects)
        - "production_summaries" (array of objects)
        - "risks" (array of strings)
        - "priorities_next_month" (array of strings)
        - "notes_for_leadership" (string)

        1) "overall_summary":
           A coherent narrative of 3–5 paragraphs, written in prose (no bullet points).
           - Link explicitly to strategic objectives by ID and title where possible.
           - Diagnose what seems on track, developing, or lightly constrained, and why.
           - Frame progress in the context of a FIVE-YEAR strategic plan.
           - Go beyond restating answers: infer patterns, tensions, and trade-offs.
           - Where evidence is thin or missing, acknowledge it neutrally.
           - Avoid urgent or alarmist language. Prefer terms like "developing," "building momentum,"
             "early stage," or "area to watch over time," rather than "at risk" or "needs immediate attention."
           - Focus your assessment primarily on HIGH-importance items (ai_weight=3), with MEDIUM items (ai_weight=2)
             as supporting context. Include relevant LOW-importance items (ai_weight=1) when they provide
             valuable context or illustrate broader patterns, but do NOT base strong negative conclusions
             primarily on LOW-importance items, which are optional or seasonal signals meant only to add nuance.
           - Be comprehensive: incorporate key findings from all answered questions, ensuring that important
             details are not lost in summarization. Each paragraph should be substantive (5-8 sentences).

        2) "objective_summaries":
           An array of objects, each with:
             - "objective_id": the strategic objective ID (e.g., "ART1", "ART2", "SCH1")
             - "objective_title": the full strategic objective title
             - "score_hint": a string in the form "<n>/3 label", where n is 0, 1, 2, or 3.
               Examples: "3/3 Strong progress", "2/3 Steady development", "1/3 Early stage", "0/3 Inactive this period".
             - "summary": a comprehensive paragraph (5-10 sentences).
        
           For each strategic objective, explain:
             - what the answers suggest about progress over the long term toward this specific strategic goal,
             - how different productions/programmes contribute to this objective,
             - and any underlying causes or dependencies you can infer.
             - Include specific details from the scorecard answers that illustrate progress or challenges.
             - Reference concrete examples, metrics, or activities mentioned in the responses.
             - Ensure that important answered questions are reflected in your narrative, not just high-level themes.
        
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
             - NEVER base a 0/3 or a harsh negative judgement solely on LOW-importance items.

        3) "production_summaries":
           An array of objects, each with:
             - "production": the production/programme name (or "General")
             - "objectives": an array of objects with:
                 - "objective_id": the strategic objective ID (e.g., "ART1", "ART2")
                 - "objective_title": the strategic objective title
                 - "score_hint": again in the form "<n>/3 label" using the same 0–3 scale.
                 - "summary" (4–7 sentences with specific details).
           Focus on how each production/programme contributes to specific strategic objectives.
           When comparing productions or programmes, do not let a single metric completely dominate your judgment.
           Look across all available answers before calling a production clearly strong or weak for a given objective.
           
           IMPORTANT: Include specific findings from the scorecard responses for each production.
           - Reference actual metrics, activities, achievements, or challenges mentioned in the answers.
           - Don't just provide generic assessments - ground your summary in the concrete details provided.
           - Ensure that answered questions are represented in the production narrative, not lost in abstraction.

           Some questions are marked as "DEPARTMENT-WIDE (not tied to a single production)".
           These describe the company or department overall and MUST NOT be treated as
           attributes of any specific production. Use them only in "overall_summary" and
           "objective_summaries", not in "production_summaries".

        4) "risks":
           An array of concise bullet-style strings labeled as "Areas to Watch" or "Considerations."
           These should identify strategic considerations worth monitoring over time, not immediate crises.
           Use measured language: "Worth monitoring," "Consider tracking," "May need attention over time."
           Base observations primarily on HIGH-importance items, supported by MEDIUM items.
           Do NOT identify concerns based solely on LOW-importance items.

        5) "priorities_next_month":
           An array of concise, action-oriented bullet strings framed as "Next Steps in the Strategic Journey."
           Each item should represent a logical next step in advancing long-term objectives.
           Frame each priority as continuing momentum, building foundations, or advancing a strategic initiative.

        6) "notes_for_leadership":
           Write 2–3 substantive paragraphs (6–12 sentences total) in prose (no bullets),
           written as if for the CEO and Board with a long-term strategic lens. Highlight:
             - the most important strategic signals from this month in the context of multi-year progress,
             - how this month's activities fit into the broader 5-year transformation journey,
             - any trade-offs or dependencies they should understand as strategic initiatives mature,
             - where sustained attention (not immediate crisis response) may support long-term success.
             - Include specific examples or data points from the scorecard that warrant Board attention.

        Style guidelines:
        - Use clear, direct language suitable for a Board / senior leadership report.
        - Avoid generic consulting clichés.
        - Do not simply repeat question text; instead, synthesise what the answers imply for strategy.
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

    For the Artistic department, we switch to an Artistic Director voice.
    For all other departments, we keep the neutral strategy-analyst voice.
    """

    # Build a strategy-aware prompt that joins questions + answers + objectives
    prompt = _build_prompt_objective_aware(meta, questions_df, responses)

    # Choose system voice based on department
    dept_name = str(meta.get("department") or "").lower()

    if "artistic" in dept_name:
        # Artistic Director voice
        system_content = (
            "You are the Artistic Director of Alberta Ballet reporting to the Board. "
            "You are reflecting on this month's Artistic scorecard in the context of a "
            "five-year strategic plan (2025–2030). Not everything will be done right away, "
            "and there is natural seasonality to the work: creation periods, rehearsal blocks, "
            "premieres, touring, festivals, and audition cycles.\n\n"
            "Speak in a grounded Artistic Director voice:\n"
            "- Use natural 'we' / 'our' language where appropriate.\n"
            "- Focus on repertoire, dancers, rehearsal and performance quality, artistic risk-taking, "
            "collaborations, and how the season is unfolding artistically.\n"
            "- Recognise that some months will be quieter for certain objectives (e.g., no auditions "
            "outside the usual cycle, no festival appearances out of season). Treat these as normal "
            "seasonal variations, not failures.\n"
            "- Use the importance weights (ai_weight: 1=low, 2=medium, 3=high) as a guide to what "
            "matters most, but apply common sense appropriate to a ballet company—we are not "
            "in emergency medicine.\n\n"
            "You still must follow the JSON output contract exactly as described in the user prompt: "
            "return only JSON, with the required keys, and no markdown or extra commentary."
        )
    else:
        # Original strategy-analyst voice for non-Artistic departments
        system_content = (
            "You are a senior strategy analyst for Alberta Ballet. "
            "You interpret monthly scorecards in the context of the 2025–2030 strategic plan—"
            "a FIVE-YEAR journey of transformation. "
            "Each monthly scorecard represents one step in a multi-year process. "
            "Not everything needs to be accomplished immediately. "
            "Your role is to assess incremental progress toward long-term goals, "
            "recognizing that strategic initiatives unfold gradually over years. "
            "Avoid creating false urgency around issues that are simply at early stages. "
            "You produce deep, board-ready narrative summaries in JSON format."
        )

    # Make the call
    try:
        client = _get_openai_client()
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": system_content,
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

            # Look for a single JSON object
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

        # Handle both old "pillars" and new "objectives" structure
        objectives = prod.get("objectives") or prod.get("pillars") or []
        cleaned_objectives = []
        for obj in objectives:
            if not isinstance(obj, dict):
                continue
            
            # Check both old pillar name and new objective_id for recruitment filtering
            obj_name = str(obj.get("pillar", "") or obj.get("objective_title", "")).lower()

            # Strip anything clearly about recruitment / world-class company
            if "recruit" in obj_name:
                continue
            if "build a world-class ballet company" in obj_name:
                continue

            cleaned_objectives.append(obj)

        # Use new "objectives" key, but maintain old "pillars" for backward compatibility
        prod["objectives"] = cleaned_objectives
        if "pillars" in prod:
            prod["pillars"] = cleaned_objectives
        cleaned_prod_summaries.append(prod)

    data["production_summaries"] = cleaned_prod_summaries

    # Normalise the output shape so app.py rendering is resilient
    # Maintain backward compatibility by providing both objective_summaries and pillar_summaries
    result = {
        "overall_summary": data.get("overall_summary", ""),
        "objective_summaries": data.get("objective_summaries", []) or [],
        "pillar_summaries": data.get("pillar_summaries", []) or data.get("objective_summaries", []) or [],
        "production_summaries": data.get("production_summaries", []) or [],
        "risks": data.get("risks", []) or [],
        "priorities_next_month": data.get("priorities_next_month", []) or [],
        "notes_for_leadership": data.get("notes_for_leadership", "") or "",
    }
    
    return result

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
        You are a senior strategy analyst and executive advisor for Alberta Ballet, preparing a comprehensive
        Board report that synthesises performance across all departments in the context of the organisation's
        2025–2030 strategic plan—a FIVE-YEAR transformation journey.

        CRITICAL CONTEXT: FIVE-YEAR STRATEGIC PLAN (2025–2030)
        
        This is not a quarterly business review—it is one monthly snapshot in a multi-year strategic
        transformation. Your analysis must reflect the reality of long-term organisational change:
        
        - Strategic initiatives unfold gradually over multiple years, not quarters or months.
        - Different objectives will naturally progress at different paces across the organisation.
        - Some initiatives may be in planning or foundation-building stages for extended periods.
        - Others may show bursts of activity followed by integration and consolidation.
        - Many will demonstrate steady, incremental progress rather than dramatic leaps.
        - Seasonal variations are normal and expected in a performing arts organisation.
        - Not everything needs to be accomplished immediately—patience and sustained effort matter more.
        
        Assess organisational progress with a long-term strategic lens, avoiding false urgency or the
        assumption that slow-and-steady progress indicates inadequacy.

        STRICT GROUNDING & TONE RULES
        
        - Base every observation ONLY on what is explicitly stated or very clearly implied in the department
          summaries, pillar scores, and overall scores you are given.
        - Do NOT invent organisational politics, interpersonal dynamics, or speculative conflicts.
        - You MUST NOT describe “tensions”, “misalignment”, “conflict”, “friction”, “strain”, “outstripping capacity”,
          or similar language **unless** the source department summaries themselves use similar wording.
        - In particular, do NOT assert or imply a misalignment between the School and Artistic departments
          unless this is clearly and explicitly described in the input summaries.
        - If the data is thin, mixed, or ambiguous, say so neutrally (e.g., “the data is inconclusive this month”,
          “this remains an area to monitor over time”) instead of speculating.
        - You MUST NOT use the exact phrases “there are tensions emerging” or “this misalignment may” anywhere
          in your output.

        ABSENCE & SEASONALITY RULES

        - You MUST NOT treat the mere absence of an activity in this month (e.g., no provincial tour, no general
          audition, no festival appearance) as evidence of a gap, failure, or risk.
        - In a performing arts context, many activities are seasonal or cyclical. A month without certain activities
          can be entirely normal.
        - Only describe the absence of an activity as a concern if:
          • The underlying department summary itself frames that absence as a problem, challenge, or risk, OR
          • There is clear, repeated evidence over time (expressly stated in the summaries) that an activity is
            expected every month and its absence is now explicitly flagged.
        - If a department summary clearly labels an absence as seasonal or non-problematic, you MUST preserve
          that framing and MUST NOT upgrade it to a risk (e.g., do not turn “no auditions this month – out of cycle”
          into “potential gaps in recruitment that could impact future growth”).
        - You MUST NOT say that “the absence of provincial tours” or “the absence of general auditions this month”
          may limit growth, outreach, or recruitment UNLESS the department summaries explicitly state this.

        PHRASE RESTRICTIONS

        - Do NOT write that a department “acknowledges the need for growth” or “recognises a gap” on a specific
          objective unless that wording (or a very close equivalent) appears in the department-level summaries
          themselves.
        - When in doubt, use neutral language such as “this objective remains a future area of focus” or
          “this remains an area to watch over time” instead of asserting a need or deficiency.
        - You MUST NOT use phrases such as “the absence of provincial tours and general auditions this month may
          limit outreach and recruitment opportunities” unless that exact concern is already clearly articulated in the
          input summaries.

        YOUR TASK: DEEP, INTERPRETIVE BOARD-LEVEL ANALYSIS
        
        You will receive department-level scorecard summaries. Each department has already been analysed
        in detail with its own strategic objectives (from the 2025-2030 strategic plan), importance weightings, 
        and production-specific context.
        
        CRITICAL: Each department summary includes a "Strategic Objectives (2025-2030 Plan)" section that lists
        the specific strategic objectives (e.g., ART1, ART2, SCH1, COM1, CORP1) that department is working on,
        along with scores and detailed summaries for each objective. Your analysis MUST be organized around
        these strategic objectives, not generic organizational categories.
        
        Your role is to:
        
        1. SYNTHESISE CROSS-DEPARTMENTAL PATTERNS BY STRATEGIC OBJECTIVE
           - Group your analysis by strategic objectives (ART1, ART2, SCH1, etc.) as they appear in the data.
           - Identify where multiple departments contribute to the same strategic objective.
           - Look for interdependencies between departments working on related objectives,
             but only where these interdependencies are clearly indicated in the underlying summaries.
           - Spot resource constraints or capacity issues that affect multiple objectives, when supported by the data.
           - Recognise where different objectives are progressing at different rates and why that matters.

        2. ASSESS STRATEGIC COHERENCE ACROSS OBJECTIVES
           - How well are the departments working in concert toward shared strategic objectives, based on the evidence given?
           - Where is the organisation building momentum across multiple objectives?
           - Where are there gaps or sequencing issues (e.g., foundations still being laid before later-phase work)?
           - Focus on trade-offs in priorities and capacity only when they are visibly grounded in the inputs.

        3. PROVIDE BOARD-LEVEL STRATEGIC INTERPRETATION
           - Go beyond restating department summaries—interpret what the collective pattern means.
           - Diagnose systemic issues, not just departmental ones, but only when they are clearly signalled.
           - Identify what's working well organisation-wide and why.
           - Point out what needs sustained Board attention over the coming months/years.
           - Acknowledge uncertainties, contradictions, or areas where the data is ambiguous.

        4. FRAME PROGRESS IN THE MULTI-YEAR CONTEXT
           - This is one month of a 60-month strategic plan.
           - Some objectives may show little visible progress this month—that can be normal.
           - Focus on trajectory and momentum over time, not just this month's snapshot.
           - Use language like “building foundations”, “gaining momentum”, “early stages”, “maturing nicely”
             rather than “at risk” or “needs immediate attention” for issues that are simply developing.

        5. BALANCE CANDOUR WITH PERSPECTIVE
           - Be honest about challenges, constraints, and areas needing attention.
           - But contextualise them within the long-term journey.
           - Distinguish between tactical hiccups and true strategic constraints, and only describe the latter
             where the data clearly supports it.
           - Highlight achievements and progress without excessive praise.

        WRITING GUIDELINES FOR BOARD-LEVEL SOPHISTICATION:
        
        - Use clear, direct, executive-level language (not academic jargon or consultant-speak).
        - Write for a knowledgeable Board that understands Alberta Ballet deeply—no need to explain basics.
        - Synthesise, don't merely summarise—transform the departmental data into higher-order insights.
        - Point out non-obvious patterns and dependencies only when they are genuinely supported by the inputs.
        - Where you see gaps in the data or ambiguity, say so directly.
        - Avoid generic phrases like “strong performance” or “areas for improvement”—be specific and grounded.
        - Balance the competing demands of artistic excellence, financial sustainability, community impact,
          and organisational capacity in your interpretation.

        ────────────────────────────────────────────────────────
        OUTPUT FORMAT (STRICT CONTRACT):

        Respond with JSON only, no prose before or after, and no markdown or backticks.

        Return a single JSON object with exactly these top-level keys:

        {
          "overall_summary": string,
          "pillar_summaries": [
            {
              "strategic_pillar": string,    // Must be in format "OBJECTIVE_ID: Objective Title" (e.g., "ART1: Elevate the Art of Dance")
              "score_hint": string,           // Must be in format "n/3 label" (e.g., "2/3 Steady development")
              "summary": string
            },
            ...
          ],
          "risks": [
            string,
            ...
          ],
          "priorities_next_month": [
            string,
            ...
          ],
          "notes_for_leadership": string
        }

        DETAILED SPECIFICATIONS FOR EACH SECTION:

        1) "overall_summary" (string):
           Write 4–6 rich, substantive paragraphs (minimum 500 words) that provide a Board-level
           interpretation of organisational performance this month.
           
           Structure:
           - Paragraph 1: Executive summary of overall organisational health and trajectory in the context
             of the 5-year plan. What's the big picture this month?
           - Paragraph 2-3: Cross-departmental themes, patterns, and interdependencies that are clearly
             supported by the department summaries (avoid speculation). Include specific examples and
             data points from the department reports.
           - Paragraph 4: Notable achievements, momentum, or areas of strength worth celebrating or building on.
             Reference concrete activities, metrics, or milestones from the department summaries.
           - Paragraph 5: Constructive challenges, capacity constraints, or areas requiring sustained Board
             attention, framed in terms of the long-term strategic journey.
           - Paragraph 6 (optional): Additional insights or observations that emerge from the comprehensive
             review of all departments.

           Quality standards:
           - Go beyond restating department summaries—provide genuine synthesis and interpretation.
           - Reference specific departments and their interactions by name only where those links are evident.
           - Identify patterns and strategic implications that are clearly grounded in the input data.
           - Frame everything in the context of multi-year strategic transformation.
           - Acknowledge complexity, trade-offs, and uncertainty where present, without dramatising.
           - Be comprehensive: ensure that important information from department summaries is not lost in
             the synthesis. Include specific details that warrant Board attention.

        2) "pillar_summaries" (array):
           Analyze by STRATEGIC OBJECTIVES from the 2025-2030 strategic plan (e.g., ART1, ART2, SCH1, COM1, CORP1, etc.).
           DO NOT use generic organizational categories like "Artistic Excellence" or "Community Engagement".
           
           For EACH strategic objective that appears in the department data, create one object:
           
           {
             "strategic_pillar": "<objective_id: objective_title>",
             "score_hint": "<n>/3 label (e.g., '2.5/3 Strong progress', '2/3 Steady development', '1/3 Early stage')",
             "summary": "<substantial paragraph, 8-12 sentences with specific details>"
           }
           
           IMPORTANT: The department summaries include "Strategic Objectives (2025-2030 Plan)" sections that 
           list the actual strategic objectives with their IDs (e.g., ART1, SCH1, COM1) and scores.
           You MUST use these objective IDs as the basis for your pillar_summaries, not invented categories.
           
           For each strategic objective:
           - Use the exact objective_id and objective_title from the department data (e.g., "ART1: Elevate the Art of Dance").
           - Synthesise performance across ALL departments working on this objective.
           - Identify how different departments contribute to or shape this objective, but only as far as
             the summaries clearly show.
           - Assess trajectory and momentum in the context of the 5-year plan.
           - Point out dependencies or resource trade-offs that are visibly supported by the inputs.
           - Be specific about what's working and what needs sustained attention.
           - Include concrete examples, metrics, or activities from the department summaries that
             illustrate this objective's performance.
           - Ensure comprehensive coverage: don't lose important departmental information in the synthesis.
           
           Use the 0–3 scoring scale with an organisation-wide perspective:
           - 3/3: Strong progress across multiple departments toward this strategic objective
           - 2/3: Steady development with good momentum (this is positive for a 5-year plan)
           - 1/3: Early stages or foundation-building across the organisation
           - 0/3: Little to no activity (rare; only if departments clearly show inactivity)

        3) "risks" (array of strings):
           Identify 5–10 strategic considerations, constraints, or areas to monitor over time.

           These should be:
           - Cross-departmental or systemic issues (not just single-department problems).
           - Clearly and explicitly grounded in the department summaries and/or scores.
           - Framed as “Areas for Board Attention” or “Strategic Considerations” rather than crises.
           - Expressed in measured, governance-appropriate language.
           - Specific enough to be meaningful, but never speculative about tensions or misalignment.

           Grounding rule:
           - For each risk, you should be able to point to one or more concrete statements in the department
             summaries that support it. If you cannot, do NOT include that risk.

        4) "priorities_next_month" (array of strings):
           Recommend 4–8 clear, action-oriented priorities for the organisation as a whole.
           
           These should be:
           - Organisation-wide (not department-specific unless they have broad strategic implications).
           - Framed as next steps in the multi-year journey, not urgent fixes.
           - Specific enough that leadership can act on them.
           - Connected to the patterns and themes identified in your analysis.

        5) "notes_for_leadership" (string):
           Write 3–5 substantive paragraphs (minimum 400 words) directly addressing the CEO and Board.

           Focus on:
           - The most important strategic signals from this month.
           - What the Board and CEO should keep in mind long-term.
           - Any emerging patterns or early indicators to monitor.
           - What is going well that deserves continued support.
           - Where strategic choices or trade-offs may be approaching, based on the evidence provided.
           - Include specific examples or data points from department reports that warrant leadership attention.
           - Ensure that key insights from the department summaries are surfaced, not lost in abstraction.

        ────────────────────────────────────────────────────────
        DEPARTMENT SUMMARIES FOLLOW BELOW

        Treat these as the complete set of departments reporting this period. Do not invent additional
        departments or assume you're seeing only a partial picture. Each department summary contains
        its own detailed analysis, scores, and narratives.
        
        Your job is to synthesise these into a coherent, Board-level perspective that
        provides genuine strategic insight beyond what any single department report offers, while staying
        firmly grounded in the information provided.
        ────────────────────────────────────────────────────────
        """
    ).strip()

    blocks: List[str] = []

    for ds in dept_summaries:
        dept = ds.get("department") or "Unknown department"
        month_label = ds.get("month_label") or ds.get("month") or "Reporting period not specified"
        overall_score = ds.get("overall_score")
        pillar_scores = ds.get("pillar_scores") or {}
        objective_summaries = ds.get("objective_summaries") or []
        summary_text = (ds.get("summary_text") or "").strip()

        # Build strategic objectives block (preferred)
        if objective_summaries:
            obj_lines = []
            for obj_sum in objective_summaries:
                obj_id = obj_sum.get("objective_id", "") or ""
                obj_title = obj_sum.get("objective_title", "") or ""
                score_hint = obj_sum.get("score_hint", "") or ""
                summary = obj_sum.get("summary", "") or ""
                
                if obj_id and obj_title:
                    obj_lines.append(f"- {obj_id} ({obj_title}): {score_hint}")
                    if summary:
                        obj_lines.append(f"  Summary: {summary}")
            
            objectives_block = "\n".join(obj_lines) if obj_lines else "(No objective summaries provided.)"
        else:
            objectives_block = "(No objective summaries provided.)"

        # Keep pillar scores for backward compatibility
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
            
            Strategic Objectives (2025-2030 Plan):
            {objectives_block}
            
            Legacy Pillar scores (for reference):
            {pillar_block}

            Department summary:
            {summary_text or '[No summary text provided]'}
            ────────────────────────────────────────────────────────
            """
        ).strip()

        blocks.append(block)

    return header + "\n\nDEPARTMENT_SUMMARIES:\n\n" + "\n\n".join(blocks)

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
                        "You are a senior strategy analyst and executive advisor to the Board of Alberta Ballet. "
                        "You specialise in synthesising complex organisational data into sophisticated, actionable "
                        "Board-level strategic analysis.\n\n"
                        "Your expertise includes:\n"
                        "- Interpreting cross-departmental patterns and systemic organisational dynamics\n"
                        "- Assessing long-term strategic coherence and progress in multi-year transformation initiatives\n"
                        "- Identifying non-obvious interdependencies, tensions, and trade-offs across functions\n"
                        "- Framing tactical issues within broader strategic context\n"
                        "- Providing candid, balanced counsel appropriate for Board governance\n\n"
                        "You understand that Alberta Ballet's 2025–2030 strategic plan is a FIVE-YEAR journey. "
                        "Each monthly scorecard is one step in a 60-month transformation process. Strategic initiatives "
                        "unfold gradually, and different objectives naturally progress at different paces. Your analyses "
                        "reflect this long-term perspective, avoiding false urgency while maintaining appropriate candor "
                        "about genuine strategic challenges.\n\n"
                        "You write in clear, direct executive language—sophisticated but never academic or jargon-heavy. "
                        "You synthesise rather than summarise, transforming departmental data into higher-order strategic "
                        "insights that help the Board govern effectively.\n\n"
                        "You produce deep, comprehensive Board-ready narratives in strict JSON format as specified in "
                        "the user prompt."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.15,  # was 0.3 – lower to reduce speculative leaps
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

