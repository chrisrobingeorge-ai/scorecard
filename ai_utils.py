# ai_utils.py

import json
import os
from datetime import datetime
from typing import Dict, Any

import pandas as pd
from openai import OpenAI

from config import MODEL_NAME

api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError(
        "OPENAI_API_KEY is not set. Please set it as an environment variable or Streamlit secret."
    )

client = OpenAI(api_key=api_key)

def build_ai_payload(
    meta: Dict[str, Any],
    questions: pd.DataFrame,
    responses: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Turn raw responses + metadata into a clean JSON payload for the model.
    """
    items = []
    for _, row in questions.iterrows():
        qid = row["question_id"]
        items.append(
            {
                "question_id": qid,
                "strategic_pillar": row.get("strategic_pillar", ""),
                "production": row.get("production", ""),
                "metric": row.get("metric", ""),
                "kpi_type": row.get("kpi_type", ""),
                "ai_weight": float(row.get("ai_weight", 1.0) or 1.0),
                "response_type": row.get("response_type", ""),
                "response": responses.get(qid, None),
            }
        )

    payload = {
        "meta": {
            "staff_name": meta.get("staff_name"),
            "role": meta.get("role"),
            "department": meta.get("department"),
            "month": meta.get("month"),
            "submitted_at_utc": datetime.utcnow().isoformat(timespec="seconds"),
        },
        "items": items,
    }
    return payload


def interpret_scorecard(
    meta: Dict[str, Any],
    questions: pd.DataFrame,
    responses: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Call OpenAI to interpret the scorecard and return a structured result.
    """
    payload = build_ai_payload(meta, questions, responses)

    system_msg = (
        "You are an expert arts-management coach writing monthly performance reflections "
        "for a ballet organisation. Be concise, concrete, and constructive."
    )

    user_instruction = """
You will receive a JSON payload with metadata and a list of answered scorecard questions.

Return a single JSON object with the following shape:

{
  "overall_summary": "2–3 paragraphs summarising this person's month in a supportive, honest tone.",
  "pillar_summaries": [
    {
      "strategic_pillar": "...",
      "summary": "Short paragraph about this pillar.",
      "score_hint": "High / Mixed / Low"
    }
  ],
  "risks": [
    "Short bullet-style sentence describing a risk or concern.",
    "... (2–5 items total)"
  ],
  "priorities_next_month": [
    "Concrete priority expressed as an action.",
    "... (3–6 items total)"
  ],
  "notes_for_leadership": "Optional short paragraph with anything leaders should be aware of (can be empty)."
}

Guidelines:
- Pay attention to kpi_type and ai_weight when deciding what to emphasise.
- Consider patterns across answers, not just individual scores.
- Use plain language that a busy executive can skim.
- Do not invent numbers that are not in the payload.
"""

    messages = [
        {"role": "system", "content": system_msg},
        {
            "role": "user",
            "content": user_instruction
            + "\n\nHere is the scorecard data as JSON:\n"
            + json.dumps(payload, indent=2),
        },
    ]

    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=0.3,
    )

    content = resp.choices[0].message.content or ""

    # Try to parse as JSON
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # Fallback if the model returns plain text
        parsed = {
            "overall_summary": content.strip(),
            "pillar_summaries": [],
            "risks": [],
            "priorities_next_month": [],
            "notes_for_leadership": "",
        }

    return parsed
