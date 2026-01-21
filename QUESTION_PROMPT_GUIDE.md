# Question Prompt Guide

This guide explains how to add, edit, and manage question prompts in the Scorecard app, and how they're used in conflict resolution.

## Where Question Prompts Come From

Question prompts are stored in CSV files in the [data/](data/) directory:

- **[data/community_scorecard_questions.csv](data/community_scorecard_questions.csv)** - Community department questions
- **[data/school_scorecard_questions.csv](data/school_scorecard_questions.csv)** - School department questions  
- **[data/artistic_scorecard_questions.csv](data/artistic_scorecard_questions.csv)** - Artistic department questions
- **[data/corporate_scorecard_questions.csv](data/corporate_scorecard_questions.csv)** - Corporate department questions

## CSV Structure

Each CSV has these key columns:

| Column | Purpose | Example |
|--------|---------|---------|
| `question_id` | Unique identifier | `COMM_REC_Q2a` |
| `question_text` | **Full prompt shown to users** | `"If yes, how many NEW recreational students registered this period (best estimate is fine)?"` |
| `section` | Display section name | `Recreational Classes` |
| `strategic_pillar` | Higher-level grouping | `Boost Enrollment & Engagement in AB Classes` |
| `department` | Department name | `Community` |
| `production` | Show/production name | `Recreational Classes` |
| `response_type` | Input type | `number`, `text`, `yes_no` |
| `required` | Whether required | `TRUE` or `FALSE` |

## How to Add a New Question

1. **Open the appropriate CSV file** for your department
   
2. **Add a new row** with these required fields:
   - `question_id`: Create a unique ID following the naming convention
     - Community: `COMM_<AREA>_Q<N>` (e.g., `COMM_REC_Q5`)
     - School: `SCH_<AREA>_Q<N>` (e.g., `SCH_CT_Q3`)
     - Artistic: `ATI<N>`, `ACSI<N>`, `CR<N>`, etc.
     - Corporate: `CORP_<AREA>_Q<N>` (e.g., `CORP_GP_Q2`)
   
   - `question_text`: **Write the EXACT sentence you want users to see**
     - This is displayed in:
       - The form when filling out the scorecard
       - Conflict resolution UI when merging files
       - AI summaries and reports
   
   - `section`: The section/category this question belongs to
   
   - `response_type`: One of:
     - `yes_no` - Yes/No radio buttons
     - `text` - Text area
     - `number` - Numeric input
     - `date` - Date picker

3. **Save the CSV file**

4. **No code changes needed!** The app automatically:
   - Loads the new question into the form
   - Uses the full text in conflict resolution
   - Includes it in exports and summaries

## How to Edit a Question Prompt

1. **Find the question** by searching for its `question_id` in the CSV
   
2. **Edit the `question_text` column** - this is the text shown everywhere

3. **Save the CSV file**

4. **Restart the Streamlit app** (if running) to pick up changes

⚠️ **Important**: Don't change the `question_id` unless you want to create a NEW question. Changing the ID will break existing data references.

## How Question Prompts Are Used

### 1. Form Rendering ([app.py](app.py))

When a user fills out a scorecard, questions are rendered from the CSV:

```python
for _, q_row in questions_df.iterrows():
    question_id = q_row["question_id"]
    question_text = q_row["question_text"]  # ← Displayed to user
    response_type = q_row["response_type"]
    
    if response_type == "text":
        st.text_area(question_text, key=question_id)
    elif response_type == "number":
        st.number_input(question_text, key=question_id)
    # etc...
```

### 2. Conflict Resolution ([merge_scorecards.py](merge_scorecards.py))

When merging multiple scorecards, the `QuestionRegistry` looks up the full text:

```python
registry = QuestionRegistry()
registry.load_from_csv_file("data/community_scorecard_questions.csv")

# Look up full text for a conflict
question_text = registry.get_question_text("COMM_REC_Q2a")
# Returns: "If yes, how many NEW recreational students registered this period..."
```

The conflict UI then displays:

```
📍 Recreational Classes
❓ If yes, how many NEW recreational students registered this period (best estimate is fine)?
🔧 Primary answer (debug: per_show_answers.Community::Recreational Classes.COMM_REC_Q2a › primary)

Select which value to keep:
○ user1.json: 100
○ user2.json: 150
```

### 3. AI Summaries ([ai_utils.py](ai_utils.py))

The AI uses question text to provide context in summaries:

```python
context = f"Question: {question_text}\nAnswer: {user_response}"
# AI can now understand what the answer refers to
```

## Question ID Naming Conventions

Follow these patterns for consistency:

### Community Department
- Access Programs: `COMM_ACCESS_Q<N>`
- Recreational Classes: `COMM_REC_Q<N>`
- Provincial Touring: `COMM_TOUR_Q<N>`

### School Department
- Classical Training: `SCH_CT_Q<N>`
- Attracting Students: `SCH_AS_Q<N>`
- Student Accessibility: `SCH_SA_Q<N>`

### Artistic Department
- Artistic & Technical Innovation: `ATI<N>`
- Social Impact: `ACSI<N>`
- Collaborations: `CR<N>`
- Auditions: `RA<N>`

### Corporate Department
- Global Presence: `CORP_GP_Q<N>`
- Marketing: `CORP_CM_Q<N>`, `CORP_SM_Q<N>`
- Leadership: `CORP_LS_Q<N>`
- Board: `CORP_BM_Q<N>`

Subquestions (follow-ups) use letters: `Q1a`, `Q1b`, `Q1c`, etc.

## Best Practices for Writing Question Text

✅ **DO:**
- Be specific and clear
- Include units or context: "...in dollars", "...this month", "...best estimate is fine"
- Use consistent tense (usually present or past)
- Match the tone used elsewhere in the app

❌ **DON'T:**
- Use shorthand or abbreviations without explanation
- Assume context that might not be clear later
- Make the question too long (aim for 1-2 sentences)
- Include formatting like bold/italic (use plain text)

## Examples

### Good Question Text
```
"If yes, how many NEW recreational students registered this period (best estimate is fine)?"
```
- ✓ Clear what's being asked
- ✓ Includes context ("NEW", "this period")
- ✓ Acknowledges estimates are okay

### Poor Question Text
```
"New students?"
```
- ✗ Too vague
- ✗ Missing context
- ✗ Unclear what period

## Testing Your Changes

After adding or editing questions:

1. **Run the test suite:**
   ```bash
   pytest tests/test_conflict_label_resolver.py -v
   ```

2. **Test in the app:**
   - Start the Streamlit app: `streamlit run app.py`
   - Navigate to your department
   - Fill out a test scorecard
   - Verify your question appears correctly
   - Try merging duplicate scorecards to test conflict resolution

3. **Verify exports:**
   - Export a PDF or DOCX
   - Confirm the question text appears correctly in the document

## Troubleshooting

### Question not appearing in the form
- Check CSV file saved properly
- Verify `question_id` is unique
- Ensure `required` is set to TRUE or FALSE (not blank)
- Restart Streamlit app

### Conflict shows "Q2A" instead of full text
- Verify CSV has `question_text` populated
- Check that registry is loading (see [app.py](app.py) line 1230)
- Ensure the CSV file path is correct in app config

### Question appears twice
- Check for duplicate `question_id` in CSV
- Each ID must be unique across all questions

## Related Files

- **[merge_scorecards.py](merge_scorecards.py)** - QuestionRegistry implementation
- **[app.py](app.py)** - Form rendering and conflict UI
- **[ai_utils.py](ai_utils.py)** - AI summary generation
- **[tests/test_conflict_label_resolver.py](tests/test_conflict_label_resolver.py)** - Test suite

## Need Help?

See [CONFLICT_LABEL_FIX.md](CONFLICT_LABEL_FIX.md) for technical details on how the conflict resolution system works.
