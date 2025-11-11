# app.py

import json
import streamlit as st
import pandas as pd
from datetime import date

from config import DEPARTMENT_FILES, YES_NO_OPTIONS
from ai_utils import interpret_scorecard
from pdf_utils import build_scorecard_pdf


st.set_page_config(page_title="Monthly Scorecard", layout="wide")
st.title("Monthly Scorecard with AI Summary")

@st.cache_data
def load_questions(file_path) -> pd.DataFrame:
    df = pd.read_csv(file_path)

    if "required" in df.columns:
        df["required"] = df["required"].astype(str).str.upper().eq("TRUE")
    if "display_order" in df.columns:
        df["display_order"] = pd.to_numeric(df["display_order"], errors="coerce").fillna(0)

    if "section" not in df.columns:
        df["section"] = df.get("strategic_pillar", "General")

    df["section"] = df["section"].fillna("General")
    df["strategic_pillar"] = df.get("strategic_pillar", "").fillna("")
    df["production"] = df.get("production", "").fillna("")
    df["metric"] = df.get("metric", "").fillna("")
    df["question_text"] = df.get("question_text", "").fillna("")
    return df


@st.cache_data
def load_productions() -> pd.DataFrame:
    df = pd.read_csv("data/productions.csv")

    df["department"] = df["department"].fillna("")
    df["production_name"] = df["production_name"].fillna("")
    if "active" in df.columns:
        df["active"] = df["active"].astype(str).str.upper().eq("TRUE")
    else:
        df["active"] = True

    return df

def build_form_for_questions(df: pd.DataFrame):
    """
    Render widgets for each question, grouped by pillar + production,
    with a main answer plus a description field.
    """
    responses = {}

    df = df.copy()
    df["strategic_pillar"] = df["strategic_pillar"].fillna("General")
    df["production"] = df["production"].fillna("All works")
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

            if production and str(production).strip().lower() not in ("school-wide", "corporate-wide", "all works"):
                st.markdown(f"**{production}**")

            cols = st.columns(2)

            for idx, (_, row) in enumerate(prod_block.iterrows()):
                col = cols[idx % 2]
                with col:
                    qid = row["question_id"]

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
                        options = [o.strip() for o in opts_raw.split(",") if o.strip()]

                    # We'll collect a small dict per metric
                    entry = {
                        "primary": None,       # main answer (Y/N, number, scale…)
                        "description": None,   # free-text context
                    }

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
                        # Fallback: free-text as the primary answer
                        entry["primary"] = st.text_area(
                            label_display, key=qid, height=60
                        )
                    # ---------------------------------

                    # ---- description / context ----
                    # Show for everything except when the primary is *already* a big text box.
                    show_desc = rtype in ("yes_no", "scale_1_5", "number", "select")
                    if show_desc:
                        metric = str(row.get("metric", "") or "").strip()
                        desc_label = metric + " – description / notes" if metric else "Description / notes"
                        desc_label = str(desc_label)
                        entry["description"] = st.text_area(
                            desc_label, key=f"{qid}_desc", height=60
                        )
                    # --------------------------------

                    responses[qid] = entry

    return responses

def build_draft_from_state(questions_df: pd.DataFrame, meta: dict) -> dict:
    """
    Walk all questions and pull current widget values from st.session_state.
    This lets the user save a partial form as a JSON draft.
    """
    draft = {
        "meta": meta,
        "answers": {},
    }

    for _, row in questions_df.iterrows():
        qid = row["question_id"]
        primary = st.session_state.get(qid, None)
        desc = st.session_state.get(f"{qid}_desc", None)

        if primary is not None or (desc not in (None, "")):
            draft["answers"][qid] = {
                "primary": primary,
                "description": desc,
            }

    return draft

def apply_draft_to_state(draft: dict):
    """
    Take a draft dict and push values into st.session_state so that
    widgets (keyed by question_id and question_id_desc) are prefilled.
    """
    answers = draft.get("answers", {})
    for qid, entry in answers.items():
        if "primary" in entry:
            st.session_state[qid] = entry["primary"]
        if "description" in entry:
            st.session_state[f"{qid}_desc"] = entry["description"]

def main():
    # Basic identity + month
    staff_name = st.text_input("Your name")
    role = st.text_input("Your role / department title")

    # Month selection (we treat it as YYYY-MM string)
    month_date = st.date_input("Reporting month", value=date.today())
    month_str = month_date.strftime("%Y-%m")

    # Department selection
    dept_label = st.selectbox("Which area are you reporting on?", list(DEPARTMENT_FILES.keys()))
    questions_df = load_questions(DEPARTMENT_FILES[dept_label])

    # Optional filters for pillar / production
    st.subheader("Scope of this report")

    # Pillar filter (from questions CSV)
    pillars = ["All"] + sorted(
        questions_df["strategic_pillar"].dropna().unique().tolist()
    )
    sel_pillar = st.selectbox("Strategic pillar (optional filter)", pillars)

    # Production filter (from productions.csv)
    productions_df = load_productions()

    # normalise department strings for matching
    dept_series = productions_df["department"].astype(str).str.strip().str.lower()
    current_dept = (dept_label or "").strip().lower()

    dept_prods = productions_df[
        (dept_series == current_dept) & (productions_df["active"])
    ]

    # Fallback: if nothing matched this department, just use all active productions
    if dept_prods.empty:
        dept_prods = productions_df[productions_df["active"]]

    prod_options = ["All"] + sorted(
        dept_prods["production_name"].dropna().unique().tolist()
    )

    sel_prod = st.selectbox(
        "Production / area (optional filter)",
        prod_options,
    )

    # Apply filters to the questions
    filtered = questions_df.copy()
    if sel_pillar != "All":
        filtered = filtered[filtered["strategic_pillar"] == sel_pillar]

    # Only filter by production if the questions CSV actually uses those names
    if (
        sel_prod != "All"
        and "production" in filtered.columns
        and sel_prod in filtered["production"].unique()
    ):
        filtered = filtered[filtered["production"] == sel_prod]

    if filtered.empty:
        st.warning("No questions found for this combination. Try changing the filters.")
        return

    st.markdown("### Scorecard Questions")

    # -------- DRAFT CONTROLS (SIDEBAR) --------
    st.sidebar.subheader("Drafts")

    draft_file = st.sidebar.file_uploader(
        "Load saved draft",
        type="json",
        help="Upload a JSON draft you previously saved."
    )
    if draft_file is not None:
        try:
            draft_data = json.loads(draft_file.read().decode("utf-8"))
            apply_draft_to_state(draft_data)
            st.sidebar.success("Draft loaded. Your answers have been restored.")
        except Exception as e:
            st.sidebar.error(f"Could not load draft: {e}")
    # ------------------------------------------
    with st.form("scorecard_form"):
        responses = build_form_for_questions(filtered)
        submitted = st.form_submit_button("Generate AI Summary & PDF")

    # Build meta now (we’ll use it for drafts + AI)
    meta = {
        "staff_name": staff_name or "Unknown",
        "role": role or "",
        "department": dept_label,
        "month": month_str,
        "production": sel_prod if sel_prod != "All" else "",
    }

    # ---- Save progress (download draft) ----
    # Use the *filtered* questions for the current scope
    draft_dict = build_draft_from_state(filtered, meta)
    st.sidebar.download_button(
        "💾 Save progress",
        data=json.dumps(draft_dict, indent=2),
        file_name="scorecard_draft.json",
        mime="application/json",
        help="Download a snapshot of your current answers so you can finish later.",
    )
    # ----------------------------------------

    # If they haven't clicked submit, stop here (but the Save button is visible)
    if not submitted:
        return

    # Basic validation (same as before)
    missing_required = []
    for _, row in filtered.iterrows():
        if bool(row.get("required", False)):
            qid = row["question_id"]
            val = responses.get(qid, None)

            primary_val = None
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
            st.markdown(f"**{ps.get('strategic_pillar', 'Pillar')} — {ps.get('score_hint', '')}**")
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
