"""
merge_scorecards.py

Deep merge logic for combining multiple scorecard JSON files from different users.

This module provides intelligent merging that:
- Preserves all data from multiple sources
- Detects and reports conflicts
- Prefers non-default values over defaults
- Tracks data provenance (which file contributed which data)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum
import copy


class MergePolicy(Enum):
    """Policy for resolving conflicts when merging."""
    NON_DEFAULT_WINS = "non_default_wins"  # Prefer non-default over default
    LAST_WINS = "last_wins"  # Later file overwrites earlier
    FIRST_WINS = "first_wins"  # First file wins
    CONFLICT = "conflict"  # Mark as conflict, require manual resolution


@dataclass
class Conflict:
    """Represents a conflict between two values during merge."""
    section: str
    key: str
    values: List[Tuple[Any, str]]  # [(value, source_filename), ...]
    
    def __repr__(self):
        return f"Conflict({self.section}/{self.key}: {self.values})"


@dataclass
class MergeResult:
    """Result of merging multiple scorecard JSON files."""
    merged_data: Dict[str, Any]
    conflicts: List[Conflict] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)  # List of source filenames
    stats: Dict[str, int] = field(default_factory=dict)  # Merge statistics
    
    @property
    def has_conflicts(self) -> bool:
        return len(self.conflicts) > 0


def is_default_value(value: Any, field_type: str = "general") -> bool:
    """
    Determine if a value is a "default" (i.e., likely untouched by user).
    
    Args:
        value: The value to check
        field_type: Type hint for the field (e.g., "number", "text", "kpi")
    
    Returns:
        True if value appears to be a default/empty value
    """
    if value is None:
        return True
    
    if field_type in ("number", "kpi", "financial"):
        # For numeric fields, 0 is considered default
        try:
            return float(value) == 0.0
        except (ValueError, TypeError):
            return False
    
    if isinstance(value, str):
        # Empty or whitespace-only strings are defaults
        return value.strip() == ""
    
    if isinstance(value, (list, dict)):
        # Empty collections are defaults
        return len(value) == 0
    
    return False


def merge_kpi_entries(
    entries: List[Tuple[Dict[str, Any], str]],
    policy: MergePolicy = MergePolicy.NON_DEFAULT_WINS
) -> Tuple[Dict[str, Any], Optional[Conflict]]:
    """
    Merge multiple KPI entries for the same KPI line.
    
    Args:
        entries: List of (kpi_dict, source_filename) tuples
        policy: Merge policy to use
    
    Returns:
        (merged_kpi, conflict) - conflict is None if no conflict detected
    """
    if not entries:
        return {}, None
    
    if len(entries) == 1:
        return entries[0][0], None
    
    # Extract the key for this KPI
    first_entry = entries[0][0]
    kpi_key = f"{first_entry.get('area', '')}/{first_entry.get('category', '')}/{first_entry.get('sub_category', '')}"
    
    # Collect all actuals and their sources
    actuals_with_sources = [(e[0].get('actual', 0.0), e[1]) for e in entries]
    
    # Apply merge policy
    if policy == MergePolicy.NON_DEFAULT_WINS:
        # Find non-default values
        non_defaults = [(val, src) for val, src in actuals_with_sources 
                        if not is_default_value(val, "kpi")]
        
        if len(non_defaults) == 0:
            # All are defaults, take the last one
            result = copy.deepcopy(entries[-1][0])
            return result, None
        
        elif len(non_defaults) == 1:
            # Exactly one non-default, use it
            for entry, source in entries:
                if entry.get('actual', 0.0) == non_defaults[0][0]:
                    result = copy.deepcopy(entry)
                    return result, None
        
        else:
            # Multiple non-defaults - check if they're all the same
            unique_non_defaults = set(val for val, _ in non_defaults)
            if len(unique_non_defaults) == 1:
                # All non-defaults are the same value
                for entry, source in entries:
                    if entry.get('actual', 0.0) == non_defaults[0][0]:
                        result = copy.deepcopy(entry)
                        return result, None
            else:
                # Real conflict: multiple different non-default values
                conflict = Conflict(
                    section="financial_kpis_actuals",
                    key=kpi_key,
                    values=non_defaults
                )
                # Use the last non-default as the merged value
                for entry, source in reversed(entries):
                    if not is_default_value(entry.get('actual', 0.0), "kpi"):
                        result = copy.deepcopy(entry)
                        return result, conflict
    
    elif policy == MergePolicy.LAST_WINS:
        return copy.deepcopy(entries[-1][0]), None
    
    elif policy == MergePolicy.FIRST_WINS:
        return copy.deepcopy(entries[0][0]), None
    
    # Default: last wins
    return copy.deepcopy(entries[-1][0]), None


def merge_nested_dict(
    target: Dict[str, Any],
    source: Dict[str, Any],
    source_name: str,
    conflicts: List[Conflict],
    section_name: str = "answers",
    policy: MergePolicy = MergePolicy.NON_DEFAULT_WINS
) -> None:
    """
    Deep merge source dict into target dict, detecting conflicts.
    
    Args:
        target: Target dictionary (modified in place)
        source: Source dictionary to merge in
        source_name: Name of source file (for conflict reporting)
        conflicts: List to append conflicts to
        section_name: Name of section being merged (for conflict reporting)
        policy: Merge policy
    """
    for key, source_value in source.items():
        if key not in target:
            # New key, just add it
            target[key] = copy.deepcopy(source_value)
        else:
            target_value = target[key]
            
            # Both exist - need to merge intelligently
            if isinstance(source_value, dict) and isinstance(target_value, dict):
                # Recursive merge for nested dicts
                merge_nested_dict(
                    target_value, 
                    source_value, 
                    source_name, 
                    conflicts,
                    f"{section_name}.{key}",
                    policy
                )
            else:
                # Leaf values - apply merge policy
                if policy == MergePolicy.NON_DEFAULT_WINS:
                    target_is_default = is_default_value(target_value)
                    source_is_default = is_default_value(source_value)
                    
                    if target_is_default and not source_is_default:
                        # Source has real value, target is default -> use source
                        target[key] = copy.deepcopy(source_value)
                    elif not target_is_default and source_is_default:
                        # Target has real value, source is default -> keep target
                        pass
                    elif not target_is_default and not source_is_default:
                        # Both have real values - check if they differ
                        if target_value != source_value:
                            conflicts.append(Conflict(
                                section=section_name,
                                key=str(key),
                                values=[(target_value, "previous"), (source_value, source_name)]
                            ))
                        # Keep target value (could also keep source)
                    # else: both defaults, keep target
                
                elif policy == MergePolicy.LAST_WINS:
                    target[key] = copy.deepcopy(source_value)
                
                elif policy == MergePolicy.FIRST_WINS:
                    pass  # Keep target
                
                else:
                    # Default to last wins
                    target[key] = copy.deepcopy(source_value)


def merge_scorecards(
    scorecards: List[Tuple[Dict[str, Any], str]],
    policy: MergePolicy = MergePolicy.NON_DEFAULT_WINS,
    defaults: Optional[Dict[str, Any]] = None
) -> MergeResult:
    """
    Merge multiple scorecard JSON files intelligently.
    
    Args:
        scorecards: List of (scorecard_dict, source_filename) tuples
        policy: Merge policy to apply
        defaults: Optional dict of default values to help identify untouched fields
    
    Returns:
        MergeResult with merged data and any conflicts detected
    """
    if not scorecards:
        return MergeResult(merged_data={}, conflicts=[], sources=[])
    
    if len(scorecards) == 1:
        return MergeResult(
            merged_data=copy.deepcopy(scorecards[0][0]),
            conflicts=[],
            sources=[scorecards[0][1]]
        )
    
    # Initialize result
    merged = {
        "meta": {},
        "answers": {},
        "per_show_answers": {},
        "financial_kpis_actuals": [],
    }
    
    conflicts: List[Conflict] = []
    sources = [name for _, name in scorecards]
    stats = {
        "files_merged": len(scorecards),
        "answers_merged": 0,
        "kpis_merged": 0,
        "conflicts_detected": 0,
    }
    
    # Process each scorecard
    for scorecard_data, source_name in scorecards:
        # Merge meta - later files can override
        if "meta" in scorecard_data and scorecard_data["meta"]:
            for key, value in scorecard_data["meta"].items():
                if key not in merged["meta"] or value not in (None, ""):
                    merged["meta"][key] = value
        
        # Merge answers with conflict detection
        if "answers" in scorecard_data and scorecard_data["answers"]:
            merge_nested_dict(
                merged["answers"],
                scorecard_data["answers"],
                source_name,
                conflicts,
                "answers",
                policy
            )
        
        # Merge per_show_answers
        if "per_show_answers" in scorecard_data and scorecard_data["per_show_answers"]:
            for show_key, show_answers in scorecard_data["per_show_answers"].items():
                if show_key not in merged["per_show_answers"]:
                    merged["per_show_answers"][show_key] = {}
                
                merge_nested_dict(
                    merged["per_show_answers"][show_key],
                    show_answers,
                    source_name,
                    conflicts,
                    f"per_show_answers.{show_key}",
                    policy
                )
        
        # Merge financial KPIs by key (area, category, sub_category)
        if "financial_kpis_actuals" in scorecard_data and scorecard_data["financial_kpis_actuals"]:
            for kpi in scorecard_data["financial_kpis_actuals"]:
                key = (kpi.get("area"), kpi.get("category"), kpi.get("sub_category"))
                
                # Find if this KPI already exists in merged
                existing_idx = None
                for idx, existing_kpi in enumerate(merged["financial_kpis_actuals"]):
                    existing_key = (
                        existing_kpi.get("area"),
                        existing_kpi.get("category"),
                        existing_kpi.get("sub_category")
                    )
                    if existing_key == key:
                        existing_idx = idx
                        break
                
                if existing_idx is not None:
                    # Merge with existing KPI entry
                    existing_entry = merged["financial_kpis_actuals"][existing_idx]
                    merged_kpi, conflict = merge_kpi_entries(
                        [(existing_entry, "previous"), (kpi, source_name)],
                        policy
                    )
                    merged["financial_kpis_actuals"][existing_idx] = merged_kpi
                    if conflict:
                        conflicts.append(conflict)
                else:
                    # New KPI, add it
                    merged["financial_kpis_actuals"].append(copy.deepcopy(kpi))
        
        # Merge ai_result - later files override
        if "ai_result" in scorecard_data and scorecard_data["ai_result"]:
            merged["ai_result"] = copy.deepcopy(scorecard_data["ai_result"])
        
        # Merge kpi_explanations - concatenate
        if "kpi_explanations" in scorecard_data and scorecard_data["kpi_explanations"]:
            if "kpi_explanations" not in merged or not merged["kpi_explanations"]:
                merged["kpi_explanations"] = scorecard_data["kpi_explanations"]
            else:
                merged["kpi_explanations"] += "\n\n" + scorecard_data["kpi_explanations"]
    
    # Update stats
    stats["answers_merged"] = len(merged.get("answers", {}))
    stats["kpis_merged"] = len(merged.get("financial_kpis_actuals", []))
    stats["conflicts_detected"] = len(conflicts)
    
    return MergeResult(
        merged_data=merged,
        conflicts=conflicts,
        sources=sources,
        stats=stats
    )


def format_conflicts_for_display(conflicts: List[Conflict]) -> str:
    """
    Format conflicts into a human-readable string for UI display.
    
    Args:
        conflicts: List of conflicts
    
    Returns:
        Formatted string describing all conflicts
    """
    if not conflicts:
        return "No conflicts detected."
    
    lines = [f"⚠️  {len(conflicts)} conflict(s) detected:\n"]
    
    for i, conflict in enumerate(conflicts, 1):
        lines.append(f"{i}. **{conflict.section}** / `{conflict.key}`:")
        for value, source in conflict.values:
            lines.append(f"   - {source}: `{value}`")
        lines.append("")
    
    return "\n".join(lines)


def apply_conflict_resolutions(
    merged_data: Dict[str, Any],
    conflicts: List[Conflict],
    resolutions: Dict[int, int]
) -> Dict[str, Any]:
    """
    Apply user's conflict resolution choices to the merged data.
    
    Args:
        merged_data: The merged data with conflicts
        conflicts: List of conflicts
        resolutions: Dict mapping conflict index to chosen value index
                     e.g., {0: 1, 1: 0} means conflict 0 uses value 1, conflict 1 uses value 0
    
    Returns:
        Updated merged data with conflicts resolved
    """
    result = copy.deepcopy(merged_data)
    
    for conflict_idx, value_idx in resolutions.items():
        if conflict_idx >= len(conflicts):
            continue
            
        conflict = conflicts[conflict_idx]
        if value_idx >= len(conflict.values):
            continue
        
        chosen_value, _ = conflict.values[value_idx]
        
        # Apply the resolution based on section type
        if conflict.section == "financial_kpis_actuals":
            # Parse the KPI key
            key_parts = conflict.key.split("/")
            if len(key_parts) == 3:
                area, category, sub_category = key_parts
                
                # Find and update the KPI entry
                for kpi in result.get("financial_kpis_actuals", []):
                    if (kpi.get("area") == area and 
                        kpi.get("category") == category and 
                        kpi.get("sub_category") == sub_category):
                        kpi["actual"] = chosen_value
                        break
        
        elif conflict.section.startswith("answers"):
            # Handle nested answer keys like "answers.Q1.primary"
            keys = conflict.section.split(".")[1:] + [conflict.key]
            
            # Navigate to the nested location
            current = result.get("answers", {})
            for key in keys[:-1]:
                if key not in current:
                    current[key] = {}
                current = current[key]
            
            # Set the chosen value
            if keys:
                current[keys[-1]] = chosen_value
        
        elif conflict.section.startswith("per_show_answers"):
            # Handle per-show answers like "per_show_answers.Show1.Q1"
            parts = conflict.section.split(".", 2)
            if len(parts) >= 2:
                show_key = parts[1] if len(parts) > 1 else ""
                
                if show_key in result.get("per_show_answers", {}):
                    # Navigate through nested structure
                    remaining_keys = parts[2:] if len(parts) > 2 else []
                    remaining_keys.append(conflict.key)
                    
                    current = result["per_show_answers"][show_key]
                    for key in remaining_keys[:-1]:
                        if key not in current:
                            current[key] = {}
                        current = current[key]
                    
                    if remaining_keys:
                        current[remaining_keys[-1]] = chosen_value
        
        else:
            # Generic handling for other sections
            if conflict.key in result.get(conflict.section, {}):
                result[conflict.section][conflict.key] = chosen_value
    
    return result
