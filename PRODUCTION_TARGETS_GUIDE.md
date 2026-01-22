# Production Targets Feature Guide

## Overview

The scorecard app now displays **production-specific targets** when users select a production, providing context before they answer financial and performance questions.

---

## How It Works

### 1. User Selects a Production

When a user selects **"Nijinsky"** from the production dropdown, they will immediately see:

```
ℹ️ Nijinsky — Performance Targets:
- Budget: $400,000
- Target Seats: 5,000
- Target Revenue: $450,000
- Target Avg Ticket Price: $90.00

Holiday season flagship production
```

This context appears **before the scorecard questions**, so users can reference these targets while answering.

### 2. Users Answer Questions with Context

When they reach financial questions like:
- **FM01:** "What was the ticket revenue performance for this production versus budget (variance %)?"
- **FM02:** "What was the seats sold performance for this production versus target (variance %)?"
- **FM03:** "What was the average ticket price realised for this production ($)?"

They already know the targets and can calculate variances accurately.

### 3. AI Uses Targets for Smarter Summaries

The AI receives the production targets and can generate summaries like:

> "Nijinsky exceeded its $400,000 budget target by 8%, generating $432,000 in revenue. Seat sales reached 5,200 (104% of target), with an average ticket price of $92, slightly above the $90 target."

---

## Managing Production Targets

### File Location
`data/production_targets.csv`

### CSV Structure

```csv
production_name,department,budget,target_seats,target_revenue,target_ticket_price,notes
Nijinsky,Artistic,400000,5000,450000,90,Holiday season flagship production
Once Upon a Time,Artistic,250000,3200,280000,87.50,Family programming
Nutcracker,Artistic,600000,8000,720000,90,Annual tradition - largest production
```

### Column Definitions

| Column | Type | Description | Required |
|--------|------|-------------|----------|
| `production_name` | text | Exact name matching dropdown (case-insensitive) | Yes |
| `department` | text | Department name (Artistic, School, Community, Corporate) | Yes |
| `budget` | number | Production budget in dollars | Optional |
| `target_seats` | number | Target number of seats to fill | Optional |
| `target_revenue` | number | Target revenue in dollars | Optional |
| `target_ticket_price` | number | Target average ticket price | Optional |
| `notes` | text | Additional context (displayed in italics) | Optional |

### Adding New Productions

1. Open `data/production_targets.csv`
2. Add a new row with the production details
3. Save the file
4. Targets will display immediately (cached for performance)

Example:
```csv
Romeo and Juliet,Artistic,350000,4200,378000,90,Classic repertoire
```

---

## When Targets Are Shown

✅ **Shown:**
- When a **specific production** is selected (not "General")
- For departments with `has_productions=True` (currently: Artistic)
- Only if matching targets exist in the CSV

❌ **Not Shown:**
- When "General" scope is selected
- For departments without productions
- If no matching target exists for that production

---

## Example User Experience

### Step 1: User Flow
1. User selects **Department: Artistic**
2. User selects **Production: Nutcracker**
3. **Info box appears:**

```
ℹ️ Nutcracker — Performance Targets:
- Budget: $600,000
- Target Seats: 8,000
- Target Revenue: $720,000
- Target Avg Ticket Price: $90.00

Annual tradition - largest production
```

4. User scrolls down to **Financials & Marketing** tab
5. Sees questions:
   - FM01: What was the ticket revenue performance versus budget (variance %)?
   - FM02: What was the seats sold performance versus target (variance %)?
   - FM03: What was the average ticket price realised ($)?
6. User enters actual values, already knowing the targets

### Step 2: AI Summary
After clicking "Generate AI Summary & PDF", the AI creates contextual analysis:

> **Nutcracker Financial Performance:**
> 
> The Nutcracker achieved exceptional results against its targets. Revenue reached $756,000, exceeding the $720,000 target by 5%. With 8,400 seats sold (105% of the 8,000 target) and an average ticket price of $90, this production demonstrated strong demand for our annual holiday tradition.

---

## Extending to Other Departments

The system is designed to support targets for:

### School Department
Potential columns:
- `program_name` (e.g., "Summer Intensive")
- `target_enrollment`
- `scholarship_budget`
- `revenue_target`

### Community Department
Potential columns:
- `program_name` (e.g., "Access Dance - Calgary")
- `target_participants`
- `funding_target`
- `partner_organizations`

### Corporate Department
Potential columns:
- `initiative_name` (e.g., "Q1 Marketing Campaign")
- `budget`
- `target_leads`
- `target_conversions`

To add these:
1. Create corresponding CSV files (e.g., `data/school_program_targets.csv`)
2. Update the display logic in app.py to check other departments
3. Modify column names as appropriate

---

## Benefits

✅ **For Users:**
- Clear context before answering questions
- No need to reference separate documents
- Reduces errors in variance calculations

✅ **For Reviewers:**
- AI summaries include target comparisons
- Easier to assess performance at a glance
- Targets embedded in PDF/DOCX exports

✅ **For Administrators:**
- Easy to update targets via CSV
- No code changes needed
- Scalable to all departments

---

## Technical Notes

### Caching
- Targets are cached via `@cache_data` decorator
- Cache invalidates if CSV file changes
- Fast repeated loads within same session

### Matching Logic
- Production name matching is **case-insensitive**
- Matches on both `production_name` and `department`
- Handles missing/null values gracefully

### Display Logic
- Only shows non-null values
- Formats currency with commas (`$400,000`)
- Notes appear in italics below metrics

### AI Integration
- Targets passed to `interpret_scorecard()` via `meta["production_targets"]`
- AI can reference targets in all summary sections
- Works with existing AI prompt structure

---

## Current Productions with Targets

| Production | Budget | Target Seats | Target Revenue | Notes |
|-----------|--------|--------------|----------------|-------|
| Nijinsky | $400,000 | 5,000 | $450,000 | Holiday season flagship |
| Once Upon a Time | $250,000 | 3,200 | $280,000 | Family programming |
| Nutcracker | $600,000 | 8,000 | $720,000 | Annual tradition |
| Romeo and Juliet | $350,000 | 4,200 | $378,000 | Classic repertoire |
| Swan Lake | $500,000 | 6,500 | $585,000 | Major classical |
| Auditions | $15,000 | — | — | Recruitment only |
| Festivals | $75,000 | — | — | External events |

---

*Last updated: January 22, 2026*
