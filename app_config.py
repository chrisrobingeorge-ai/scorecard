from dataclasses import dataclass

GENERAL_PROD_LABEL = "General"
YES_NO_OPTIONS = ["Yes", "No"]  # global default

@dataclass
class DeptConfig:
    questions_csv: str
    has_productions: bool
    productions_csv: str | None
    scope_label: str | None = "Production"  # cosmetic only

DEPARTMENT_CONFIGS = {
    "Artistic": DeptConfig(
        questions_csv="data/artistic_scorecard_questions.csv",
        has_productions=True,
        productions_csv="data/productions.csv",
        scope_label="Production",
    ),
    "School": DeptConfig(
        questions_csv="data/school_scorecard_questions.csv",
        has_productions=False,              # School has no productions/programmes
        productions_csv=None,
        scope_label="Programme",
    ),
    "Community": DeptConfig(
        questions_csv="data/community_scorecard_questions.csv",
        has_productions=True,
        productions_csv="data/productions.csv",
        scope_label="Programme",
    ),
    "Corporate": DeptConfig(
        questions_csv="data/corporate_scorecard_questions.csv",
        has_productions=False,
        productions_csv=None,
        scope_label="Area",
    ),
}
