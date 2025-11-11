# app.py

import json
from datetime import date

import pandas as pd
import streamlit as st

from config import DEPARTMENT_FILES, YES_NO_OPTIONS
from ai_utils import interpret_scorecard
from pdf_utils import build_scorecard_pdf


st.set_page_config(page_title="Monthly Scorecard", layout="wide")
st.title("Monthly Scorecard with AI Summary")

def safe_rerun():
    """Call st.rerun() if available, else fall back to st.experimental_rerun()."""
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

# -----------------------------
# Data loading helpers
# -----------------------------
@st.cache_data
def load_questions(file_path) -> pd.DataFrame:
    df = pd.read_csv(file_path)

    # NORMALISE IDs TO STRINGS (important for drafts)
    if "question_id" in df.columns:
        df["question_id"] = df["question_id"].astype(str).str.strip()
    else:
        raise ValueError("questions CSV must contain a 'question_id' column")

    if "required" in df.columns:
        df["required"] = df["required"].astype(str).str.upper().eq("TRUE")
    if "display_order" in df.columns:
        df["display_order"] = pd.to_numeric(
            df["display_order"], errors="coerce"
        ).fillna(0)

    if "section" not in df.columns:
        df["section"] = df.get("strategic_pillar", "General")

    df["section"] = df["section"].fillna("General")
    df["strategic_pillar"] = df.get("strategic_pillar", "").fillna("")
    df["production"] = df.get("production", "").fillna("")
    df["metric"] = df.get("metric", "").fillna("")
    df["question_text"] = df.get("question_text", "").fillna("")
    df["response_type"] = df.get("response_type", "").fillna("text")
    df["options"] = df.get("options", "").fillna("")
    return df


@st.cache_data
def load_productions() -> pd.DataFrame:
    """
    Load list of productions from data/productions.csv
    Expected columns: department, production_name, active (TRUE/FALSE)
    """
    df = pd.read_csv("data/productions.csv")

    df["department"] = df["department"].fillna("")
    df["production_name"] = df["production_name"].fillna("")
    if "active" in df.columns:
        df["active"] = df["active"].astype(str).str.upper().eq("TRUE")
    else:
        df["active"] = True

    return df


# -----------------------------
# Form building
# -----------------------------
def build_form_for_questions(df: pd.DataFrame) -> dict:
    """
    Render widgets for each question, grouped by pillar + production,
    with a main answer plus a description field.

    NOTE: We don't pass initial values in here; we rely on st.session_state
    being populated (either by the user or by a loaded draft).
    """
    responses: dict = {}

    df = df.copy()
    df["strategic_pillar"] = df["strategic_pillar"].fillna("General")
    df["production"] = df["production"].fillna("All works")
    df["metric"] = df["metric"].fillna("")
    df["display_order"] = pd.to_numeric(
        df.get("display_order", 0), errors="coerce"
    ).fillna(0)

    pillars = df["strategic_pillar"].unique()

    for pillar in pillars:
        pillar_block = df[df["strategic_pillar"] == pillar].sort_values(
            ["production", "display_order"]
        )

        st.markdown(f"### {pillar}")

        for production in pillar_block["production"].unique():
            prod_block = pillar_block[pillar_block["production"] == production]

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
                    qid = row["question_id"]  # ALWAYS STRING NOW

                    # ----- Label (no 'nan') -----
                    raw_label = row.get("question_text", "")
                    try:
                        is_na = pd.isna(raw_label)
                    except TypeError:
                        is_na = False

                    if is_na or str(raw_label).strip() == "":
                        metric = str(row.get("metric", "") or "").strip()
                        fallback = metric or qid
                        label = fallback
                    else:
                        label = str(raw_label).strip()

                    required = bool(row.get("required", False))
                    label_display = f"{label} *" if required else label
                    label_display = str(label_display)
                    # ----------------------------

                    rtype = str(row.get("response_type", "")).strip().lower()
                    opts_raw = row.get("options", "")
                    options = []
                    if isinstance(opts_raw, str) and opts_raw.strip():
                        options = [
                            o.strip() for o in opts_raw.split(",") if o.strip()
                        ]

                    entry = {"primary": None, "description": None}

                    # ---- primary control by type ----
                    if rtype == "yes_no":
                        entry["primary"] = st.radio(
                            label_display,
                            YES_NO_OPTIONS,
                            horizontal=True,
                            key=qid,
                        )

                    elif rtype == "scale_1_5":
                        entry["primary"] = int(
                            st.slider(label_display, 1, 5, 3, key=qid)
                        )

                    elif rtype == "number":
                        entry["primary"] = st.number_input(
                            label_display, value=0.0, step=1.0, key=qid
                        )

                    elif rtype == "select" and options:
                        entry["primary"] = st.selectbox(
                            label_display, options, key=qid
                        )

                    else:
                        entry["primary"] = st.text_area(
                            label_display, key=qid, height=60
                        )
                    # ---------------------------------

                    # ---- description / context ----
                    show_desc = rtype in (
                        "yes_no",
                        "scale_1_5",
                        "number",
                        "select",
                    )
                    if show_desc:
                        metric = str(row.get("metric", "") or "").strip()
                        desc_label = (
                            metric + " – description / notes"
                            if metric
                            else "Description / notes"
                        )
                        entry["description"] = st.text_area(
                            str(desc_label),
                            key=f"{qid}_desc",
                            height=60,
                        )
                    # --------------------------------

                    responses[qid] = entry

    return responses


# -----------------------------
# Draft helpers
# -----------------------------
def build_draft_from_state(questions_df: pd.DataFrame, meta: dict) -> dict:
    """
    Walk all questions and pull current widget values from st.session_state.
    This lets the user save a partial form as a JSON draft.
    """
    draft = {"meta": meta, "answers": {}}

    for _, row in questions_df.iterrows():
        qid = row["question_id"]  # STRING
        primary = st.session_state.get(qid, None)
        desc = st.session_state.get(f"{qid}_desc", None)

        if primary is not None or (desc not in (None, "")):
            draft["answers"][qid] = {
                "primary": primary,
                "description": desc,
            }

    return draft


# -----------------------------
# Main app
# -----------------------------
def main():
    # Init flags
    if "draft_applied" not in st.session_state:
        st.session_state["draft_applied"] = False

    # Basic identity + month
    staff_name = st.text_input("Your name")
    role = st.text_input("Your role / department title")

    month_date = st.date_input("Reporting month", value=date.today())
    month_str = month_date.strftime("%Y-%m")

    # Department selection
    dept_label = st.selectbox(
        "Which area are you reporting on?", list(DEPARTMENT_FILES.keys())
    )
    questions_df = load_questions(DEPARTMENT_FILES[dept_label])

    # Scope filters
    st.subheader("Scope of this report")

    pillars = ["All"] + sorted(
        questions_df["strategic_pillar"].dropna().unique().tolist()
    )
    sel_pillar = st.selectbox("Strategic pillar (optional filter)", pillars)

    productions_df = load_productions()

    dept_series = productions_df["department"].astype(str).str.strip().str.lower()
    current_dept = (dept_label or "").strip().lower()

    dept_prods = productions_df[
        (dept_series == current_dept) & (productions_df["active"])
    ]
    if dept_prods.empty:
        dept_prods = productions_df[productions_df["active"]]

    prod_options = ["All"] + sorted(
        dept_prods["production_name"].dropna().unique().tolist()
    )

    sel_prod = st.selectbox("Production / area (optional filter)", prod_options)

    # Filter questions
    filtered = questions_df.copy()
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

    # -------- DRAFT CONTROLS (SIDEBAR) --------
    st.sidebar.subheader("Drafts")

    draft_file = st.sidebar.file_uploader(
        "Load saved draft",
        type="json",
        help="Upload a JSON draft you previously saved.",
    )

    if draft_file is not None and not st.session_state.get("draft_applied", False):
        try:
            draft_data = json.loads(draft_file.getvalue().decode("utf-8"))
            st.session_state["loaded_draft"] = draft_data

            # Apply draft into session_state EXACTLY ONCE, then rerun
            answers = draft_data.get("answers", {}) or {}
            for qid_str, entry in answers.items():
                # qid_str is already a string
                st.session_state[qid_str] = entry.get("primary", None)
                st.session_state[f"{qid_str}_desc"] = entry.get(
                    "description", None
                )

            st.session_state["draft_applied"] = True
            st.sidebar.success("Draft loaded and applied to the form.")
            safe_rerun()

        except Exception as e:
            st.sidebar.error(f"Could not load draft: {e}")

    # DEBUG: show loaded meta (optional, can remove later)
    draft = st.session_state.get("loaded_draft")
    if draft:
        st.sidebar.markdown("**Loaded draft meta**")
        st.sidebar.json(draft.get("meta", {}))
        st.sidebar.write("Loaded answers:", len(draft.get("answers", {})))
    # ------------------------------------------

    st.markdown("### Scorecard Questions")

    # Build the form widgets. Their initial values now come from st.session_state
    # if a draft was applied in a previous rerun.
    with st.form("scorecard_form"):
        responses = build_form_for_questions(filtered)
        submitted = st.form_submit_button("Generate AI Summary & PDF")

    # Meta used for drafts + AI
    meta = {
        "staff_name": staff_name or "Unknown",
        "role": role or "",
        "department": dept_label,
        "month": month_str,
        "production": sel_prod if sel_prod != "All" else "",
    }

    # Save progress (draft download) – always available
    draft_dict = build_draft_from_state(filtered, meta)
    st.sidebar.download_button(
        "💾 Save progress",
        data=json.dumps(draft_dict, indent=2),
        file_name="scorecard_draft.json",
        mime="application/json",
        help="Download a snapshot of your current answers so you can finish later.",
    )

    if not submitted:
        return

    # Basic validation
    missing_required = []
    for _, row in filtered.iterrows():
        if bool(row.get("required", False)):
            qid = row["question_id"]
            val = responses.get(qid, None)

            if isinstance(val, dict):
                primary_val = val.get("primary", None)
            else:
                primary_val = val

            if primary_val in (None, "", []):
                missing_required.append(row["question_text"])

    if missing_required:
        st.error("Please answer all required questions before generating the summary.")
        with st.expander("Missing required questions"):
            for q in missing_required:
                st.write("• ", q)
        return

    # AI call
    with st.spinner("Asking AI to interpret this scorecard..."):
        ai_result = interpret_scorecard(meta, filtered, responses)

    st.success("AI summary generated.")

    # Display AI result
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

    # Build PDF
    pdf_bytes = build_scorecard_pdf(meta, filtered, responses, ai_result)

    st.download_button(
        label="Download PDF report",
        data=pdf_bytes,
        file_name=f"scorecard_{dept_label.replace(' ', '_')}_{month_str}.pdf",
        mime="application/pdf",
    )


if __name__ == "__main__":
    main()
