from dataclasses import dataclass
from typing import Optional

GENERAL_PROD_LABEL = "General"
YES_NO_OPTIONS = ["Yes", "No"]  # global default

@dataclass
class DepartmentConfig:
    questions_csv: str
    has_productions: bool = True
    productions_csv: Optional[str] = None
    scope_label: str = "Production / area"
    allow_general_option: bool = True   # ← NEW

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
        allow_general_option=False,  # ✅ Hide General for Community
    ),
    "Corporate": DepartmentConfig(
        questions_csv="data/corporate_scorecard_questions.csv",
        has_productions=False,
        productions_csv=None,
        scope_label="Area",
        allow_general_option=True,
    ),
}
