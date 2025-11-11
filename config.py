# config.py

from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

DEPARTMENT_FILES = {
    "Artistic": DATA_DIR / "artistic_scorecard_questions.csv",
    "School": DATA_DIR / "school_scorecard_questions.csv",
    "Community": DATA_DIR / "community_scorecard_questions.csv",
    "Corporate": DATA_DIR / "corporate_scorecard_questions.csv",
}

PRODUCTIONS_FILE = DATA_DIR / "productions.csv"

# Where your CSVs live
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

DEPARTMENT_FILES = {
    "Artistic & Production": DATA_DIR / "artistic_scorecard_questions.csv",
    "School": DATA_DIR / "school_scorecard_questions.csv",
    "Community": DATA_DIR / "community_scorecard_questions.csv",
    "Corporate": DATA_DIR / "corporate_scorecard_questions.csv",
}

# OpenAI model (change if you like)
MODEL_NAME = "gpt-4.1-mini"

# Yes/No options for UI
YES_NO_OPTIONS = ["Yes", "No"]
