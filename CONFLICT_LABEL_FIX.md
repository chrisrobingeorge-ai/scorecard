# Conflict Label Resolution Fix

## Summary

Fixed the conflict UI to display **full human-readable question text** instead of shorthand codes like "Comm Rec Q2A".

## Problem

When merge conflicts were detected in `per_show_answers` paths, the UI showed:
- ✅ Section header: "Recreational Classes" (production name from path)
- ❌ Question label: "Comm Rec Q2A" (humanized question ID - not helpful)
- ✅ Debug path: "per_show_answers.Community::Recreational Classes.COMM_REC_Q2a › primary"

Users couldn't understand what the conflict was about without referencing documentation.

## Solution

Updated `resolve_conflict_label()` in [merge_scorecards.py](merge_scorecards.py) to:

1. **Always use full question text from registry** when available
   - Looks up question_id in CSV to get the `question_text` column
   - Example: "If yes, how many NEW recreational students registered this period (best estimate is fine)?"

2. **Prefer production/show name from path** for `per_show_answers` conflicts
   - Extracts "Recreational Classes" from `per_show_answers.Community::Recreational Classes.COMM_REC_Q2a`
   - More specific and relevant than the CSV's strategic_pillar ("Boost Enrollment & Engagement in AB Classes")

3. **Graceful fallback** when registry is unavailable
   - Still extracts show name from path
   - Falls back to humanized question ID for the question label

## Changes Made

### [merge_scorecards.py](merge_scorecards.py)

- **Lines 274-284**: Extract `show_name_from_path` for per_show_answers conflicts
- **Lines 286-300**: Prefer show name for section_label when available
- **Lines 302-310**: Apply same logic for cases without registry

### [tests/test_conflict_label_resolver.py](tests/test_conflict_label_resolver.py)

- **test_per_show_answers_with_registry**: Verifies full question text is used with registry
- **test_per_show_answers_without_registry**: Verifies graceful fallback without registry
- **test_per_show_conflict**: Updated to expect show name from path

## How It Works

### Question Text Source

Questions are defined in CSV files with this structure:

```csv
question_id,question_text,section,strategic_pillar,department,production
COMM_REC_Q2a,"If yes, how many NEW recreational students registered this period (best estimate is fine)?",Recreational Classes,Boost Enrollment & Engagement in AB Classes,Community,Recreational Classes
```

The `QuestionRegistry` class loads these CSVs and provides:
- `get_question_text(question_id)` → Returns the `question_text` column
- `get_section_label(question_id)` → Returns section/strategic_pillar/department hierarchy

### Path Parsing for per_show_answers

Conflict paths have the format:
```
per_show_answers.<Department>::<Production>.<QUESTION_ID>
```

Example:
```
per_show_answers.Community::Recreational Classes.COMM_REC_Q2a
```

The resolver extracts:
- Department: "Community"
- Production: "Recreational Classes" ← Used as section_label
- Question ID: "COMM_REC_Q2a" ← Used to lookup full text

### Registry Building in app.py

The registry is built in [app.py](app.py):

```python
def _build_question_registry(all_questions_df):
    registry = QuestionRegistry()
    if all_questions_df is not None and not all_questions_df.empty:
        registry.load_from_dataframe(all_questions_df)
    return registry
```

And passed to conflict resolution:
```python
resolutions = _render_conflict_resolution_ui(conflicts, questions_all_df)
```

## Adding/Editing Questions

To add or modify question text:

1. **Locate the appropriate CSV file** in [data/](data/):
   - `community_scorecard_questions.csv`
   - `school_scorecard_questions.csv`
   - `artistic_scorecard_questions.csv`
   - `corporate_scorecard_questions.csv`

2. **Edit the `question_text` column** for the question ID
   - This is the text shown to users in forms
   - This is now also shown in conflict resolution

3. **No code changes needed** - the registry automatically loads the updated text

## Testing

Run the comprehensive test suite:

```bash
pytest tests/test_conflict_label_resolver.py -v
```

All 34 tests pass, including:
- Registry loading from CSV
- Question text lookup
- Path parsing for per_show_answers
- Graceful fallback when registry is missing
- Integration tests with real CSV data

## Example Output

### Before Fix
```
❌ Recreational Classes
   Comm Rec Q2A
   Primary answer (debug: per_show_answers.Community::Recreational Classes.COMM_REC_Q2a › primary)
```

### After Fix
```
✅ Recreational Classes
   If yes, how many NEW recreational students registered this period (best estimate is fine)?
   Primary answer (debug: per_show_answers.Community::Recreational Classes.COMM_REC_Q2a › primary)
```

## Edge Cases Handled

1. **Registry is None or empty**: Falls back to humanized question ID
2. **Question not in registry**: Falls back to humanized question ID
3. **No show name in path**: Uses registry section or derived section
4. **Non-per_show_answers paths**: Uses registry section as before
5. **Invalid CSV format**: Gracefully caught by try/except in `load_from_dataframe()`

## Future Enhancements

Consider adding:
- Tooltip showing the strategic pillar on hover
- Color coding by question type (yes/no, number, text)
- Quick preview of both conflicting answers inline
