# app.py

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Dict, Tuple

import pandas as pd
import streamlit as st

from config import DEPARTMENT_FILES, YES_NO_OPTIONS
from ai_utils import interpret_scorecard
from pdf_utils import build_scorecard_pdf


# ─────────────────────────────────────────────────────────────────────────────
# MUST be the first Streamlit call
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Monthly Scorecard", layout="wide")

GENERAL_PROD_LABEL = "General"


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
              "question_text", "response_type", "options"):
        _ensure_col(df, c, "")

    # Defaults for grouping/rendering
    df["section"] = df["section"].replace("", "General")
    df["response_type"] = df["response_type"].replace("", "text")

    return df


@st.cache_data
def load_productions() -> pd.DataFrame:
    """
    data/productions.csv
    Expected columns: department, production_name, active (TRUE/FALSE)
    """
    df = pd.read_csv("data/productions.csv")
    _ensure_col(df, "department", "")
    _ensure_col(df, "production_name", "")
    if "active" in df.columns:
        df["active"] = df["active"].astype(str).str.upper().eq("TRUE")
    else:
        df["active"] = True
    return df

# ─────────────────────────────────────────────────────────────────────────────
# Conditional visibility rules
# ─────────────────────────────────────────────────────────────────────────────
def should_show_question(qid: str, dept_label: str, production: str) -> bool:
    """
    Decide whether a question should be shown, based on answers to other questions.
    Uses Streamlit session_state values for the controlling questions.
    """
    base = f"{dept_label}::{production}::"

    def v(other_qid: str):
        return st.session_state.get(f"{base}{other_qid}")

    # Innovation & Sustainability
    if qid == "ATI04":  # Reusable Elements Description
        return v("ATI03") == "Yes"
    if qid == "ATI06":  # Efficiency / Capability Gains Description
        return v("ATI05") == "Yes"

    # Artistic contributions & social impact
    if qid == "ACSI03":  # Social / Community Issues Description
        return v("ACSI02") == "Yes"
    if qid == "ACSI05":  # Alberta-based Artists Description
        return v("ACSI04") == "Yes"

    # Collaborations & residencies
    if qid == "CR02":  # External Collaborators Description
        return v("CR01") == "Yes"
    if qid == "CR04":  # Artistic Residencies Description
        return v("CR03") == "Yes"

    # Recruitment & auditions
    if qid in ("RA02", "RA03"):  # Recruitment Timing / Volume & Hires
        return v("RA01") == "Yes"

    # Festivals & events
    if qid in ("FE02", "FE03"):  # Festival / Event Details & Outcomes
        return v("FE01") == "Yes"

    # Luxury brands
    if qid == "FM07":  # Luxury Brand Involvement Description
        return v("FM06") == "Yes"

    # Default: visible
    return True

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

    # We already filtered by pillar in main(), so just sort and iterate
    df = df.sort_values("display_order")

    for _, row in df.iterrows():
        qid = str(row["question_id"])  # ALWAYS STRING

        # Conditional visibility
        if not should_show_question(qid, dept_label, production):
            continue

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
            # Radio for Yes / No
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

            # If answered "Yes", show a follow-up description box
            if entry["primary"] == "Yes":
                desc_key = f"{widget_key}__desc"
                default_desc = prev_desc or ""
                entry["description"] = st.text_area(
                    "If yes, briefly describe:",
                    key=desc_key,
                    value=default_desc,
                    height=60,
                )
            else:
                # Clear description if they change back to "No"
                entry["description"] = ""

        elif rtype == "scale_1_5":

            default_val = 3
            if isinstance(prev_primary, (int, float)) and 1 <= int(prev_primary) <= 5:
                default_val = int(prev_primary)
            entry["primary"] = int(
                st.slider(label_display, min_value=1, max_value=5, key=widget_key, value=default_val)
            )
        elif rtype == "number":
            default_val = float(prev_primary) if isinstance(prev_primary, (int, float)) else 0.0
            entry["primary"] = st.number_input(label_display, step=1.0, key=widget_key, value=default_val)
        elif (rtype in ("select", "dropdown")) and options:
            default = prev_primary if prev_primary in options else options[0]
            entry["primary"] = st.selectbox(
                label_display,
                options,
                key=widget_key,
                index=options.index(default),
            )
        else:
            default_text = str(prev_primary) if prev_primary is not None else ""
            entry["primary"] = st.text_area(label_display, key=widget_key, value=default_text, height=60)

        responses[qid] = entry

    return responses


# ─────────────────────────────────────────────────────────────────────────────
# Draft helpers — queued apply to avoid "cannot be modified after widget" errors
# ─────────────────────────────────────────────────────────────────────────────
def queue_draft_bytes(draft_bytes: bytes) -> Tuple[bool, str]:
    """
    Queue a draft for application on the next run (before widgets are created).
    Returns (queued, message).
    """
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
    """
    If a pending draft exists, apply it BEFORE widgets are created.
    Populates answers_df from draft['answers'] + draft['per_show_answers'].
    """
    b = st.session_state.get("pending_draft_bytes")
    h = st.session_state.get("pending_draft_hash")
    if not b:
        return

    try:
        data = json.loads(b.decode("utf-8"))
        answers = data.get("answers", {}) or {}
        meta = data.get("meta", {}) or {}
        per_show_answers = data.get("per_show_answers", {}) or {}

        # Load questions for department to normalise types
        dept_meta = meta.get("department")
        if dept_meta and dept_meta in DEPARTMENT_FILES:
            questions_df = load_questions(DEPARTMENT_FILES[dept_meta])
            qinfo = {row["question_id"]: row for _, row in questions_df.iterrows()}
        else:
            qinfo = {}

        def _normalise_loaded_entry(qid_str: str, raw_entry):
            entry = _normalise_show_entry(raw_entry)
            if entry is None:
                return {}
            row = qinfo.get(qid_str, {})
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

        rows = []

        def _add_entries_for(dept_val: str, prod_val: str, answers_dict: dict):
            if not isinstance(answers_dict, dict):
                return
            for qid_str, raw_entry in answers_dict.items():
                normalized = _normalise_loaded_entry(qid_str, raw_entry)
                if not normalized:
                    continue
                rows.append(
                    {
                        "department": dept_val or "",
                        "production": prod_val or "",
                        "question_id": qid_str,
                        "primary": normalized.get("primary"),
                        "description": normalized.get("description", ""),
                    }
                )

        # First: multi-show data, if present
        for show_key, show_entries in per_show_answers.items():
            if isinstance(show_key, str) and "::" in show_key:
                dept_val, prod_val = show_key.split("::", 1)
            else:
                dept_val = meta.get("department", "")
                prod_val = meta.get("production", "") or ""
            _add_entries_for(dept_val, prod_val, show_entries)

        # Then: top-level answers (current show) as a fallback
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
        if "department" in meta and meta["department"] in DEPARTMENT_FILES:
            st.session_state["dept_label"] = meta["department"]

        # Restore current production filter (UI label)
        prod_norm = meta.get("production") or ""
        if not prod_norm:
            st.session_state["filter_production"] = GENERAL_PROD_LABEL
        else:
            st.session_state["filter_production"] = prod_norm

        st.session_state["loaded_draft"] = data
        st.session_state["draft_hash"] = h
        st.session_state["draft_applied"] = True

    except Exception as e:
        st.session_state["pending_draft_error"] = str(e)
    finally:
        st.session_state.pop("pending_draft_bytes", None)
        st.session_state.pop("pending_draft_hash", None)


def clear_form(all_questions_df: pd.DataFrame):
    """Clears answers for the current department's questions and resets draft flags."""
    keys_to_clear = []
    for _, row in all_questions_df.iterrows():
        qid = row["question_id"]
        keys_to_clear.extend([qid, f"{qid}_desc"])
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]

    for k in ("staff_name", "role", "report_month_date", "filter_production"):
        st.session_state.pop(k, None)

    st.session_state.pop("answers_df", None)

    st.session_state.pop("draft_applied", None)
    st.session_state.pop("draft_hash", None)
    st.session_state.pop("loaded_draft", None)


def _normalise_answers_for_export(answers: Dict[str, dict]) -> Dict[str, dict]:
    """Ensure exported answers contain only supported keys and non-null entries."""
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
    current_production: str | None = None,
    question_ids=None,
) -> dict:
    """
    Build a draft from answers_df, including:
    - answers: current production's answers
    - per_show_answers: all (department, production) answers
    """
    question_ids = [str(q) for q in (question_ids or [])]
    qid_set = set(question_ids)

    dept = meta.get("department") or ""
    answers_df = get_answers_df()

    # Only this department's answers
    df = answers_df[answers_df["department"] == dept].copy()
    if not df.empty:
        df["question_id"] = df["question_id"].astype(str)
        if qid_set:
            df = df[df["question_id"].isin(qid_set)]

    # Decide which production is "current"
    prod_for_current = current_production or ""

    # Current production's answers → draft["answers"]
    current_answers: Dict[str, dict] = {}
    if not df.empty:
        if prod_for_current != "":
            curr_df = df[df["production"] == prod_for_current]
        else:
            curr_df = df[df["production"] == ""]  # general rows

        for _, row in curr_df.iterrows():
            qid = str(row["question_id"])
            entry = {}
            if row["primary"] not in (None, ""):
                entry["primary"] = row["primary"]
            desc = row.get("description", "")
            if desc not in (None, ""):
                entry["description"] = desc
            if entry:
                current_answers[qid] = entry

    draft = {
        "meta": meta,
        "answers": _normalise_answers_for_export(current_answers),
    }

    # All shows → draft["per_show_answers"]
    per_show_export: Dict[str, Dict[str, dict]] = {}
    if not df.empty:
        for (d, p), grp in df.groupby(["department", "production"]):
            show_key = _build_show_key(d, p)
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
# Main App
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
        month_date = st.date_input("Reporting month", key="report_month_date")
    else:
        month_date = st.date_input("Reporting month", value=_date.today(), key="report_month_date")

    month_str = (st.session_state.get("report_month_date") or _date.today()).strftime("%Y-%m")

    # Department
    dept_label = st.selectbox(
        "Which area are you reporting on?",
        list(DEPARTMENT_FILES.keys()),
        key="dept_label",
    )

    questions_all_df = load_questions(DEPARTMENT_FILES[dept_label])
    all_question_ids = questions_all_df["question_id"].astype(str).tolist()

    # Scope: Production / area
    st.subheader("Scope of this report")

    productions_df = load_productions()
    dept_series = productions_df["department"].astype(str).str.strip().str.lower()
    current_dept = (dept_label or "").strip().lower()
    dept_prods = productions_df[(dept_series == current_dept) & (productions_df["active"])]
    if dept_prods.empty:
        dept_prods = productions_df[productions_df["active"]]

    prod_list = sorted(dept_prods["production_name"].dropna().unique().tolist())
    prod_options = [GENERAL_PROD_LABEL] + prod_list

    sel_prod = st.selectbox("Production / area", prod_options, key="filter_production")

    # Normalised production key for storage: "" for General, or the production name
    if sel_prod == GENERAL_PROD_LABEL:
        current_production = ""
    else:
        current_production = sel_prod

    # Filter questions for display
    filtered = questions_all_df.copy()
    if "production" in filtered.columns:
        prod_col = filtered["production"].astype(str).fillna("").str.strip()
        prod_lower = prod_col.str.lower()

        # General questions (apply broadly)
        general_vals = ["", "all works", "school-wide", "corporate-wide", "all"]
        # General-only questions: shown only when "General" is selected
        general_only_vals = ["general_only"]
        # Production-only questions: shown only when a specific production is selected
        production_only_vals = ["production_only"]

        general_mask = prod_lower.isin(general_vals + general_only_vals)
        general_only_mask = prod_lower.isin(general_only_vals)
        production_only_mask = prod_lower.isin(production_only_vals)

        if current_production == "":
            # General: show general + general-only, but NOT production-only
            filtered = filtered[general_mask & ~production_only_mask]
        else:
            # Specific production: include
            # - general (but NOT general-only or production-only),
            # - this production's specific questions,
            # - all PRODUCTION_ONLY questions
            cur_norm = current_production.strip()
            specific_mask = prod_col.str.casefold() == cur_norm.casefold()

            if specific_mask.any():
                filtered = filtered[
                    (general_mask & ~general_only_mask & ~production_only_mask)
                    | specific_mask
                    | production_only_mask
                ]
            else:
                # If there are no specific questions for this production:
                # show general (not general-only / production-only) + PRODUCTION_ONLY
                filtered = filtered[
                    (general_mask & ~general_only_mask & ~production_only_mask)
                    | production_only_mask
                ]



    if filtered.empty:
        st.warning("No questions found for this combination. Try changing the production.")
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
                responses.update(
                    build_form_for_questions(
                        block,
                        dept_label=dept_label,
                        production=current_production,
                    )
                )

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

    # Save progress (download JSON) — includes all productions for this department
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

    # Validation (visible questions only)
    missing_required = []
    for _, row in filtered.iterrows():
        if bool(row.get("required", False)):
            qid = row["question_id"]
            val = responses.get(qid, None)
            primary_val = val.get("primary", None) if isinstance(val, dict) else val
            if primary_val in (None, "", []):
                qt = str(row.get("question_text") or "").strip()
                missing_required.append(qt or qid)


    if missing_required:
        st.error("Please answer all required questions before generating the summary.")
        with st.expander("Missing required questions"):
            for q in missing_required:
                st.write("• ", q)
        return

    # AI call
    try:
        with st.spinner("Asking AI to interpret this scorecard..."):
            ai_result = interpret_scorecard(meta, filtered, responses)
    except RuntimeError as e:
        st.error(f"AI configuration error: {e}")
        st.info("Check your OPENAI_API_KEY secret and that `openai>=1.51.0` (or newer) is in requirements.txt.")
        st.stop()
    except Exception as e:
        st.error(f"Failed to generate AI summary: {e}")
        st.stop()

    st.success("AI summary generated.")

    # AI Interpretation
    st.subheader("AI Interpretation")
    st.markdown("#### Overall Summary")
    st.write(ai_result.get("overall_summary", ""))

    pillar_summaries = ai_result.get("pillar_summaries", []) or []
    if pillar_summaries:
        st.markdown("#### By Strategic Pillar")
        for ps in pillar_summaries:
            st.markdown(
                f"**{ps.get('strategic_pillar', 'Pillar')} — {ps.get('score_hint', '')}**"
            )
            st.write(ps.get("summary", ""))

    risks = ai_result.get("risks", []) or []
    if risks:
        st.markdown("#### Key Risks / Concerns")
        for r in risks:
            st.write(f"- {r}")

    priorities = ai_result.get("priorities_next_month", []) or []
    if priorities:
        st.markdown("#### Priorities for Next Month")
        for p in priorities:
            st.write(f"- {p}")

    nfl = ai_result.get("notes_for_leadership", "")
    if nfl:
        st.markdown("#### Notes for Leadership")
        st.write(nfl)

    # PDF
    try:
        pdf_bytes = build_scorecard_pdf(meta, filtered, responses, ai_result)
        st.download_button(
            label="Download PDF report",
            data=pdf_bytes,
            file_name=f"scorecard_{meta['department'].replace(' ', '_')}_{month_str}.pdf",
            mime="application/pdf",
        )
    except Exception as e:
        st.warning(f"PDF export failed: {e}")
        st.info("If this persists, check pdf_utils.py dependencies (reportlab or fpdf2).")


if __name__ == "__main__":
    main()
