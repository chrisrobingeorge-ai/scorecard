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

    instruction = (
        "You are an expert analyst preparing an executive summary of Alberta Ballet’s departmental scorecard results for board review. "
        "The scorecard uses a 3-point ranking system to evaluate progress across five main categories: Company, School, Community, Corporate, and HR & Governance. "
        "Each ranking is determined by measurable outputs, reflecting the effectiveness of initiatives in artistic excellence, student development, audience engagement, financial sustainability, and governance.\n\n"
        "Please analyse the provided scorecard data and produce a comprehensive, narrative-driven summary that includes:\n"
        "1. Overall Organisational Summary: A high-level overview of Alberta Ballet’s current performance, major achievements, and strategic direction.\n"
        "2. Departmental Summaries: For each pillar (Company, School, Community, Corporate, HR & Governance), provide:\n"
        "   - The total score and what it indicates about progress.\n"
        "   - Key achievements and standout successes.\n"
        "   - Areas needing improvement or facing challenges.\n"
        "   - Notable risks or barriers to future progress.\n"
        "   - Strategic priorities for the next month/quarter.\n"
        "3. Cross-cutting Risks and Opportunities: Identify any themes or issues that affect multiple departments.\n"
        "4. Actionable Recommendations for Leadership: What should the executive team focus on to accelerate progress and address gaps?\n\n"
        "Use clear, concise language suitable for board/executive consumption. Blend quantitative results with qualitative insights, and ensure the summary is both informative and inspiring.\n\n"
        "Return your answer as a concise JSON with keys: overall_summary (string), pillar_summaries (list of {strategic_pillar, score_hint, summary}), risks (list of strings), priorities_next_month (list of strings), notes_for_leadership (string). Base your output only on the input."
    )

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
