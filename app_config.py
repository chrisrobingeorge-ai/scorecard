# app_config.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any

from pathlib import Path
import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# Base paths
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

# ─────────────────────────────────────────────────────────────────────────────
# Global labels / options
# ─────────────────────────────────────────────────────────────────────────────
GENERAL_PROD_LABEL = "General"
YES_NO_OPTIONS = ["Yes", "No"]  # global default

# ─────────────────────────────────────────────────────────────────────────────
# Strategic objectives index
# ─────────────────────────────────────────────────────────────────────────────
OBJECTIVES_INDEX_PATH = DATA_DIR / "strategic_objectives_index.csv"

try:
    OBJECTIVES_DF = pd.read_csv(OBJECTIVES_INDEX_PATH)
    OBJECTIVES_BY_ID: Dict[str, Dict[str, Any]] = (
        OBJECTIVES_DF
        .set_index("objective_id")
        .to_dict(orient="index")
    )
except FileNotFoundError:
    # Fallback: keep the app running even if the index is missing
    OBJECTIVES_DF = pd.DataFrame(
        columns=["objective_id", "owner", "objective_title", "short_description"]
    )
    OBJECTIVES_BY_ID: Dict[str, Dict[str, Any]] = {}

# ─────────────────────────────────────────────────────────────────────────────
# Financial KPI targets
# ─────────────────────────────────────────────────────────────────────────────
FINANCIAL_KPI_TARGETS_PATH = DATA_DIR / "financial_kpi_targets.csv"

try:
    FINANCIAL_KPI_TARGETS_DF = pd.read_csv(FINANCIAL_KPI_TARGETS_PATH)

    # Normalise column names just in case
    FINANCIAL_KPI_TARGETS_DF.columns = [
        c.strip().lower() for c in FINANCIAL_KPI_TARGETS_DF.columns
    ]

    # Ensure the expected columns exist
    expected_cols = {"area", "category", "sub_category", "target"}
    missing = expected_cols - set(FINANCIAL_KPI_TARGETS_DF.columns)
    if missing:
        raise ValueError(
            f"financial_kpi_targets.csv missing columns: {', '.join(sorted(missing))}"
        )

    # Optional: normalise dtypes
    FINANCIAL_KPI_TARGETS_DF["target"] = pd.to_numeric(
        FINANCIAL_KPI_TARGETS_DF["target"], errors="coerce"
    ).fillna(0)

    # If report_section not set yet, default to area (you can refine later in the CSV)
    if "report_section" not in FINANCIAL_KPI_TARGETS_DF.columns:
        FINANCIAL_KPI_TARGETS_DF["report_section"] = (
            FINANCIAL_KPI_TARGETS_DF["area"].astype(str)
        )
    else:
        FINANCIAL_KPI_TARGETS_DF["report_section"] = (
            FINANCIAL_KPI_TARGETS_DF["report_section"]
            .fillna(FINANCIAL_KPI_TARGETS_DF["area"])
            .astype(str)
        )

    # Default ordering if you haven’t filled report_order yet
    if "report_order" not in FINANCIAL_KPI_TARGETS_DF.columns:
        FINANCIAL_KPI_TARGETS_DF["report_order"] = (
            FINANCIAL_KPI_TARGETS_DF.groupby("report_section").cumcount() + 1
        )

except Exception as e:
    # Fallback so the app still runs
    FINANCIAL_KPI_TARGETS_DF = pd.DataFrame(
        columns=[
            "area",
            "category",
            "sub_category",
            "target",
            "report_section",
            "report_order",
        ]
    )
    print(f"Warning: could not load financial_kpi_targets.csv: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Department configuration
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class DepartmentConfig:
    questions_csv: str
    has_productions: bool = True
    productions_csv: Optional[str] = None
    scope_label: str = "Production / area"
    allow_general_option: bool = True   # whether "General" is allowed in the dropdown


DEPARTMENT_CONFIGS = {
    "Artistic": DepartmentConfig(
        questions_csv="data/artistic_scorecard_questions.csv",
        has_productions=True,
        productions_csv="data/productions.csv",
        scope_label="Production",
        allow_general_option=False,
    ),
    "School": DepartmentConfig(
        questions_csv="data/school_scorecard_questions.csv",
        has_productions=True,
        productions_csv="data/productions.csv",
        scope_label="Programme",
        allow_general_option=False,
    ),
    "Community": DepartmentConfig(
        questions_csv="data/community_scorecard_questions.csv",
        has_productions=True,
        productions_csv="data/productions.csv",
        scope_label="Programme",
        allow_general_option=False,  # Hide General for Community
    ),
    "Corporate": DepartmentConfig(
        questions_csv="data/corporate_scorecard_questions.csv",
        has_productions=True,
        productions_csv="data/productions.csv",
        scope_label="Programme",
        allow_general_option=False,
    ),
        "KPIs": DepartmentConfig(
        # This won't actually be used once we special-case it in app.py,
        # but we need *something* here so the normaliser is happy.
        questions_csv="data/corporate_scorecard_questions.csv",
        has_productions=False,
        productions_csv=None,
        scope_label="Area",
        allow_general_option=True,
    ),
}
