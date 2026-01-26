"""
Unit tests for merge_scorecards module.

Tests the intelligent merge logic for combining multiple scorecard JSON files.
"""
import pytest
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from merge_scorecards import (
    merge_scorecards,
    MergePolicy,
    is_default_value,
    Conflict,
)


class TestIsDefaultValue:
    """Test the is_default_value function."""
    
    def test_none_is_default(self):
        assert is_default_value(None)
    
    def test_zero_is_default_for_numbers(self):
        assert is_default_value(0, "number")
        assert is_default_value(0.0, "kpi")
        assert is_default_value("0", "financial")
    
    def test_empty_string_is_default(self):
        assert is_default_value("")
        assert is_default_value("   ")
    
    def test_non_empty_string_not_default(self):
        assert not is_default_value("something")
        assert not is_default_value("Yes")
    
    def test_nonzero_number_not_default(self):
        assert not is_default_value(100, "kpi")
        assert not is_default_value(42.5, "financial")
    
    def test_empty_collections_are_default(self):
        assert is_default_value([])
        assert is_default_value({})


class TestMergeScorecards:
    """Test the main merge_scorecards function."""
    
    def test_empty_list_returns_empty(self):
        result = merge_scorecards([])
        assert result.merged_data == {}
        assert result.conflicts == []
    
    def test_single_scorecard_no_merge(self):
        data = {"meta": {"department": "Artistic"}, "answers": {"Q1": {"primary": "Yes"}}}
        result = merge_scorecards([(data, "file1")])
        
        assert result.merged_data["meta"]["department"] == "Artistic"
        assert result.merged_data["answers"]["Q1"]["primary"] == "Yes"
        assert len(result.conflicts) == 0
    
    def test_merge_disjoint_answers(self):
        data1 = {"answers": {"Q1": {"primary": "Yes"}}}
        data2 = {"answers": {"Q2": {"primary": "No"}}}
        
        result = merge_scorecards([(data1, "file1"), (data2, "file2")])
        
        assert "Q1" in result.merged_data["answers"]
        assert "Q2" in result.merged_data["answers"]
        assert result.merged_data["answers"]["Q1"]["primary"] == "Yes"
        assert result.merged_data["answers"]["Q2"]["primary"] == "No"
        assert len(result.conflicts) == 0
    
    def test_merge_with_real_fixtures(self):
        """Integration test using actual test fixtures."""
        import json
        
        fixtures_dir = Path(__file__).parent / "fixtures"
        
        with open(fixtures_dir / "user1_draft.json") as f:
            user1_data = json.load(f)
        
        with open(fixtures_dir / "user2_draft.json") as f:
            user2_data = json.load(f)
        
        result = merge_scorecards(
            [(user1_data, "user1_draft.json"), (user2_data, "user2_draft.json")],
            policy=MergePolicy.NON_DEFAULT_WINS
        )
        
        # Check that answers from both users are present
        assert "ATI01" in result.merged_data["answers"]  # From user1
        assert "ATI03" in result.merged_data["answers"]  # From user2


class TestMergePolicy:
    """Test different merge policies."""
    
    def test_last_wins_policy(self):
        data1 = {"answers": {"Q1": {"primary": "Yes"}}}
        data2 = {"answers": {"Q1": {"primary": "No"}}}
        
        result = merge_scorecards(
            [(data1, "file1"), (data2, "file2")],
            policy=MergePolicy.LAST_WINS
        )
        
        assert result.merged_data["answers"]["Q1"]["primary"] == "No"
        # LAST_WINS doesn't detect conflicts
        assert len(result.conflicts) == 0
    
    def test_first_wins_policy(self):
        data1 = {"answers": {"Q1": {"primary": "Yes"}}}
        data2 = {"answers": {"Q1": {"primary": "No"}}}
        
        result = merge_scorecards(
            [(data1, "file1"), (data2, "file2")],
            policy=MergePolicy.FIRST_WINS
        )
        
        assert result.merged_data["answers"]["Q1"]["primary"] == "Yes"
        assert len(result.conflicts) == 0


class TestNestedMerge:
    """Test deep merging of nested structures."""
    
    def test_per_show_answers_merge(self):
        data1 = {
            "per_show_answers": {
                "Artistic::Show1": {
                    "Q1": {"primary": "Yes"}
                }
            }
        }
        data2 = {
            "per_show_answers": {
                "Artistic::Show1": {
                    "Q2": {"primary": "No"}
                },
                "Artistic::Show2": {
                    "Q3": {"primary": "Maybe"}
                }
            }
        }
        
        result = merge_scorecards([(data1, "file1"), (data2, "file2")])
        
        # Check that Show1 has both Q1 and Q2
        assert "Q1" in result.merged_data["per_show_answers"]["Artistic::Show1"]
        assert "Q2" in result.merged_data["per_show_answers"]["Artistic::Show1"]
        # Check that Show2 is also present
        assert "Artistic::Show2" in result.merged_data["per_show_answers"]
        assert "Q3" in result.merged_data["per_show_answers"]["Artistic::Show2"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
