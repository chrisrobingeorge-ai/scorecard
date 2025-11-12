# app.py
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Dict, Tuple

import pandas as pd
import streamlit as st

from config import DEPARTMENT_CONFIGS, YES_NO_OPTIONS, GENERAL_PROD_LABEL
from ai_utils import interpret_scorecard
from pdf_utils import build_scorecard_pdf


# ─────────────────────────────────────────────────────────────────────────────
# MUST be the first Streamlit call
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Monthly Scorecard", layout="wide")


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────
def safe_rerun():
    """Call st.rerun() if available, else fall back to st.experimental_rerun()."""
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


def _hash_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _ensure_col(df: pd.DataFrame, col: str, default=""):
    """Ensure a column exists and fill NA."""
    if col not in df.columns:
        df[col] = default
    df[col] = df[col].fillna(default)


def get_answers_df() -> pd.DataFrame:
    """
    Single source of truth for all answers.
    One row = one answer to one question for one production in one department.
    """
    if "answers_df" not in st.session_state:
        st.session_state["answers_df"] = pd.DataFrame(
            columns=["department", "production", "question_id", "primary", "description"]
        )
    return st.session_state["answers_df"]


def get_answer_value(dept: str, production: str, qid: str) -> Tuple[object | None, str | None]:
    df = get_answers_df()
    mask = (
        (df["department"] == dept) &
        (df["production"] == production) &
        (df["question_id"] == qid)
    )
    if not mask.any():
        return None, None
    row = df[mask].iloc[0]
    return row.get("primary", None), row.get("description", None)


def upsert_answer(dept: str, production: str, qid: str, primary, description=None):
    df = get_answers_df()
    mask = (
        (df["department"] == dept) &
        (df["production"] == production) &
        (df["question_id"] == qid)
    )

    new_row = {
        "department": dept,
        "production": production,
        "question_id": qid,
        "primary": primary,
        "description": description or "",
    }

    if mask.any():
        st.session_state["answers_df"].loc[mask, ["primary", "description"]] = [
            (primary, description or "")
        ]
    else:
        st.session_state["answers_df"] = pd.concat(
            [df, pd.DataFrame([new_row])],
            ignore_index=True,
        )


def _normalise_show_entry(entry):
    """Convert stored show answers into the dict format used across the app."""
    if isinstance(entry, dict):
        cleaned = {}
        if "primary" in entry:
            cleaned["primary"] = entry.get("primary")
        if "description" in entry:
            cleaned["description"] = entry.get("description")
        return cleaned if cleaned else None
    if entry is None:
        return None
    return {"primary": entry}


# ─────────────────────────────────────────────────────────────────────────────
# Data loading (cached)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data
def load_questions(file_path: str) -> pd.DataFrame:
    df = pd.read_csv(file_path)

    # Normalize ID
    if "question_id" in df.columns:
        df["question_id"] = df["question_id"].astype(str).str.strip()
    else:
        raise ValueError("questions CSV must contain a 'question_id' column")

    # Normalize common columns
    if "required" in df.columns:
        df["required"] = df["required"].astype(str).str.upper().eq("TRUE")
    if "display_order" in df.columns:
        df["display_order"] = pd.to_numeric(df["display_order"], errors="coerce").fillna(0)

    if "section" not in df.columns:
        df["section"] = df.get("strategic_pillar", "General")

    for c in ("section", "strategic_pillar", "production", "metric",
              "question_text", "response_type", "options", "depends_on"):
        _ensure_col(df, c, "")

    # Defaults for grouping/rendering
    df["section"] = df["section"].replace("", "General")
    df["response_type"] = df["response_type"].replace("", "text")

    return df


# ─────────────────────────────────────────────────────────────────────────────
# Conditional visibility rules
# ─────────────────────────────────────────────────────────────────────────────
def question_is_visible(row: pd.Series, dept_label: str, production: str) -> bool:
    """
    Returns True if the question should be shown, based on an optional 'depends_on'
    parent question. Currently: show only if parent == 'Yes' for yes/no parents.
    """
    depends_on = str(row.get("depends_on", "") or "").strip()
    if not depends_on:
        return True  # no dependency

    parent_key = f"{dept_label}::{production}::{depends_on}"
    parent_val = st.session_state.get(parent_key)
    return parent_val == "Yes"


# ─────────────────────────────────────────────────────────────────────────────
# Form rendering
# ─────────────────────────────────────────────────────────────────────────────
def build_form_for_questions(
    df: pd.DataFrame,
    dept_label: str,
    production: str,
) -> Dict[str, dict]:
    """
    Render widgets for each question in the provided DataFrame.
    Reads/writes values via answers_df. Returns {qid: {primary, description}}.
    """
    responses: Dict[str, dict] = {}

    df = df.copy()
    df["strategic_pillar"] = df["strategic_pillar"].replace("", "General")
    df["metric"] = df["metric"].fillna("")
    df["display_order"] = pd.to_numeric(df.get("display_order", 0), errors="coerce").fillna(0)
    df = df.sort_values("display_order")

    for _, row in df.iterrows():
        # Skip if dependency not satisfied
        if not question_is_visible(row, dept_label, production):
            continue

        qid = str(row["question_id"])  # ALWAYS STRING

        # Label resolution
        raw_label = str(row.get("question_text", "") or "").strip()
        if not raw_label:
            metric = str(row.get("metric", "") or "").strip()
            label = metric or qid
        else:
            label = raw_label

        required = bool(row.get("required", False))
        label_display = f"{label} *" if required else label

        rtype = str(row.get("response_type", "")).strip().lower()
        opts_raw = row.get("options", "")
        options = []
        if isinstance(opts_raw, str) and opts_raw.strip():
            options = [o.strip() for o in opts_raw.split(",") if o.strip()]

        # Get previous value for this (dept, production, qid)
        prev_primary, prev_desc = get_answer_value(dept_label, production, qid)

        # Make widget key unique per production
        widget_key = f"{dept_label}::{production}::{qid}"

        entry = {"primary": None, "description": prev_desc}

        if rtype == "yes_no":
            if prev_primary in YES_NO_OPTIONS:
                idx = YES_NO_OPTIONS.index(prev_primary)
            else:
                idx = 0
            entry["primary"] = st.radio(
                label_display,
                YES_NO_OPTIONS,
                horizontal=True,
                key=widget_key,
                index=idx,
            )

        elif rtype == "scale_1_5":
            default_val = 3
            if isinstance(prev_primary, (int, float)) and 1 <= int(prev_primary) <= 5:
                default_val = int(prev_primary)
            entry["primary"] = int(
                st.slider(label_display, min_value=1, max_value=5, key=widget_key, value=default_val)
            )

        elif rtype == "number":
            default_val = float(prev_primary) if isinstance(prev_primary, (int, float)) else 0.0
            entry["primary"] = st.number_input(label_
