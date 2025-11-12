# app_config.py
from dataclasses import dataclass
from typing import Optional, Dict

# Single source of truth for the "general" scope label
GENERAL_PROD_LABEL: str = "General"

YES_NO_OPTIONS = ["Yes", "No"]


@dataclass
class DepartmentConfig:
    key: str
    label: str
    questions_csv: str
    has_productions: bool = True
    productions_csv: Optional[str] = None
    scope_label: str = "Production / area"  # Label for second dropdown


# ─────────────────────────────────────────────────────────────────────────────
# Configure your four departments here. Point to your CSV paths.
# - questions_* CSVs must include: question_id, (optional) strategic_pillar,
#   production, question_text, response_type, options, required, display_order, depends_on
# - productions_* CSVs must include: department, production_name, (optional) active
# ─────────────────────────────────────────────────────────────────────────────
DEPARTMENT_CONFIGS: Dict[str, DepartmentConfig] = {
    "Artistic": DepartmentConfig(
        key="Artistic",
        label="Artistic",
        questions_csv="data/questions_artistic.csv",
        has_productions=True,
        productions_csv="data/productions_artistic.csv",  # or shared file
        scope_label="Production",
    ),
    "School": DepartmentConfig(
        key="School",
        label="School",
        questions_csv="data/questions_school.csv",
        has_productions=True,
        productions_csv="data/productions_school.csv",    # programmes/levels
        scope_label="Programme / Level",
    ),
    "Community": DepartmentConfig(
        key="Community",
        label="Community",
        questions_csv="data/questions_community.csv",
        has_productions=False,
        productions_csv=None,
        scope_label="Area",
    ),
    "Corporate": DepartmentConfig(
        key="Corporate",
        label="Corporate",
        questions_csv="data/questions_corporate.csv",
        has_productions=False,
        productions_csv=None,
        scope_label="Area",
    ),
}
