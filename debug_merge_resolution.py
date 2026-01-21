#!/usr/bin/env python3
"""
Debug script to test the full merge and resolution flow.
"""
import json
from merge_scorecards import merge_scorecards, MergePolicy, apply_conflict_resolutions

# Create two scorecards with conflicting values
data1 = {
    "meta": {
        "department": "Community",
        "production": "Recreational Classes",
        "month": "2026-01"
    },
    "per_show_answers": {
        "Community::Recreational Classes": {
            "COMM_REC_Q2a": {
                "primary": "100"
            }
        }
    }
}

data2 = {
    "meta": {
        "department": "Community",
        "production": "Recreational Classes",
        "month": "2026-01"
    },
    "per_show_answers": {
        "Community::Recreational Classes": {
            "COMM_REC_Q2a": {
                "primary": "150"
            }
        }
    }
}

print("=" * 80)
print("STEP 1: Merge scorecards")
print("=" * 80)

result = merge_scorecards(
    [(data1, "user1.json"), (data2, "user2.json")],
    policy=MergePolicy.NON_DEFAULT_WINS
)

print(f"Has conflicts: {result.has_conflicts}")
print(f"Number of conflicts: {len(result.conflicts)}")

if result.has_conflicts:
    print("\nConflicts detected:")
    for i, conflict in enumerate(result.conflicts):
        print(f"  {i}. Section: {conflict.section}")
        print(f"     Key: {conflict.key}")
        print(f"     Values: {conflict.values}")
    
    print("\n" + "=" * 80)
    print("STEP 2: Apply resolution (choose first value)")
    print("=" * 80)
    
    # User chooses first value for all conflicts
    resolutions = {i: 0 for i in range(len(result.conflicts))}
    
    resolved_data = apply_conflict_resolutions(
        result.merged_data,
        result.conflicts,
        resolutions
    )
    
    print("\nResolved data:")
    print(json.dumps(resolved_data, indent=2))
    
    # Verify the resolution
    try:
        value = resolved_data["per_show_answers"]["Community::Recreational Classes"]["COMM_REC_Q2a"]["primary"]
        print(f"\n✅ Resolution successful! Value is: {value}")
        assert value == "100", f"Expected 100, got {value}"
        print("✅ Assertion passed - value is correct!")
    except (KeyError, AssertionError) as e:
        print(f"\n❌ Resolution failed: {e}")
        print("\nFull data structure:")
        print(json.dumps(resolved_data, indent=2))
else:
    print("❌ No conflicts detected - test cannot proceed")

print("\n" + "=" * 80)
print("STEP 3: Simulate saving to JSON and reloading")
print("=" * 80)

if result.has_conflicts:
    # Simulate what the app does
    merged_bytes = json.dumps(resolved_data).encode("utf-8")
    print(f"Encoded to {len(merged_bytes)} bytes")
    
    # Reload
    reloaded = json.loads(merged_bytes.decode("utf-8"))
    print("Reloaded successfully")
    
    # Verify
    try:
        value = reloaded["per_show_answers"]["Community::Recreational Classes"]["COMM_REC_Q2a"]["primary"]
        print(f"✅ Value after reload: {value}")
        assert value == "100"
        print("✅ Full flow works correctly!")
    except (KeyError, AssertionError) as e:
        print(f"❌ Reload failed: {e}")
