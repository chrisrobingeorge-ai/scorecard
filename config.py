# config.py
from dataclasses import dataclass

@dataclass
class DepartmentConfig:
    key: str
    label: str
    questions_csv: str
    has_productions: bool = True
    productions_csv: str | None = "data/productions.csv"
    scope_label: str = "Production / area"  # label for the second dropdown


DEPARTMENT_CONFIGS: dict[str, DepartmentConfig] = {
    "Artistic": DepartmentConfig(
        key="Artistic",
        label="Artistic",
        questions_csv="data/questions_artistic.csv",
        has_productions=True,
        productions_csv="data/productions_artistic.csv",  # or shared
        scope_label="Production",
    ),
    "School": DepartmentConfig(
        key="School",
        label="School",
        questions_csv="data/questions_school.csv",
        has_productions=True,     # maybe "Programme / level"
        productions_csv="data/questions_school_programmes.csv",
        scope_label="Programme / level",
    ),
    "Community": DepartmentConfig(
        key="Community",
        label="Community",
        questions_csv="data/questions_community.csv",
        has_productions=False,    # just General or maybe Region later
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

# For backwards-compat if you still want a simple mapping:
DEPARTMENT_FILES = {k: v.questions_csv for k, v in DEPARTMENT_CONFIGS.items()}

YES_NO_OPTIONS = ["Yes", "No"]
