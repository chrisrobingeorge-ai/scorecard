# Fix: Merge Conflict Resolution - Answers Loading Issue

## Problem
When users clicked "✅ Apply Merge with Selected Values" after resolving conflicts, their selected answer values were not appearing in the application after reload.

## Root Cause
The `_normalise_loaded_entry()` function in `app.py` performed strict validation on answer values. Values that didn't exactly match the expected format (e.g., not in dropdown options list) were silently dropped during the load process.

## Solution
Modified `_normalise_loaded_entry()` to use lenient validation:
- Accept values even if they don't perfectly match validation rules
- Essential for merge conflict resolution where values from different sources may have slight formatting differences
- Prevents silent data loss

## Changes
- **app.py** (lines ~807-860): Updated validation logic to be lenient
- Added fallback logic for all validation types (yes/no, select, dropdown, scale, number)
- Values are now preserved as strings if they don't match strict validation

## Result
✅ Merge conflict resolutions now work correctly
✅ User-selected values are preserved and displayed
