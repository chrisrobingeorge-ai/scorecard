#!/usr/bin/env python3
"""
Test script to demonstrate the JSON merge bug in the Scorecard app.

This script loads the current merge logic from app.py and shows how 
financial KPI data is being lost when merging multiple JSON files.
"""
import json
import sys
from pathlib import Path

# Add parent directory to path to import from app.py
sys.path.insert(0, str(Path(__file__).parent.parent))


def load_fixture(filename):
    """Load a test fixture JSON file."""
    fixture_path = Path(__file__).parent / "fixtures" / filename
    with open(fixture_path, 'r') as f:
        return json.load(f)


def test_current_merge_logic():
    """
    Replicate the current merge logic from queue_multiple_draft_bytes()
    in app.py lines 692-764 to demonstrate the bug.
    """
    print("=" * 80)
    print("TESTING CURRENT MERGE LOGIC")
    print("=" * 80)
    
    # Load test fixtures
    user1_data = load_fixture("user1_draft.json")
    user2_data = load_fixture("user2_draft.json")
    
    print("\n📄 User 1 Data:")
    print(f"  Answers: {list(user1_data['answers'].keys())}")
    print(f"  Financial KPIs: {len(user1_data['financial_kpis_actuals'])} entries")
    for kpi in user1_data['financial_kpis_actuals']:
        print(f"    - {kpi['area']}/{kpi['category']}/{kpi['sub_category']}: {kpi['actual']}")
    
    print("\n📄 User 2 Data:")
    print(f"  Answers: {list(user2_data['answers'].keys())}")
    print(f"  Financial KPIs: {len(user2_data['financial_kpis_actuals'])} entries")
    for kpi in user2_data['financial_kpis_actuals']:
        print(f"    - {kpi['area']}/{kpi['category']}/{kpi['sub_category']}: {kpi['actual']}")
    
    # Simulate current merge logic (from lines 692-764 in app.py)
    merged_data = {
        "meta": {},
        "answers": {},
        "per_show_answers": {},
        "financial_kpis_actuals": [],
    }
    
    for i, data in enumerate([user1_data, user2_data], 1):
        print(f"\n🔄 Processing file {i}...")
        
        # Merge meta - later files override earlier ones
        if "meta" in data and data["meta"]:
            merged_data["meta"].update(data["meta"])
        
        # Merge answers - later files override earlier ones for the same question
        if "answers" in data and data["answers"]:
            merged_data["answers"].update(data["answers"])
        
        # Merge per_show_answers - merge at show level
        if "per_show_answers" in data and data["per_show_answers"]:
            for show_key, show_answers in data["per_show_answers"].items():
                if show_key not in merged_data["per_show_answers"]:
                    merged_data["per_show_answers"][show_key] = {}
                merged_data["per_show_answers"][show_key].update(show_answers)
        
        # Merge financial_kpis_actuals - combine and deduplicate
        if "financial_kpis_actuals" in data and data["financial_kpis_actuals"]:
            for kpi in data["financial_kpis_actuals"]:
                # Check if this KPI already exists (by area, category, sub_category)
                key = (kpi.get("area"), kpi.get("category"), kpi.get("sub_category"))
                existing_idx = None
                for idx, existing in enumerate(merged_data["financial_kpis_actuals"]):
                    existing_key = (existing.get("area"), existing.get("category"), existing.get("sub_category"))
                    if existing_key == key:
                        existing_idx = idx
                        break
                if existing_idx is not None:
                    # Update existing - later files override
                    print(f"  ⚠️  OVERWRITING: {key} - {merged_data['financial_kpis_actuals'][existing_idx]['actual']} → {kpi['actual']}")
                    merged_data["financial_kpis_actuals"][existing_idx] = kpi
                else:
                    print(f"  ✅ Adding: {key} = {kpi['actual']}")
                    merged_data["financial_kpis_actuals"].append(kpi)
    
    print("\n" + "=" * 80)
    print("MERGE RESULT")
    print("=" * 80)
    print(f"\n✅ Answers merged: {list(merged_data['answers'].keys())}")
    print(f"✅ Financial KPIs in result: {len(merged_data['financial_kpis_actuals'])} entries")
    for kpi in merged_data['financial_kpis_actuals']:
        print(f"    - {kpi['area']}/{kpi['category']}/{kpi['sub_category']}: {kpi['actual']}")
    
    print("\n" + "=" * 80)
    print("BUG ANALYSIS")
    print("=" * 80)
    
    # Analyze what went wrong
    expected_kpis = set()
    for data in [user1_data, user2_data]:
        for kpi in data['financial_kpis_actuals']:
            key = (kpi['area'], kpi['category'], kpi['sub_category'])
            expected_kpis.add(key)
    
    actual_kpis = set()
    for kpi in merged_data['financial_kpis_actuals']:
        key = (kpi['area'], kpi['category'], kpi['sub_category'])
        actual_kpis.add(key)
    
    print(f"\n📊 Expected unique KPI lines: {len(expected_kpis)}")
    print(f"📊 Actual KPI lines in merge: {len(actual_kpis)}")
    
    if expected_kpis == actual_kpis:
        print("✅ No KPI lines were lost!")
    else:
        print("❌ BUG DETECTED: Some KPI lines were affected!")
    
    # Check for the specific issue: default 0 overwriting non-default value
    print("\n🔍 Checking for default-overwriting-nondefault bug...")
    donations_general = None
    for kpi in merged_data['financial_kpis_actuals']:
        if (kpi['area'], kpi['category'], kpi['sub_category']) == ('DONATIONS', 'General', '–'):
            donations_general = kpi['actual']
            break
    
    if donations_general == 0.0:
        print("❌ BUG CONFIRMED: 'DONATIONS/General/–' was set to 100000 by User 1")
        print("   but User 2's default value of 0 overwrote it!")
        print("   Expected: 100000.0 (non-default value should win)")
        print(f"   Actual: {donations_general} (default value won)")
    elif donations_general == 100000.0:
        print("✅ 'DONATIONS/General/–' correctly preserved User 1's value of 100000")
    
    return merged_data


if __name__ == "__main__":
    result = test_current_merge_logic()
    
    print("\n" + "=" * 80)
    print("CONCLUSION")
    print("=" * 80)
    print("""
The current merge logic has the following issues:

1. ❌ OVERWRITES NON-DEFAULTS WITH DEFAULTS
   When User 2's JSON contains a KPI with value 0 (default), it overwrites 
   User 1's intentionally entered value of 100000.
   
2. ❌ NO DISTINCTION BETWEEN "NOT TOUCHED" AND "EXPLICITLY SET TO 0"
   The app cannot distinguish between:
   - A user who never edited a field (should remain default)
   - A user who explicitly set a field to 0 (intentional value)
   
3. ❌ LAST-FILE-WINS POLICY IS TOO NAIVE
   Simply taking the last file's value doesn't account for which user 
   actually provided meaningful data.

RECOMMENDED FIX:
- Implement a smart merge that prefers non-zero values over zero values
- Add metadata to track which fields were actually edited by users
- Implement conflict detection when both files have non-zero values that differ
- Provide UI for users to resolve conflicts
""")
