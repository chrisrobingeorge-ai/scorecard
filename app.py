# app.py

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
    # Normalise some types
    if "required" in df.columns:
        df["required"] = df["required"].astype(str).str.upper().eq("TRUE")
    if "display_order" in df.columns:
        df["display_order"] = pd.to_numeric(df["display_order"], errors="coerce").fillna(0)
    return df


def build_form_for_questions(df: pd.DataFrame):
    """
    Render Streamlit widgets for each question and collect responses.
    """
    responses = {}

    for _, row in df.sort_values("display_order").iterrows():
        qid = row["question_id"]
        label = row["question_text"]
        rtype = str(row.get("response_type", "")).strip()
        opts_raw = row.get("options", "")
        options = []
        if isinstance(opts_raw, str) and opts_raw.strip():
            options = [o.strip() for o in opts_raw.split(",") if o.strip()]

        if rtype == "yes_no":
            responses[qid] = st.selectbox(label, YES_NO_OPTIONS, key=qid)
        elif rtype == "scale_1_5":
            responses[qid] = int(st.slider(label, 1, 5, 3, key=qid))
        elif rtype == "number":
            responses[qid] = float(st.number_input(label, value=0.0, step=1.0, key=qid))
        elif rtype == "select" and options:
            responses[qid] = st.selectbox(label, options, key=qid)
        else:
            responses[qid] = st.text_area(label, key=qid, height=70)

    return responses


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

    pillars = ["All"] + sorted(questions_df["strategic_pillar"].dropna().unique().tolist())
    productions = ["All"] + sorted(questions_df["production"].dropna().unique().tolist())

    sel_pillar = st.selectbox("Strategic pillar (optional filter)", pillars)
    sel_prod = st.selectbox("Production / area (optional filter)", productions)

    filtered = questions_df.copy()
    if sel_pillar != "All":
        filtered = filtered[filtered["strategic_pillar"] == sel_pillar]
    if sel_prod != "All":
        filtered = filtered[filtered["production"] == sel_prod]

    if filtered.empty:
        st.warning("No questions found for this combination. Try changing the filters.")
        return

    st.markdown("### Scorecard Questions")

    with st.form("scorecard_form"):
        responses = build_form_for_questions(filtered)
        submitted = st.form_submit_button("Generate AI Summary & PDF")

    if not submitted:
        return

    # Basic validation
    missing_required = []
    for _, row in filtered.iterrows():
        if bool(row.get("required", False)):
            qid = row["question_id"]
            val = responses.get(qid, None)
            if val in (None, "", []):
                missing_required.append(row["question_text"])

    if missing_required:
        st.error(
            "Please answer all required questions before generating the summary."
        )
        with st.expander("Missing required questions"):
            for q in missing_required:
                st.write("• ", q)
        return

    meta = {
        "staff_name": staff_name or "Unknown",
        "role": role or "",
        "department": dept_label,
        "month": month_str,
    }

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
