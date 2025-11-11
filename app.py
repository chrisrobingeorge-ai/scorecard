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

# ---------------------------------------------------------------------
# Streamlit config MUST be the first Streamlit call
# ---------------------------------------------------------------------
st.set_page_config(page_title="Monthly Scorecard", layout="wide")


# ---------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------
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


# ---------------------------------------------------------------------
# Data loading (cached)
# ---------------------------------------------------------------------
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


# ---------------------------------------------------------------------
# Form rendering
# ---------------------------------------------------------------------
def build_form_for_questions(df: pd.DataFrame) -> Dict[str, dict]:
    """
    Render widgets for each question, grouped by pillar + production.
    Uses st.session_state for initial values. Returns {qid: {primary, description}}.
    """
    responses: Dict[str, dict] = {}

    df = df.copy()
    df["strategic_pillar"] = df["strategic_pillar"].replace("", "General")
    df["production"] = df["production"].replace("", "All works")
    df["metric"] = df["metric"].fillna("")
    df["display_order"] = pd.to_numeric(df.get("display_order", 0), errors="coerce").fillna(0)

    pillars = df["strategic_pillar"].unique()

    for pillar in pillars:
        pillar_block = df[df["strategic_pillar"] == pillar].sort_values(
            ["production", "display_order"]
        )
        st.markdown(f"### {pillar}")

        for production in pillar_block["production"].unique():
            prod_block = pillar_block[pillar_block["production"] == production]

            # Sub-heading for specific productions only
            if production and str(production).strip().lower() not in (
                "school-wide",
                "corporate-wide",
                "all works",
            ):
                st.markdown(f"**{production}**")

            cols = st.columns(2)
            for idx, (_, row) in enumerate(prod_block.iterrows()):
                col = cols[idx % 2]
                with col:
                    qid = row["question_id"]  # ALWAYS STRING

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

                    entry = {"primary": None, "description": None}

                    # Primary control by type
                    if rtype == "yes_no":
                        entry["primary"] = st.radio(
                            label_display, YES_NO_OPTIONS, horizontal=True, key=qid
                        )
                    elif rtype == "scale_1_5":
                        entry["primary"] = int(st.slider(label_display, 1, 5, 3, key=qid))
                    elif rtype == "number":
                        entry["primary"] = st.number_input(label_display, value=0.0, step=1.0, key=qid)
                    elif rtype == "select" and options:
                        entry["primary"] = st.selectbox(label_display, options, key=qid)
                    else:
                        entry["primary"] = st.text_area(label_display, key=qid, height=60)

                    # Description control for certain types
                    show_desc = rtype in ("yes_no", "scale_1_5", "number", "select")
                    if show_desc:
                        metric = str(row.get("metric", "") or "").strip()
                        desc_label = (metric + " – description / notes") if metric else "Description / notes"
                        entry["description"] = st.text_area(
                            desc_label, key=f"{qid}_desc", height=60
                        )

                    responses[qid] = entry

    return responses


# ---------------------------------------------------------------------
# Draft helpers
# ---------------------------------------------------------------------
def apply_draft_bytes(draft_bytes: bytes) -> Tuple[bool, str]:
    """
    Apply a draft (bytes). Returns (applied, message).
    Applies even if a different draft was already applied in this session.
    """
    try:
        content = draft_bytes.decode("utf-8")
        h = _hash_bytes(draft_bytes)

        # Skip if already applied this exact content
        if st.session_state.get("draft_hash") == h:
            return False, "This draft is already applied."

        data = json.loads(content)
        answers = data.get("answers", {}) or {}
        meta = data.get("meta", {}) or {}

        # 1) Apply answers into session_state
        for qid_str, entry in answers.items():
            st.session_state[qid_str] = entry.get("primary", None)
            st.session_state[f"{qid_str}_desc"] = entry.get("description", None)

        # 2) Apply meta to bound UI keys so widgets reflect the draft immediately
        if "staff_name" in meta:
            st.session_state["staff_name"] = meta["staff_name"]
        if "role" in meta:
            st.session_state["role"] = meta["role"]

        if "month" in meta and isinstance(meta["month"], str):
            # "YYYY-MM" -> set to first of that month
            try:
                y, m = meta["month"].split("-")
                st.session_state["report_month_date"] = date(int(y), int(m), 1)
            except Exception:
                pass

        if "department" in meta and meta["department"] in DEPARTMENT_FILES:
            st.session_state["dept_label"] = meta["department"]

        # Filters
        if "filter_pillar" in meta:
            st.session_state["filter_pillar"] = meta["filter_pillar"]
        st.session_state["filter_production"] = meta.get("production") or "All"

        # Book-keeping
        st.session_state["loaded_draft"] = data
        st.session_state["draft_hash"] = h
        st.session_state["draft_applied"] = True

        return True, "Draft loaded and applied to the form."

    except Exception as e:
        return False, f"Could not load draft: {e}"


def clear_form(all_questions_df: pd.DataFrame):
    """
    Clears answers for the current department's questions and resets draft flags.
    """
    keys_to_clear = []
    for _, row in all_questions_df.iterrows():
        qid = row["question_id"]
        keys_to_clear.extend([qid, f"{qid}_desc"])
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]

    # Clear meta-bound keys (leave department so user doesn't lose context)
    for k in ("staff_name", "role", "report_month_date",
              "filter_pillar", "filter_production"):
        st.session_state.pop(k, None)

    st.session_state.pop("draft_applied", None)
    st.session_state.pop("draft_hash", None)
    st.session_state.pop("loaded_draft", None)


def build_draft_from_state(all_questions_df: pd.DataFrame, meta: dict) -> dict:
    """
    Build a draft by scanning session_state for ALL questions in the department.
    """
    draft = {"meta": meta, "answers": {}}
    for _, row in all_questions_df.iterrows():
        qid = row["question_id"]  # STRING
        primary = st.session_state.get(qid, None)
        desc = st.session_state.get(f"{qid}_desc", None)
        if primary is not None or (desc not in (None, "")):
            draft["answers"][qid] = {"primary": primary, "description": desc}
    return draft


# ---------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------
def main():
    st.title("Monthly Scorecard with AI Summary")
    st.caption(
        ":information_source: On Streamlit Community Cloud, the server file system is "
        "**not persistent**. To keep your progress, **download** a draft and "
        "**re-upload** it later."
    )
    st.sidebar.info(f"Streamlit version: {st.__version__}")

    # Init flags
    if "draft_applied" not in st.session_state:
        st.session_state["draft_applied"] = False

    # ------------- Identity & Date (BOUND TO SESSION STATE) -------------
    staff_name = st.text_input("Your name", key="staff_name")
    role = st.text_input("Your role / department title", key="role")
    month_date = st.date_input("Reporting month", value=date.today(), key="report_month_date")
    month_str = (st.session_state.get("report_month_date") or date.today()).strftime("%Y-%m")

    # ------------------------ Department (BOUND) ------------------------
    dept_label = st.selectbox(
        "Which area are you reporting on?",
        list(DEPARTMENT_FILES.keys()),
        key="dept_label",
    )

    # Load all questions for this department
    questions_all_df = load_questions(DEPARTMENT_FILES[dept_label])

    # ----------------------------- Filters ------------------------------
    st.subheader("Scope of this report")

    pillars = ["All"] + sorted(questions_all_df["strategic_pillar"].dropna().unique().tolist())
    productions_df = load_productions()
    dept_series = productions_df["department"].astype(str).str.strip().str.lower()
    current_dept = (dept_label or "").strip().lower()
    dept_prods = productions_df[(dept_series == current_dept) & (productions_df["active"])]
    if dept_prods.empty:
        dept_prods = productions_df[productions_df["active"]]
    prod_options = ["All"] + sorted(dept_prods["production_name"].dropna().unique().tolist())

    sel_pillar = st.selectbox("Strategic pillar (optional filter)", pillars, key="filter_pillar")
    sel_prod = st.selectbox("Production / area (optional filter)", prod_options, key="filter_production")

    # Filter questions for display
    filtered = questions_all_df.copy()
    if sel_pillar != "All":
        filtered = filtered[filtered["strategic_pillar"] == sel_pillar]
    if (
        sel_prod != "All"
        and "production" in filtered.columns
        and sel_prod in filtered["production"].unique()
    ):
        filtered = filtered[filtered["production"] == sel_prod]

    if filtered.empty:
        st.warning("No questions found for this combination. Try changing the filters.")
        return

    # -------------------------- Draft controls --------------------------
    st.sidebar.subheader("Drafts")

    # File uploader
    draft_file = st.sidebar.file_uploader(
        "Load saved draft (JSON)",
        type="json",
        help="Upload a JSON draft you previously downloaded.",
    )
    if draft_file is not None:
        applied, msg = apply_draft_bytes(draft_file.getvalue())
        if applied:
            st.sidebar.success(msg)
            safe_rerun()
        else:
            if "already applied" in msg:
                st.sidebar.info(msg)
            else:
                st.sidebar.error(msg)

    # Paste-from-clipboard loader
    with st.sidebar.expander("Paste draft JSON"):
        txt = st.text_area("Paste JSON here", height=120, key="paste_json")
        if st.button("Load pasted draft"):
            if txt.strip():
                applied, msg = apply_draft_bytes(txt.encode("utf-8"))
                if applied:
                    st.success(msg)
                    safe_rerun()
                else:
                    if "already applied" in msg:
                        st.info(msg)
                    else:
                        st.error(msg)

    # Force re-apply helper (useful in testing same file repeatedly)
    with st.sidebar.expander("Draft helpers"):
        if st.button("Force re-apply last draft"):
            st.session_state.pop("draft_hash", None)
            st.sidebar.success("You can now re-upload the same draft to apply it again.")

    # Clear form
    if st.sidebar.button("Clear current answers"):
        clear_form(questions_all_df)
        st.sidebar.success("Form cleared.")
        safe_rerun()

    # Show loaded meta quick view
    draft = st.session_state.get("loaded_draft")
    if draft:
        st.sidebar.markdown("**Loaded draft meta**")
        st.sidebar.json(draft.get("meta", {}))
        st.sidebar.write("Loaded answers:", len(draft.get("answers", {})))

    # --------------------------- Form section ---------------------------
    st.markdown("### Scorecard Questions")
    with st.form("scorecard_form"):
        responses = build_form_for_questions(filtered)
        submitted = st.form_submit_button("Generate AI Summary & PDF")

    # Meta (built from bound keys)
    meta = {
        "staff_name": st.session_state.get("staff_name") or "Unknown",
        "role": st.session_state.get("role") or "",
        "department": st.session_state.get("dept_label"),
        "month": month_str,
        "production": (st.session_state.get("filter_production") or ""),
        "filter_pillar": st.session_state.get("filter_pillar", "All"),
    }
    if meta["production"] == "All":
        meta["production"] = ""

    # Save progress (downloads ALL department questions)
    draft_dict = build_draft_from_state(questions_all_df, meta)
    st.sidebar.download_button(
        "💾 Save progress (download JSON)",
        data=json.dumps(draft_dict, indent=2),
        file_name=f"scorecard_draft_{meta['department'].replace(' ', '_')}_{month_str}.json",
        mime="application/json",
        help="Downloads a snapshot of your current answers. Re-upload later to continue.",
    )

    if not submitted:
        return

    # ------------------------ Validation & AI ---------------------------
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

    # AI call (with graceful error if key/SDK not configured)
    try:
        with st.spinner("Asking AI to interpret this scorecard..."):
            ai_result = interpret_scorecard(meta, filtered, responses)
    except RuntimeError as e:
        st.error(f"AI configuration error: {e}")
        st.info("Check your OPENAI_API_KEY secret and that `openai>=1.51.0` is in requirements.txt.")
        st.stop()
    except Exception as e:
        st.error(f"Failed to generate AI summary: {e}")
        st.stop()

    st.success("AI summary generated.")

    # --------------------------- Output UI -----------------------------
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
