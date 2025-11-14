# ai_utils.py
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import pandas as pd


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


def interpret_scorecard(
    meta: Dict[str, Any],
    questions_df: pd.DataFrame,
    responses: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Call OpenAI to produce a structured interpretation of the scorecard.
    Returns a dict with keys that app.py expects.
    """
    prompt = _build_prompt(meta, questions_df, responses)

    # Make the call
    try:
        client = _get_openai_client()
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You analyse monthly scorecards for a single department and produce structured summaries.",
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

            m = re.search(r"\{.*\}", text, re.S)
            data = json.loads(m.group(0)) if m else {}
    except Exception as e:
        # Propagate as RuntimeError so app.py can show a friendly message
        raise RuntimeError(str(e))

    # Normalize the output shape so app.py rendering is resilient
    return {
        "overall_summary": data.get("overall_summary", ""),
        "pillar_summaries": data.get("pillar_summaries", []) or [],
        "production_summaries": data.get("production_summaries", []) or [],
        "risks": data.get("risks", []) or [],
        "priorities_next_month": data.get("priorities_next_month", []) or [],
        "notes_for_leadership": data.get("notes_for_leadership", "") or "",
    }
