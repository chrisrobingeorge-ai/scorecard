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


def _build_prompt(meta: Dict[str, Any], questions_df: pd.DataFrame, responses: Dict[str, Dict[str, Any]]) -> str:
    """
    Build a minimal, structured input for the model.
    """
    items: List[Dict[str, Any]] = []
    for _, row in questions_df.iterrows():
        qid = str(row.get("question_id"))
        # Use question_text, else metric, else qid
        qtext = (row.get("question_text") or row.get("metric") or qid) or qid
        r = responses.get(qid) or {}
        items.append(
            {
                "question_id": qid,
                "question": str(qtext),
                "response": r.get("primary"),
                "notes": r.get("description"),
                "pillar": str(row.get("strategic_pillar") or ""),
                "production": str(row.get("production") or ""),
                "metric": str(row.get("metric") or ""),
                "type": str(row.get("response_type") or ""),
            }
        )

    payload = {"meta": meta, "items": items}

    dept_name = str(meta.get("department") or "this department")
    scope = str(meta.get("scope") or "").strip()
    if scope == "department_all_productions":
        scope_desc = f"for the entire {dept_name} department across all productions in the reporting period"
    else:
        scope_desc = f"for the {dept_name} department based only on the items provided"

    instruction = f"""
    You are an expert analyst preparing an executive summary of Alberta Ballet’s scorecard results {scope_desc}.

    CRITICAL SCOPE RULES:
    - You are analysing ONE department only: {dept_name}.
    - Do NOT assume you can see the whole organisation or other departments.
    - Do NOT invent additional departments or pillars that do not appear in the data.
    - Base everything strictly on the INPUT_JSON.

    Pillars:
    - Each item includes a "pillar" field.
    - For pillar_summaries, infer the set of pillars from the DISTINCT values of that "pillar" field.
    - Produce ONE pillar_summaries entry per pillar value you actually see.
    - If a pillar is not present in the data, do NOT mention it at all.

    Task:
    Analyse the provided scorecard data and produce a narrative summary for this department that includes:
    1) overall_summary:
       - High-level performance this period.
       - Major achievements and constructive challenges.
    2) pillar_summaries:
       - For EACH pillar actually present in the data (from the "pillar" field), provide:
         • strategic_pillar: the pillar name as it appears in the data.
         • score_hint: a short hint such as "2/3 – steady progress", "1/3 – needs improvement", or "N/A – limited data", inferred from responses.
         • summary: 2–4 sentences about achievements, issues, and next steps for that pillar.
    3) risks:
       - Cross-cutting risks or concerns that affect THIS department.
       - Each entry is a short, clear sentence.
    4) priorities_next_month:
       - 3–6 concrete priorities for THIS department for the coming month.
       - Each entry is a short, action-oriented sentence.
    5) notes_for_leadership:
       - A short paragraph with advice for the executive team focused on THIS department only.

    Output Contract (strict):
    - Respond with JSON only, no prose before or after.
    - Use exactly these keys at the top level:
      - overall_summary (string)
      - pillar_summaries (array of objects with keys: strategic_pillar (string), score_hint (string), summary (string))
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
                {"role": "system", "content": "You analyze monthly scorecards and produce structured summaries."},
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
        "pillar_summaries": data.get("pillar_summaries", []),
        "risks": data.get("risks", []),
        "priorities_next_month": data.get("priorities_next_month", []),
        "notes_for_leadership": data.get("notes_for_leadership", ""),
    }
