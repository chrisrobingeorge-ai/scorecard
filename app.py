# app.py
from __future__ import annotations

import os
from pathlib import Path
import json
from dataclasses import dataclass
from datetime import date
from typing import Dict, Tuple, List, Any, Optional

import pandas as pd
import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# Config imports + safe fallbacks
# ─────────────────────────────────────────────────────────────────────────────
try:
    from app_config import DEPARTMENT_CONFIGS as _DEPT_CFGS
except Exception:
    _DEPT_CFGS = None

try:
    from app_config import YES_NO_OPTIONS as _YNO
    YES_NO_OPTIONS = list(_YNO)
except Exception:
    YES_NO_OPTIONS = ["Yes", "No"]

try:
    from app_config import GENERAL_PROD_LABEL as _GPL
    GENERAL_PROD_LABEL = _GPL
except Exception:
    GENERAL_PROD_LABEL = "General"

try:
    from ai_utils import interpret_scorecard
except Exception:
    def interpret_scorecard(meta, filtered_df, responses):
        # Safe stub if ai_utils not available
        return {
            "overall_summary": "AI module not configured.",
            "pillar_summaries": [],
            "risks": [],
            "priorities_next_month": [],
            "notes_for_leadership": "",
        }

try:
    from pdf_utils import build_scorecard_pdf
except Exception:
    def build_scorecard_pdf(*args, **kwargs):
        # ASCII-only stub to avoid SyntaxError on some hosts
        return b"%PDF-1.4\n% Stub PDF - pdf_utils not configured.\n"

# ─────────────────────────────────────────────────────────────────────────────
# Streamlit cache guard (supports older Streamlit)
# ─────────────────────────────────────────────────────────────────────────────
try:
    cache_data = st.cache_data
except AttributeError:  # Streamlit < 1.18
    cache_data = st.cache

# ─────────────────────────────────────────────────────────────────────────────
# Config normalization (robust to dicts, SimpleNamespace, or custom objects)
# ─────────────────────────────────────────────────────────────────────────────
from collections.abc import Mapping

@dataclass
class DepartmentConfig:
    questions_csv: str
    has_productions: bool = True
    productions_csv: Optional[str] = None
    scope_label: str = "Production / area"
    allow_general_option: bool = True  # 👈 Add this

def _normalize_dept_cfgs(raw: Any) -> Dict[str, DepartmentConfig]:
    def _defaults() -> Dict[str, DepartmentConfig]:
        return {
            "Artistic": DepartmentConfig(
                questions_csv="data/artistic_scorecard_questions.csv",
                has_productions=True,
                productions_csv="data/productions.csv",
                scope_label="Production",
                allow_general_option=True,
            ),
            "School": DepartmentConfig(
                questions_csv="data/school_scorecard_questions.csv",
                has_productions=False,
                productions_csv=None,
                scope_label="Programme",
                allow_general_option=True,
            ),
            "Community": DepartmentConfig(
                questions_csv="data/community_scorecard_questions.csv",
                has_productions=True,
                productions_csv="data/productions.csv",
                scope_label="Programme",
                allow_general_option=False,  
            ),
            "Corporate": DepartmentConfig(
                questions_csv="data/corporate_scorecard_questions.csv",
                has_productions=False,
                productions_csv=None,
                scope_label="Area",
                allow_general_option=True,
            ),
        }

    if not raw:
        return _defaults()

    if not isinstance(raw, Mapping):
        return _defaults()

    out: Dict[str, DepartmentConfig] = {}
    for k, v in raw.items():
        if isinstance(v, DepartmentConfig):
            out[k] = v
            continue

        # Extract fields from dict or object
        questions_csv        = v.get("questions_csv") if isinstance(v, Mapping) else getattr(v, "questions_csv", None)
        has_productions      = v.get("has_productions", True) if isinstance(v, Mapping) else getattr(v, "has_productions", True)
        productions_csv      = v.get("productions_csv") if isinstance(v, Mapping) else getattr(v, "productions_csv", None)
        scope_label          = v.get("scope_label", "Production / area") if isinstance(v, Mapping) else getattr(v, "scope_label", "Production / area")
        allow_general_option = v.get("allow_general_option", True) if isinstance(v, Mapping) else getattr(v, "allow_general_option", True)

        out[k] = DepartmentConfig(
            questions_csv=questions_csv,
            has_productions=bool(has_productions),
            productions_csv=productions_csv,
            scope_label=scope_label or "Production / area",
            allow_general_option=bool(allow_general_option),
        )

    return out

DEPARTMENT_CONFIGS: Dict[str, DepartmentConfig] = _normalize_dept_cfgs(_DEPT_CFGS)

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
    import hashlib as _hl
    return _hl.sha256(b).hexdigest()

def _ensure_col(df: pd.DataFrame, col: str, default: Any = ""):
    """Ensure a column exists and fill NA."""
    if col not in df.columns:
        df[col] = default
    df[col] = df[col].fillna(default)

def _resolve_path(p: str) -> Optional[str]:
    """Try several locations for a relative CSV path; return the first that exists."""
    if not p:
        return None
    if os.path.isabs(p) and os.path.exists(p):
        return p
    candidates = [
        p,
        str(Path(p)),
        str(Path.cwd() / p),
        str(Path.cwd() / "data" / Path(p).name),
        "/mount/src/scorecard/" + p,
        "/mount/src/scorecard/data/" + Path(p).name,
    ]
    for c in candidates:
        try:
            if os.path.exists(c):
                return c
        except Exception:
            pass
    return None

# ─────────────────────────────────────────────────────────────────────────────
# Answers storage
# ─────────────────────────────────────────────────────────────────────────────
def get_answers_df() -> pd.DataFrame:
    """Single source of truth for all answers."""
    if "answers_df" not in st.session_state:
        st.session_state["answers_df"] = pd.DataFrame(
            columns=["department", "production", "question_id", "primary", "description"]
        )
    return st.session_state["answers_df"]

def get_answer_value(dept: str, production: str, qid: str) -> Tuple[Optional[object], Optional[str]]:
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

def upsert_answer(dept: str, production: str, qid: str, primary, description: Optional[str] = None):
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
        # Separate column assignments to avoid shape errors
        st.session_state["answers_df"].loc[mask, "primary"] = primary
        st.session_state["answers_df"].loc[mask, "description"] = (description or "")
    else:
        st.session_state["answers_df"] = pd.concat(
            [df, pd.DataFrame([new_row])],
            ignore_index=True,
        )

def _normalise_show_entry(entry: Any) -> Optional[dict]:
    """Convert stored show answers into the dict format used across the app."""
    if isinstance(entry, dict):
        cleaned: Dict[str, Any] = {}
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
@cache_data
def load_questions_from_bytes(csv_bytes: bytes) -> pd.DataFrame:
    from io import BytesIO
    df = pd.read_csv(BytesIO(csv_bytes))

    # Normalize ID
    if "question_id" in df.columns:
        df["question_id"] = df["question_id"].astype(str).str.strip()
    else:
        raise ValueError("questions CSV must contain a 'question_id' column")

    # Normalize common columns
    if "required" in df.columns:
        df["required"] = df["required"].astype(str).str.upper().eq("TRUE")
    else:
        df["required"] = False

    if "display_order" in df.columns:
        df["display_order"] = pd.to_numeric(df["display_order"], errors="coerce").fillna(0)
    else:
        df["display_order"] = 0

    if "section" not in df.columns:
        df["section"] = df.get("strategic_pillar", "General")

    for c in ("section", "strategic_pillar", "production", "metric",
              "question_text", "response_type", "options", "depends_on"):
        if c not in df.columns:
            df[c] = ""
        df[c] = df[c].fillna("")

    # Defaults for grouping/rendering
    df["section"] = df["section"].replace("", "General")
    df["response_type"] = df["response_type"].replace("", "text")

    return df

@cache_data
def load_questions(file_path: str) -> pd.DataFrame:
    resolved = _resolve_path(file_path)
    if not resolved:
        raise FileNotFoundError(f"Could not find CSV: {file_path}")
    with open(resolved, "rb") as f:
        return load_questions_from_bytes(f.read())

# ─────────────────────────────────────────────────────────────────────────────
# Visibility rules (CSV-driven)
# ─────────────────────────────────────────────────────────────────────────────
def question_is_visible(row: pd.Series, dept_label: str, production: str) -> bool:
    """
    Visibility logic controlled by CSV 'depends_on'.

    Supported forms (case-insensitive for values):
      - "QID"                      → show if parent == "Yes"
      - "QID=Value"               → show if parent equals Value
      - "QID!=Value"              → show if parent not equals Value
      - "QID in [A,B,C]"          → show if parent is any of A,B,C
      - "QID not in [A,B]"        → show if parent not in A,B
      - Combine with ';' or '&&' for AND: "Q1=Yes; Q2 in [A,B]"

    Parent lookup key is f"{dept_label}::{production}::{QID}" (same scope).
    """
    rule = str(row.get("depends_on", "") or "").strip()
    if not rule:
        return True  # no dependency

    import re
    parts = [p.strip() for p in re.split(r';|&&', rule) if p.strip()]
    if not parts:
        return True

    def _parse_list(s: str) -> List[str]:
        s = s.strip()
        if s.startswith('[') and s.endswith(']'):
            s = s[1:-1]
        return [x.strip() for x in s.split(',') if x.strip()]

    def _get(parent_qid: str):
        key = f"{dept_label}::{production}::{parent_qid}"
        return st.session_state.get(key)

    def _cmp(lhs, rhs) -> bool:
        if lhs is None or rhs is None:
            return False
        return str(lhs).strip().casefold() == str(rhs).strip().casefold()

    def _in(lhs, options: List[str]) -> bool:
        if lhs is None:
            return False
        l = str(lhs).strip().casefold()
        return any(l == str(o).strip().casefold() for o in options)

    for cond in parts:
        m_in = re.match(r'^(\w+)\s+in\s+\[(.*?)\]$', cond, flags=re.I)
        m_not_in = re.match(r'^(\w+)\s+not\s+in\s+\[(.*?)\]$', cond, flags=re.I)
        m_ne = re.match(r'^(\w+)\s*!=\s*(.+)$', cond)
        m_eq = re.match(r'^(\w+)\s*=\s*(.+)$', cond)
        m_simple = re.match(r'^(\w+)$', cond)

        ok = True
        if m_in:
            qid, list_str = m_in.groups()
            want = _parse_list(list_str)
            ok = _in(_get(qid), want)
        elif m_not_in:
            qid, list_str = m_not_in.groups()
            want = _parse_list(list_str)
            ok = not _in(_get(qid), want)
        elif m_ne:
            qid, val = m_ne.groups()
            ok = not _cmp(_get(qid), val)
        elif m_eq:
            qid, val = m_eq.groups()
            ok = _cmp(_get(qid), val)
        elif m_simple:
            qid = m_simple.group(1)
            ok = _cmp(_get(qid), "Yes")
        else:
            ok = True

        if not ok:
            return False

    return True

# ─────────────────────────────────────────────────────────────────────────────
# Form rendering (parent → immediate children)
# ─────────────────────────────────────────────────────────────────────────────
def build_form_for_questions(
    df: pd.DataFrame,
    dept_label: str,
    production: str,
) -> Dict[str, dict]:
    """
    Render widgets for each question in the provided DataFrame.
    Returns {qid: {primary, description}}.
    Parents render first; each parent's visible children render immediately after.
    """
    responses: Dict[str, dict] = {}
    yes_no_opts = YES_NO_OPTIONS if isinstance(YES_NO_OPTIONS, (list, tuple)) and len(YES_NO_OPTIONS) >= 2 else ["Yes", "No"]

    # Normalize & base sort
    df = df.copy()
    # Guard against .get returning a scalar default
    if "strategic_pillar" in df.columns:
        df["strategic_pillar"] = df["strategic_pillar"].fillna("").replace("", "General")
    else:
        df["strategic_pillar"] = "General"

    if "metric" not in df.columns:
        df["metric"] = ""
    df["metric"] = df["metric"].fillna("")

    if "display_order" in df.columns:
        df["display_order"] = pd.to_numeric(df["display_order"], errors="coerce").fillna(0)
    else:
        df["display_order"] = 0

    # Split parents/children by depends_on presence
    dep_series = df["depends_on"] if "depends_on" in df.columns else pd.Series([""] * len(df))
    dep_series = dep_series.fillna("").astype(str).str.strip()
    is_child = dep_series.ne("")

    parents_df = df[~is_child].sort_values("display_order").reset_index(drop=True)
    children_df = df[is_child].copy()
    # Parent id is the token before any operator (e.g., QID in [..], QID=..., QID!=...)
    children_df["__parent_qid__"] = children_df["depends_on"].astype(str).str.split(r"[ !><=]", n=1, regex=True).str[0].str.strip()
    children_df = children_df.sort_values("display_order")

    from collections import defaultdict
    kids: Dict[str, List[pd.Series]] = defaultdict(list)
    for _, crow in children_df.iterrows():
        kids[str(crow["__parent_qid__"])].append(crow)

    rendered: set = set()

    def _widget_key(qid: str) -> str:
        return f"{dept_label}::{production}::{qid}"

    def _render_one(row: pd.Series):
        # Respect conditional visibility (including '=No', 'in [...]', etc.)
        if not question_is_visible(row, dept_label, production):
            return

        qid = str(row.get("question_id", "")).strip()
        if not qid or qid in rendered:
            return

        # Label
        raw_label = str(row.get("question_text", "") or "").strip()
        label = raw_label or str(row.get("metric", "") or "").strip() or qid
        required = bool(row.get("required", False))
        label_display = f"{label} *" if required else label

        # Response type & options
        rtype = str(row.get("response_type", "") or "").strip().lower()
        # aliases
        if rtype in ("select_yes_no", "radio_yes_no"):
            rtype = "yes_no"
        if rtype in ("select", "dropdownlist"):
            rtype = "dropdown"

        opts_raw = row.get("options", "")
        options: List[str] = []
        if isinstance(opts_raw, str) and opts_raw.strip():
            options = [o.strip() for o in opts_raw.split(",") if o.strip()]

        # Previous value
        prev_primary, prev_desc = get_answer_value(dept_label, production, qid)

        # Unique key
        widget_key = _widget_key(qid)
        entry: Dict[str, Any] = {"primary": None, "description": prev_desc}

        # Widgets
        if rtype == "yes_no":
            opts_display = ["— Select —"] + list(yes_no_opts)
            default_index = opts_display.index(prev_primary) if (prev_primary in yes_no_opts) else 0
            chosen = st.radio(
                label_display,
                opts_display,
                horizontal=True,
                key=widget_key,
                index=default_index,
            )
            entry["primary"] = chosen if chosen in yes_no_opts else None

        elif rtype == "scale_1_5":
            default_val = 3
            try:
                if isinstance(prev_primary, (int, float)) and 1 <= int(prev_primary) <= 5:
                    default_val = int(prev_primary)
            except Exception:
                pass
            entry["primary"] = int(
                st.slider(label_display, min_value=1, max_value=5, key=widget_key, value=default_val)
            )

        elif rtype == "number":
            default_val = float(prev_primary) if isinstance(prev_primary, (int, float)) else 0.0
            entry["primary"] = st.number_input(label_display, step=1.0, key=widget_key, value=default_val)

        elif rtype in ("dropdown", "select") and options:
            opts = options if (len(options) > 0 and options[0] == "— Select —") else (["— Select —"] + options)
            default_index = opts.index(prev_primary) if prev_primary in opts else 0
            chosen = st.selectbox(label_display, opts, key=widget_key, index=default_index)
            entry["primary"] = chosen if (chosen and chosen != "— Select —") else None

        else:
            default_text = str(prev_primary) if prev_primary is not None else ""
            entry["primary"] = st.text_area(label_display, key=widget_key, value=default_text, height=60)

        responses[qid] = entry
        rendered.add(qid)

    def _render_with_children(parent_row: pd.Series):
        _render_one(parent_row)
        pqid = str(parent_row.get("question_id", "")).strip()
        if not pqid:
            return
        # Render immediate children (that are visible) right after parent
        for child_row in kids.get(pqid, []):
            _render_one(child_row)
            _render_descendants(child_row)

    def _render_descendants(row: pd.Series):
        qid = str(row.get("question_id", "")).strip()
        if not qid:
            return
        for c2 in kids.get(qid, []):
            _render_one(c2)
            _render_descendants(c2)

    for _, prow in parents_df.iterrows():
        _render_with_children(prow)

    return responses

# ─────────────────────────────────────────────────────────────────────────────
# Draft helpers — queued apply to avoid "cannot be modified after widget" errors
# ─────────────────────────────────────────────────────────────────────────────
def queue_draft_bytes(draft_bytes: bytes) -> Tuple[bool, str]:
    """Queue a draft for application on the next run (before widgets are created)."""
    try:
        h = _hash_bytes(draft_bytes)
        if st.session_state.get("draft_hash") == h:
            return False, "This draft is already applied."
        st.session_state["pending_draft_bytes"] = draft_bytes
        st.session_state["pending_draft_hash"] = h
        return True, "Draft received; applying…"
    except Exception as e:
        return False, f"Could not queue draft: {e}"

def _apply_pending_draft_if_any():
    """Apply a pending draft BEFORE widgets are created."""
    b = st.session_state.get("pending_draft_bytes")
    h = st.session_state.get("pending_draft_hash")
    if not b:
        return

    try:
        data = json.loads(b.decode("utf-8"))
        answers = data.get("answers", {}) or {}
        meta = data.get("meta", {}) or {}
        per_show_answers = data.get("per_show_answers", {}) or {}

        dept_meta = meta.get("department")
        if dept_meta and dept_meta in DEPARTMENT_CONFIGS:
            questions_df = load_questions(DEPARTMENT_CONFIGS[dept_meta].questions_csv)
            qinfo = {str(row["question_id"]): row for _, row in questions_df.iterrows()}
        else:
            qinfo = {}

        def _normalise_loaded_entry(qid_str: str, raw_entry):
            entry = _normalise_show_entry(raw_entry)
            if entry is None:
                return {}
            row = qinfo.get(str(qid_str), {})
            rtype = str(row.get("response_type", "")).strip().lower()
            opts_raw = row.get("options", "")
            options = [o.strip() for o in str(opts_raw).split(",") if o.strip()]

            normalized: Dict[str, object] = {}
            val = entry.get("primary") if isinstance(entry, dict) else None

            if rtype == "yes_no":
                if val in YES_NO_OPTIONS:
                    normalized["primary"] = val
            elif rtype in ("select", "dropdown"):
                if val in options:
                    normalized["primary"] = val
            elif rtype == "scale_1_5":
                try:
                    ival = int(val)
                    if 1 <= ival <= 5:
                        normalized["primary"] = ival
                except Exception:
                    pass
            elif rtype == "number":
                try:
                    normalized["primary"] = float(val)
                except Exception:
                    pass
            else:
                if val is not None:
                    normalized["primary"] = str(val)

            if isinstance(entry, dict) and entry.get("description") not in (None, ""):
                normalized["description"] = str(entry["description"])

            return normalized

        rows: List[Dict[str, Any]] = []

        def _add_entries_for(dept_val: str, prod_val: str, answers_dict: dict):
            if not isinstance(answers_dict, dict):
                return
            for qid_str, raw_entry in answers_dict.items():
                normalized = _normalise_loaded_entry(str(qid_str), raw_entry)
                if not normalized:
                    continue
                rows.append(
                    {
                        "department": dept_val or "",
                        "production": prod_val or "",
                        "question_id": str(qid_str),
                        "primary": normalized.get("primary"),
                        "description": normalized.get("description", ""),
                    }
                )

        for show_key, show_entries in per_show_answers.items():
            if isinstance(show_key, str) and "::" in show_key:
                dept_val, prod_val = show_key.split("::", 1)
            else:
                dept_val = meta.get("department", "")
                prod_val = meta.get("production", "") or ""
            _add_entries_for(dept_val, prod_val, show_entries)

        if answers:
            dept_val = meta.get("department", "")
            prod_val = meta.get("production", "") or ""
            _add_entries_for(dept_val, prod_val, answers)

        if rows:
            df = pd.DataFrame(rows)
            df["question_id"] = df["question_id"].astype(str)
            df = df.drop_duplicates(
                subset=["department", "production", "question_id"], keep="last"
            )
            st.session_state["answers_df"] = df[
                ["department", "production", "question_id", "primary", "description"]
            ]
        else:
            st.session_state.pop("answers_df", None)

        # Apply meta to bound UI keys
        if "staff_name" in meta:
            st.session_state["staff_name"] = meta["staff_name"]
        if "role" in meta:
            st.session_state["role"] = meta["role"]
        if "month" in meta and isinstance(meta["month"], str):
            try:
                y, m = meta["month"].split("-")
                st.session_state["report_month_date"] = date(int(y), int(m), 1)
            except Exception:
                pass
        if "department" in meta and meta["department"] in DEPARTMENT_CONFIGS:
            st.session_state["dept_label"] = meta["department"]

        prod_norm = meta.get("production") or ""
        st.session_state["filter_production"] = prod_norm or GENERAL_PROD_LABEL

        st.session_state["loaded_draft"] = data
        st.session_state["draft_hash"] = h
        st.session_state["draft_applied"] = True

    except Exception as e:
        st.session_state["pending_draft_error"] = str(e)
    finally:
        st.session_state.pop("pending_draft_bytes", None)
        st.session_state.pop("pending_draft_hash", None)

# ─────────────────────────────────────────────────────────────────────────────
# Scope filtering helper
# ─────────────────────────────────────────────────────────────────────────────
def filter_questions_for_scope(questions_all_df: pd.DataFrame, current_production: str) -> pd.DataFrame:
    filtered = questions_all_df.copy()

    if "production" not in filtered.columns:
        return filtered

    prod_col = filtered["production"].astype(str).fillna("").str.strip()
    prod_lower = prod_col.str.lower()

    general_vals = ["", "all works", "school-wide", "corporate-wide", "all"]
    general_only_vals = ["general_only"]
    production_only_vals = ["production_only"]

    general_mask = prod_lower.isin(general_vals + general_only_vals)
    general_only_mask = prod_lower.isin(general_only_vals)
    production_only_mask = prod_lower.isin(production_only_vals)

    if current_production == "":
        filtered = filtered[general_mask & ~production_only_mask]
    else:
        cur_norm = current_production.strip()
        specific_mask = prod_col.str.casefold() == cur_norm.casefold()
        if specific_mask.any():
            filtered = filtered[
                (general_mask & ~general_only_mask & ~production_only_mask)
                | specific_mask
                | production_only_mask
            ]
        else:
            filtered = filtered[
                (general_mask & ~general_only_mask & ~production_only_mask)
                | production_only_mask
            ]
    return filtered

# ─────────────────────────────────────────────────────────────────────────────
# Export helpers
# ─────────────────────────────────────────────────────────────────────────────
def _normalise_answers_for_export(answers: Dict[str, dict]) -> Dict[str, dict]:
    export: Dict[str, dict] = {}
    for qid, entry in (answers or {}).items():
        normalised = _normalise_show_entry(entry)
        if not normalised:
            continue
        payload: Dict[str, object] = {}
        if "primary" in normalised:
            payload["primary"] = normalised["primary"]
        if "description" in normalised and normalised["description"] not in (None, ""):
            payload["description"] = normalised["description"]
        export[qid] = payload
    return export

def _build_show_key(department: str, show: str) -> str:
    dept_clean = (department or "").strip()
    show_clean = (show or "").strip()
    return f"{dept_clean}::{show_clean}"

def build_draft_from_state(
    all_questions_df: pd.DataFrame,
    meta: dict,
    current_production: Optional[str] = None,
    question_ids=None,
) -> dict:
    """
    Export a draft that:
      - puts the CURRENT department's CURRENT production answers under "answers"
      - puts ALL departments + productions under "per_show_answers"
    This lets one JSON restore School, Artistic, Corporate, etc., regardless of
    which department you were viewing when you saved.
    """
    # Normalize inputs
    question_ids = [str(q) for q in (question_ids or [])]
    qid_set = set(question_ids)

    dept = meta.get("department") or ""

    # Full in-memory store across *all* departments and productions
    answers_df_all = get_answers_df().copy()

    # ---------- CURRENT dept/prod -> "answers" ----------
    # Only this dept for the "answers" (what the UI reloads into immediately)
    df_curr = answers_df_all[answers_df_all["department"] == dept].copy()

    # Keep only the QIDs that exist in the current department's questions
    if not df_curr.empty:
        df_curr["question_id"] = df_curr["question_id"].astype(str)
        if qid_set:
            df_curr = df_curr[df_curr["question_id"].isin(qid_set)]

    # Determine which production the user is on: "" for General, else the name
    prod_for_current = (current_production or "")

    # Build "answers" for the current production
    current_answers: Dict[str, dict] = {}
    if not df_curr.empty:
        if prod_for_current != "":
            curr_df = df_curr[df_curr["production"] == prod_for_current]
        else:
            curr_df = df_curr[df_curr["production"] == ""]
        for _, row in curr_df.iterrows():
            qid = str(row["question_id"])
            entry: Dict[str, Any] = {}
            if row["primary"] not in (None, ""):
                entry["primary"] = row["primary"]
            desc = row.get("description", "")
            if desc not in (None, ""):
                entry["description"] = desc
            if entry:
                current_answers[qid] = entry

    draft = {
        "meta": meta,  # includes the CURRENT dept/prod/month etc.
        "answers": _normalise_answers_for_export(current_answers),
    }

    # ---------- ALL departments/prods -> "per_show_answers" ----------
    per_show_export: Dict[str, Dict[str, dict]] = {}
    if not answers_df_all.empty:
        # Do *not* filter by qid_set here — that would drop other departments' QIDs.
        answers_df_all["question_id"] = answers_df_all["question_id"].astype(str)

        for (d, p), grp in answers_df_all.groupby(["department", "production"]):
            show_key = _build_show_key(d, p)  # e.g., "School::" or "Artistic::Nutcracker"
            show_answers: Dict[str, dict] = {}
            for _, row in grp.iterrows():
                qid = str(row["question_id"])
                entry = {}
                if row["primary"] not in (None, ""):
                    entry["primary"] = row["primary"]
                desc = row.get("description", "")
                if desc not in (None, ""):
                    entry["description"] = desc
                if entry:
                    show_answers[qid] = entry

            normalised = _normalise_answers_for_export(show_answers)
            if normalised:
                per_show_export[show_key] = normalised

    if per_show_export:
        draft["per_show_answers"] = per_show_export

    return draft

# ─────────────────────────────────────────────────────────────────────────────
# Styling
# ─────────────────────────────────────────────────────────────────────────────
CUSTOM_CSS = """
<style>
html, body, [class*="stMarkdown"] { font-size: 1.0rem; }
h1 { font-size: 1.6rem !important; }
h2 { font-size: 1.3rem !important; }
h3 { font-size: 1.05rem !important; }
label, .stTextInput, .stNumberInput, .stSelectbox, .stRadio, .stDateInput, .stTextArea {
    font-size: 0.85rem !important;
}
.block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
</style>
"""

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    if "draft_applied" not in st.session_state:
        st.session_state["draft_applied"] = False

    # Apply any queued draft BEFORE widgets are created
    _apply_pending_draft_if_any()

    # Styles
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    # Sidebar: Draft controls
    st.sidebar.subheader("Drafts")
    draft_file = st.sidebar.file_uploader(
        "Load saved draft (JSON)",
        type="json",
        help="Upload a JSON draft you previously downloaded.",
    )
    if draft_file is not None:
        queued, msg = queue_draft_bytes(draft_file.getvalue())
        if queued:
            st.sidebar.success(msg)
            safe_rerun()
        else:
            st.sidebar.info(msg)

    if "pending_draft_error" in st.session_state:
        st.sidebar.error(f"Could not load draft: {st.session_state.pop('pending_draft_error')}")

    # Main UI
    st.title("Monthly Scorecard with AI Summary")
    st.caption(
        ":information_source: On Streamlit Community Cloud, the server file system is "
        "**not persistent**. To keep your progress, **download** a draft and "
        "**re-upload** it later."
    )

    # Identity & Date
    staff_name = st.text_input("Your name", key="staff_name")
    role = st.text_input("Your role / department title", key="role")

    from datetime import date as _date
    if "report_month_date" in st.session_state:
        month_date = st.date_input("Reporting period", key="report_month_date")
    else:
        month_date = st.date_input("Reporting period", value=_date.today(), key="report_month_date")

    month_str = (st.session_state.get("report_month_date") or _date.today()).strftime("%Y-%m")

    # ── 1) Department selector
    dept_label = st.selectbox(
        "Which area are you reporting on?",
        list(DEPARTMENT_CONFIGS.keys()),
        key="dept_label",
    )
    dept_cfg = DEPARTMENT_CONFIGS[dept_label]

    # Reset production when dept changes, but DO NOT clobber a draft-applied selection
    if "last_dept_label" not in st.session_state or st.session_state["last_dept_label"] != dept_label:
        if not st.session_state.get("draft_applied", False):
            if getattr(DEPARTMENT_CONFIGS[dept_label], "allow_general_option", True):
                st.session_state["filter_production"] = GENERAL_PROD_LABEL
            else:
                # Default to first available programme once we compute prod_options (done below)
                st.session_state.pop("filter_production", None)
        st.session_state["last_dept_label"] = dept_label

    # ── 2) Load questions for this department (disk first, upload only if missing)
    try:
        questions_all_df = load_questions(dept_cfg.questions_csv)
    except FileNotFoundError:
        st.warning(
            f"Couldn’t find the {dept_label} questions CSV at `{dept_cfg.questions_csv}`.\n"
            "If you have it locally, upload it below. (This prompt only appears when the file is missing.)"
        )
        missing_csv = st.file_uploader(
            f"Upload {dept_label} questions CSV",
            type=["csv"],
            key=f"fallback_questions_uploader::{dept_label}",
            help="Temporary fallback—upload only if the configured file isn’t available on disk."
        )
        if missing_csv is None:
            st.stop()
        try:
            questions_all_df = load_questions_from_bytes(missing_csv.getvalue())
            st.success(f"Using uploaded {dept_label} questions CSV for this session.")
        except Exception as e:
            st.error(f"Uploaded CSV couldn’t be parsed: {e}")
            st.stop()

    all_question_ids = questions_all_df["question_id"].astype(str).tolist()

    # ── 3) Scope selector (production / programme / general)
    st.subheader("Scope of this report")
    
    if dept_cfg.has_productions and dept_cfg.productions_csv:
        resolved_prod = _resolve_path(dept_cfg.productions_csv)
        if resolved_prod and os.path.exists(resolved_prod):
            productions_df = pd.read_csv(resolved_prod)
        else:
            productions_df = pd.DataFrame(columns=["department", "production_name", "active"])
    
        # Ensure required columns exist
        _ensure_col(productions_df, "department", "")
        _ensure_col(productions_df, "production_name", "")
        if "active" in productions_df.columns:
            productions_df["active"] = productions_df["active"].astype(str).str.upper().eq("TRUE")
        else:
            productions_df["active"] = True
    
        # Filter productions for current department
        dept_series = productions_df["department"].astype(str).str.strip().str.casefold()
        current_dept = (dept_label or "").strip().casefold()
        dept_prods = productions_df[(dept_series == current_dept) & (productions_df["active"])]
    
        # Build production options
        prod_list = sorted(dept_prods["production_name"].dropna().unique().tolist())
        if getattr(dept_cfg, "allow_general_option", True):
            # Include General if allowed
            prod_options = [GENERAL_PROD_LABEL] + prod_list if prod_list else [GENERAL_PROD_LABEL]
        else:
            # Exclude General completely
            prod_options = prod_list or []
            if not prod_options:
                st.error(
                    f"No active {dept_cfg.scope_label.lower()}s configured for {dept_label}. "
                    "Add rows to productions.csv."
                )
                st.stop()
    
        # Handle preselected value from session state
        preselected = st.session_state.get("filter_production")
        if preselected is None or preselected not in prod_options:
            # If General isn’t allowed, pick first programme automatically
            if not getattr(dept_cfg, "allow_general_option", True) and prod_options:
                preselected = prod_options[0]
                st.session_state["filter_production"] = preselected
    
        # Preserve a preloaded selection from a draft even if it isn't in the CSV
        preselected = st.session_state.get("filter_production", GENERAL_PROD_LABEL)
        if preselected and getattr(dept_cfg, "allow_general_option", True) and preselected != GENERAL_PROD_LABEL and preselected not in prod_options:
            # Keep General first; append the preselected one so Streamlit accepts the state
            prod_options = [GENERAL_PROD_LABEL] + sorted(set(prod_options[1:] + [preselected]))
    
        # Render dropdown
        sel_prod = st.selectbox(dept_cfg.scope_label, prod_options, key="filter_production")
    
    else:
        # No productions for this department → always general
        sel_prod = GENERAL_PROD_LABEL
        st.info(f"This area uses general questions only (no specific {dept_cfg.scope_label.lower()}s).")
    
    # ✅ Normalised production key for storage
    current_production = "" if sel_prod == GENERAL_PROD_LABEL else sel_prod
    
    # ── 4) Filter questions for display (CURRENT PRODUCTION ONLY)
    filtered = filter_questions_for_scope(questions_all_df, current_production)
    
    if filtered.empty:
        st.warning("No questions found for this combination. Try changing the scope.")
        return
    
    # Render form (tabs per pillar)
    st.markdown("### Scorecard Questions")
    tab_pillars = filtered["strategic_pillar"].dropna().unique().tolist()
    tabs = st.tabs(tab_pillars)
    
    responses: Dict[str, dict] = {}
    for tab, p in zip(tabs, tab_pillars):
        with tab:
            left_col, _ = st.columns([0.65, 0.35])
            with left_col:
                block = filtered[filtered["strategic_pillar"] == p]
                block_responses = build_form_for_questions(
                    block,
                    dept_label=dept_label,
                    production=current_production,
                )
                responses.update(block_responses)
    
    # Persist responses into answers_df
    for qid, entry in responses.items():
        upsert_answer(
            dept=dept_label,
            production=current_production,
            qid=qid,
            primary=entry.get("primary"),
            description=entry.get("description"),
        )
    
    submitted = st.button("Generate AI Summary & PDF", type="primary")

    # Meta
    meta = {
        "staff_name": st.session_state.get("staff_name") or "Unknown",
        "role": st.session_state.get("role") or "",
        "department": st.session_state.get("dept_label"),
        "month": month_str,
        "production": current_production,  # normalised: "" for General, else name
    }

    # Save progress (download JSON)
    draft_dict = build_draft_from_state(
        questions_all_df,
        meta,
        current_production=current_production,
        question_ids=all_question_ids,
    )
    st.sidebar.download_button(
        "💾 Save progress (JSON)",
        data=json.dumps(draft_dict, indent=2),
        file_name=f"scorecard_draft_{meta['department'].replace(' ', '_')}_{month_str}.json",
        mime="application/json",
        help="Downloads a snapshot of your current answers (this and other productions). Re-upload later to continue.",
    )
    st.sidebar.download_button(
        "⬇️ Download answers CSV",
        data=get_answers_df().to_csv(index=False),
        file_name="scorecard_answers.csv",
        mime="text/csv",
    )

    if not submitted:
        return

    # visible-only validation (CURRENT PRODUCTION ONLY)
    missing_required: List[str] = []
    for _, row in filtered.iterrows():
        if not question_is_visible(row, dept_label, current_production):
            continue
        if bool(row.get("required", False)):
            qid = str(row["question_id"])
            val = responses.get(qid)
            primary_val = val.get("primary") if isinstance(val, dict) else val
            is_empty = (primary_val is None) or (isinstance(primary_val, str) and primary_val.strip() == "")
            if is_empty:
                qt = str(row.get("question_text") or "").strip()
                missing_required.append(qt or qid)

    if missing_required:
        st.error("Please answer all required questions before generating the summary.")
        with st.expander("Missing required questions"):
            for q in missing_required:
                st.write("• ", q)
        return

    # ─────────────────────────────────────────────────────────────
    # Build AI/PDF scope
    #
    # Default: use the CURRENT scope (this production only).
    # For Artistic: widen to ALL Artistic productions for this month,
    # and attach a production_title column with the real show name.
    # ─────────────────────────────────────────────────────────────
    questions_for_ai = filtered
    responses_for_ai = responses
    meta_for_ai = meta

    if dept_label in ("Artistic", "Community"):
        # Base questions for this department
        questions_dept = questions_all_df.copy()

        # Optional: filter questions by department column if present
        dept_col_q = None
        for cand in ["department", "dept"]:
            if cand in questions_dept.columns:
                dept_col_q = cand
                break
        if dept_col_q is not None:
            questions_dept = questions_dept[questions_dept[dept_col_q] == dept_label].copy()

        # All saved answers
        answers_df = get_answers_df().copy()

        # Filter answers to this department
        dept_col_a = None
        for cand in ["department", "dept"]:
            if cand in answers_df.columns:
                dept_col_a = cand
                break
        if dept_col_a is not None:
            answers_scope = answers_df[answers_df[dept_col_a] == dept_label].copy()
        else:
            answers_scope = answers_df.copy()

        # Filter answers to this reporting month if available
        if "month" in answers_scope.columns:
            month_series = answers_scope["month"].astype(str)
            answers_scope = answers_scope[month_series.str.slice(0, 7) == month_str]

        if answers_scope.empty:
            # No saved answers beyond current production → fall back
            questions_for_ai = filtered
            responses_for_ai = responses
        else:
            answers_scope = answers_scope.copy()
            answers_scope["question_id"] = answers_scope["question_id"].astype(str)
            answers_scope["production"] = answers_scope["production"].astype(str)

            # Lookup: question_id → question metadata dict
            q_lookup = (
                questions_dept
                .set_index(questions_dept["question_id"].astype(str))
                .to_dict(orient="index")
            )

            rows_for_ai: List[dict] = []
            responses_for_ai = {}

            for _, arow in answers_scope.iterrows():
                qid_base = str(arow["question_id"])
                q_meta = q_lookup.get(qid_base)
                if not q_meta:
                    continue  # question not in this dept file; skip

                prod_title = str(arow.get("production") or "").strip()  # e.g., "Nijinsky", "Once Upon a Time", "" for General

                # Composite id so each (question, production) pair is distinct to the model
                composite_qid = f"{qid_base}::{prod_title or 'General'}"

                # Copy metadata and attach production_title + composite_id
                q_row = dict(q_meta)
                q_row["question_id"] = composite_qid
                q_row["production_title"] = prod_title
                rows_for_ai.append(q_row)

                responses_for_ai[composite_qid] = {
                    "primary": arow.get("primary"),
                    "description": arow.get("description"),
                }

            if rows_for_ai:
                questions_for_ai = pd.DataFrame(rows_for_ai)
            else:
                # Fallback: nothing matched, use current scope
                questions_for_ai = filtered
                responses_for_ai = responses

        meta_for_ai = dict(meta)
        meta_for_ai["production"] = ""  # dept-wide summary
        meta_for_ai["scope"] = "department_all_productions"


    # ─────────────────────────────────────────────────────────────
    # AI call
    # ─────────────────────────────────────────────────────────────
    try:
        with st.spinner("Asking AI to interpret this scorecard..."):
            ai_result = interpret_scorecard(meta_for_ai, questions_for_ai, responses_for_ai)
    except RuntimeError as e:
        st.error(f"AI configuration error: {e}")
        st.info("Check your OPENAI_API_KEY secret and that `openai>=1.51.0` (or newer) is in requirements.txt.")
        st.stop()
    except Exception as e:
        st.error(f"Failed to generate AI summary: {e}")
        st.stop()

    st.success("AI summary generated.")

    # ─────────────────────────────────────────────────────────────
    # AI Interpretation (fully editable before PDF)
    # ─────────────────────────────────────────────────────────────
    st.subheader("AI Interpretation (editable)")

    # ----- helpers just for this block --------------------------------
    def _normalise_overall(val):
        """Turn overall_summary (string / list / dict) into a single editable string."""
        if isinstance(val, list):
            parts = []
            for v in val:
                if isinstance(v, dict) and "text" in v:
                    parts.append(str(v["text"]))
                else:
                    parts.append(str(v))
            return "\n\n".join(p for p in parts if str(p).strip())
        if isinstance(val, dict) and "text" in val:
            return str(val["text"])
        return str(val or "")

    def _normalise_list(val):
        """Turn list-like fields (risks, priorities) into newline-separated text."""
        if not val:
            return ""
        if isinstance(val, list):
            return "\n".join(str(x) for x in val if str(x).strip())
        return str(val or "")

    # ── Executive Summary (editable) ──────────────────────────────
    raw_overall = ai_result.get("overall_summary", "")
    default_overall = _normalise_overall(raw_overall)

    st.markdown("### Executive Summary")
    editable_overall = st.text_area(
        "You can edit this summary before exporting to PDF:",
        value=default_overall,
        height=260,
    )
    ai_result["overall_summary"] = editable_overall

    # Optional immediate display of the final version
    if editable_overall.strip():
        st.markdown("#### Final Executive Summary (will appear in PDF)")
        st.write(editable_overall)
        st.write("")

    # ── Pillar summaries (editable) ──────────────────────────────
    pillar_summaries = ai_result.get("pillar_summaries", []) or []
    st.markdown("### Strategic Summary by Pillar")

    if pillar_summaries:
        for i, ps in enumerate(pillar_summaries):
            pillar_label = ps.get("strategic_pillar", "Pillar") or "Pillar"
            score_hint_val = str(ps.get("score_hint", "") or "")
            summary_val = str(ps.get("summary", "") or "")

            st.markdown(f"#### Pillar {i+1}: {pillar_label}")

            new_pillar_label = st.text_input(
                f"Pillar name (Pillar {i+1})",
                value=pillar_label,
                key=f"pillar_name_{i}",
            )
            new_score_hint = st.text_input(
                f"Score hint (Pillar {i+1})",
                value=score_hint_val,
                key=f"pillar_score_{i}",
            )
            new_summary = st.text_area(
                f"Pillar narrative (Pillar {i+1})",
                value=summary_val,
                height=140,
                key=f"pillar_summary_{i}",
            )

            # write back into ai_result
            ps["strategic_pillar"] = new_pillar_label
            ps["score_hint"] = new_score_hint
            ps["summary"] = new_summary

    # ── By Production / Programme (editable text) ─────────────────
    prod_summaries = ai_result.get("production_summaries", []) or []
    if prod_summaries:
        st.markdown("### By Production / Programme")

        for pi, prod in enumerate(prod_summaries):
            if not isinstance(prod, dict):
                continue

            pname = prod.get("production") or "General"
            st.markdown(f"#### Production {pi+1}: {pname}")

            # allow renaming the production label if desired
            new_pname = st.text_input(
                f"Production name (Production {pi+1})",
                value=pname,
                key=f"prod_name_{pi}",
            )
            prod["production"] = new_pname

            pillars = prod.get("pillars") or []
            for pj, ps in enumerate(pillars):
                pillar_name = ps.get("pillar", "Category") or "Category"
                score_hint = str(ps.get("score_hint", "") or "")
                summary = str(ps.get("summary", "") or "")

                st.markdown(f"- **Pillar {pj+1}: {pillar_name}**")

                new_pillar_name = st.text_input(
                    f"  Pillar name (Prod {pi+1}, Pillar {pj+1})",
                    value=pillar_name,
                    key=f"prod_{pi}_pillar_name_{pj}",
                )
                new_pillar_score = st.text_input(
                    f"  Score hint (Prod {pi+1}, Pillar {pj+1})",
                    value=score_hint,
                    key=f"prod_{pi}_pillar_score_{pj}",
                )
                new_pillar_summary = st.text_area(
                    f"  Narrative (Prod {pi+1}, Pillar {pj+1})",
                    value=summary,
                    height=120,
                    key=f"prod_{pi}_pillar_summary_{pj}",
                )

                ps["pillar"] = new_pillar_name
                ps["score_hint"] = new_pillar_score
                ps["summary"] = new_pillar_summary

    # ── Risks (editable) ─────────────────────────────────────────
    risks_raw = ai_result.get("risks", []) or []
    risks_default = _normalise_list(risks_raw)

    st.markdown("### Key Risks / Concerns")
    risks_edited = st.text_area(
        "One risk per line:",
        value=risks_default,
        height=140,
    )
    ai_result["risks"] = [
        line.strip() for line in risks_edited.splitlines() if line.strip()
    ]

    # ── Priorities (editable) ────────────────────────────────────
    priorities_raw = ai_result.get("priorities_next_month", []) or []
    priorities_default = _normalise_list(priorities_raw)

    st.markdown("### Priorities for Next Period")
    priorities_edited = st.text_area(
        "One priority per line:",
        value=priorities_default,
        height=140,
    )
    ai_result["priorities_next_month"] = [
        line.strip() for line in priorities_edited.splitlines() if line.strip()
    ]

    # ── Notes for Leadership (editable) ─────────────────────────
    nfl_raw = ai_result.get("notes_for_leadership", "") or ""
    nfl_default = str(nfl_raw)

    st.markdown("### Notes for Leadership")
    nfl_edited = st.text_area(
        "Notes for Leadership:",
        value=nfl_default,
        height=160,
    )
    ai_result["notes_for_leadership"] = nfl_edited


    # ─────────────────────────────────────────────────────────────
    # PDF — uses the SAME scope as AI (questions_for_ai / responses_for_ai)
    # and keeps all original columns (including display_order)
    # ─────────────────────────────────────────────────────────────
    try:
        pdf_bytes = build_scorecard_pdf(
            meta_for_ai,
            questions_for_ai,
            responses_for_ai,
            ai_result,
            logo_path="assets/alberta_ballet_logo.png",
        )
        st.download_button(
            label="Download PDF report",
            data=pdf_bytes,
            file_name=f"scorecard_{meta_for_ai['department'].replace(' ', '_')}_{month_str}.pdf",
            mime="application/pdf",
        )
    except Exception as e:
        st.warning(f"PDF export failed: {e}")
        st.info("If this persists, check pdf_utils.py dependencies (reportlab or fpdf2).")


if __name__ == "__main__":
    main()
