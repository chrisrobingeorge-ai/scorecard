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
        allow_general_option=True,
    ),
    "School": DepartmentConfig(
        questions_csv="data/school_scorecard_questions.csv",
        has_productions=False,              # School has no productions/programmes
        productions_csv=None,
        scope_label="Programme",
        allow_general_option=True,
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
        has_productions=False,
        productions_csv=None,
        scope_label="Area",
        allow_general_option=True,
    ),
}
