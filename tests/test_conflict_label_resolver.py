#!/usr/bin/env python3
"""
Tests for the conflict label resolver functionality.

Tests the resolve_conflict_label function which translates internal conflict
paths into human-readable labels for display in the UI.
"""
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from merge_scorecards import (
    Conflict,
    ConflictLabel,
    QuestionRegistry,
    resolve_conflict_label,
    _humanize_key,
    _extract_question_id_from_path,
    _derive_section_from_qid,
    _get_kpi_description,
    FIELD_LABEL_MAP,
)


class TestConflictLabel:
    """Tests for the ConflictLabel dataclass."""
    
    def test_display_header(self):
        """Test the display_header method."""
        label = ConflictLabel(
            section_label="Recreational Classes",
            question_label="How many NEW students registered?",
            field_label="Primary answer",
            debug_key="answers.COMM_REC_Q2a › primary"
        )
        assert label.display_header() == "Recreational Classes: How many NEW students registered?"
    
    def test_display_subheader_with_field(self):
        """Test display_subheader with a field label."""
        label = ConflictLabel(
            section_label="Section",
            question_label="Question",
            field_label="Primary answer",
            debug_key="debug_key"
        )
        assert label.display_subheader() == "Primary answer (debug: debug_key)"
    
    def test_display_subheader_without_field(self):
        """Test display_subheader without a field label."""
        label = ConflictLabel(
            section_label="Section",
            question_label="Question",
            field_label="",
            debug_key="debug_key"
        )
        assert label.display_subheader() == "(debug: debug_key)"


class TestQuestionRegistry:
    """Tests for the QuestionRegistry class."""
    
    def test_load_from_csv_bytes(self):
        """Test loading questions from CSV bytes."""
        csv_content = b"""question_id,question_text,section,strategic_pillar,department
COMM_REC_Q2a,"How many NEW students registered?",Recreational Classes,Boost Enrollment,Community
COMM_REC_Q2b,"How many RETURNING students continued?",Recreational Classes,Boost Enrollment,Community
"""
        registry = QuestionRegistry()
        registry.load_from_csv_bytes(csv_content)
        
        assert registry.has_question("COMM_REC_Q2a")
        assert registry.has_question("COMM_REC_Q2b")
        assert not registry.has_question("NONEXISTENT")
    
    def test_get_question_text(self):
        """Test retrieving question text."""
        csv_content = b"""question_id,question_text,section
COMM_REC_Q2a,"How many NEW students registered?",Test Section
"""
        registry = QuestionRegistry()
        registry.load_from_csv_bytes(csv_content)
        
        assert registry.get_question_text("COMM_REC_Q2a") == "How many NEW students registered?"
        assert registry.get_question_text("NONEXISTENT") is None
    
    def test_get_section_label(self):
        """Test retrieving section labels."""
        csv_content = b"""question_id,question_text,section,strategic_pillar
Q1,Question 1,My Section,
Q2,Question 2,,My Pillar
Q3,Question 3,,
"""
        registry = QuestionRegistry()
        registry.load_from_csv_bytes(csv_content)
        
        assert registry.get_section_label("Q1") == "My Section"
        assert registry.get_section_label("Q2") == "My Pillar"
        assert registry.get_section_label("Q3") == "General"
    
    def test_graceful_handling_of_invalid_csv(self):
        """Test that invalid CSV doesn't crash."""
        registry = QuestionRegistry()
        registry.load_from_csv_bytes(b"not valid csv content {{{")
        
        # Should not raise, just return None
        assert registry.get_question_text("anything") is None


class TestHumanizeKey:
    """Tests for the _humanize_key helper function."""
    
    def test_underscore_replacement(self):
        """Test underscore to space conversion."""
        assert _humanize_key("some_key_name") == "Some Key Name"
    
    def test_camel_case_handling(self):
        """Test camelCase splitting."""
        assert _humanize_key("someKeyName") == "Some Key Name"
    
    def test_mixed_format(self):
        """Test mixed underscore and camelCase."""
        assert _humanize_key("some_keyName") == "Some Key Name"


class TestExtractQuestionId:
    """Tests for _extract_question_id_from_path."""
    
    def test_extract_from_section_path(self):
        """Test extracting question ID from section path."""
        assert _extract_question_id_from_path("answers.COMM_REC_Q2a", "primary") == "COMM_REC_Q2a"
        assert _extract_question_id_from_path("answers.ATI01", "primary") == "ATI01"
    
    def test_extract_from_key(self):
        """Test extracting question ID from key when not in section."""
        assert _extract_question_id_from_path("answers", "COMM_REC_Q2a") == "COMM_REC_Q2a"
        assert _extract_question_id_from_path("answers", "ATI03") == "ATI03"
    
    def test_per_show_answers_path(self):
        """Test extraction from per-show answers path."""
        assert _extract_question_id_from_path("per_show_answers.Show1.ATI01", "primary") == "ATI01"
    
    def test_various_prefixes(self):
        """Test various question ID prefixes."""
        prefixes = [
            ("answers.ACSI02", "primary", "ACSI02"),
            ("answers.CR01", "primary", "CR01"),
            ("answers.RA04", "primary", "RA04"),
            ("answers.FE02", "primary", "FE02"),
            ("answers.FM01", "primary", "FM01"),
            ("answers.CORP_GP_Q1", "primary", "CORP_GP_Q1"),
            ("answers.SCH_CT_Q1", "primary", "SCH_CT_Q1"),
        ]
        for section, key, expected in prefixes:
            assert _extract_question_id_from_path(section, key) == expected, f"Failed for {section}/{key}"
    
    def test_no_question_id_found(self):
        """Test when no question ID can be extracted."""
        assert _extract_question_id_from_path("meta", "staff_name") is None


class TestDeriveSectionFromQid:
    """Tests for _derive_section_from_qid."""
    
    def test_community_prefixes(self):
        """Test community-related question ID prefixes."""
        assert _derive_section_from_qid("COMM_ACCESS_Q1") == "Community Access Programs"
        assert _derive_section_from_qid("COMM_REC_Q2a") == "Recreational Classes"
    
    def test_corporate_prefixes(self):
        """Test corporate question ID prefixes."""
        assert _derive_section_from_qid("CORP_GP_Q1") == "Global Presence"
        assert _derive_section_from_qid("CORP_LS_Q1") == "Leadership & Culture"
    
    def test_school_prefixes(self):
        """Test school question ID prefixes."""
        assert _derive_section_from_qid("SCH_CT_Q1") == "Classical Training"
        assert _derive_section_from_qid("SCH_AS_Q1") == "Attracting Students"
    
    def test_artistic_prefixes(self):
        """Test artistic question ID prefixes."""
        assert _derive_section_from_qid("ATI01") == "Artistic & Technical Innovation"
        assert _derive_section_from_qid("ACSI02") == "Artistic Contributions & Social Impact"
        assert _derive_section_from_qid("CR01") == "Collaborations & Residencies"
    
    def test_unknown_prefix(self):
        """Test unknown prefix returns General."""
        assert _derive_section_from_qid("UNKNOWN_Q1") == "General"


class TestGetKpiDescription:
    """Tests for _get_kpi_description."""
    
    def test_two_part_key(self):
        """Test KPI key with two parts."""
        assert _get_kpi_description("DONATIONS/General") == "Donations > General"
    
    def test_three_part_key(self):
        """Test KPI key with three parts."""
        assert _get_kpi_description("GRANTS/Government/AFA") == "Grants > Government > Afa"
    
    def test_dash_subcategory(self):
        """Test that dash subcategory is ignored."""
        assert _get_kpi_description("DONATIONS/General/–") == "Donations > General"
    
    def test_underscore_handling(self):
        """Test underscore to space conversion in KPI keys."""
        assert _get_kpi_description("TICKET_SALES/subscriptions") == "Ticket Sales > Subscriptions"


class TestResolveConflictLabel:
    """Tests for the main resolve_conflict_label function."""
    
    def test_kpi_conflict_without_registry(self):
        """Test resolving a KPI conflict without a registry."""
        conflict = Conflict(
            section="financial_kpis_actuals",
            key="DONATIONS/General/–",
            values=[(100000.0, "user1"), (150000.0, "user2")]
        )
        
        label = resolve_conflict_label(conflict, None)
        
        assert label.section_label == "Financial KPIs"
        assert "Donations" in label.question_label
        assert "General" in label.question_label
        assert label.field_label == "Actual value"
        assert "financial_kpis_actuals" in label.debug_key
    
    def test_answer_conflict_with_registry(self):
        """Test resolving an answer conflict with a registry."""
        # Create registry with test data
        csv_content = b"""question_id,question_text,section,strategic_pillar
COMM_REC_Q2a,"If yes, how many NEW recreational students registered this period?",Recreational Classes,Boost Enrollment
"""
        registry = QuestionRegistry()
        registry.load_from_csv_bytes(csv_content)
        
        conflict = Conflict(
            section="answers.COMM_REC_Q2a",
            key="primary",
            values=[("100", "user1"), ("150", "user2")]
        )
        
        label = resolve_conflict_label(conflict, registry)
        
        assert label.section_label == "Recreational Classes"
        assert "NEW recreational students" in label.question_label
        assert label.field_label == "Primary answer"
        assert "COMM_REC_Q2a" in label.debug_key
    
    def test_answer_conflict_without_registry(self):
        """Test resolving an answer conflict without a registry (fallback)."""
        conflict = Conflict(
            section="answers.COMM_REC_Q2a",
            key="primary",
            values=[("100", "user1"), ("150", "user2")]
        )
        
        label = resolve_conflict_label(conflict, None)
        
        # Should use fallback behavior
        assert label.section_label == "Recreational Classes"  # Derived from prefix
        assert "Comm Rec Q2A" in label.question_label  # Humanized
        assert label.field_label == "Primary answer"
    
    def test_per_show_conflict(self):
        """Test resolving a per-show answer conflict."""
        conflict = Conflict(
            section="per_show_answers.Artistic::Nutcracker.ATI01",
            key="primary",
            values=[("3", "user1"), ("4", "user2")]
        )
        
        label = resolve_conflict_label(conflict, None)
        
        # Should extract question ID and derive section from it
        # ATI01 is an Artistic question, so section comes from question ID prefix
        assert label.section_label == "Artistic & Technical Innovation"
        assert label.field_label == "Primary answer"
        # Debug key should contain full path including show name
        assert "Nutcracker" in label.debug_key
    
    def test_unknown_key_graceful_fallback(self):
        """Test that unknown keys get a graceful fallback."""
        conflict = Conflict(
            section="some_unknown_section",
            key="some_unknown_key",
            values=[("val1", "user1"), ("val2", "user2")]
        )
        
        label = resolve_conflict_label(conflict, None)
        
        # Should not crash, should return some reasonable label
        assert label.section_label  # Not empty
        assert label.question_label  # Not empty
        assert label.debug_key  # Contains original path
    
    def test_field_label_mapping(self):
        """Test that common field names get proper labels."""
        test_cases = [
            ("primary", "Primary answer"),
            ("description", "Description/Notes"),
            ("notes", "Notes"),
            ("actual", "Actual value"),
        ]
        
        for key, expected_label in test_cases:
            conflict = Conflict(
                section="answers.ATI01",
                key=key,
                values=[("a", "u1"), ("b", "u2")]
            )
            label = resolve_conflict_label(conflict, None)
            assert label.field_label == expected_label, f"Failed for key={key}"


class TestIntegrationWithRealData:
    """Integration tests using real CSV data from the repository."""
    
    @pytest.fixture
    def real_registry(self):
        """Load the real community scorecard questions."""
        csv_path = Path(__file__).parent.parent / "data" / "community_scorecard_questions.csv"
        if csv_path.exists():
            registry = QuestionRegistry()
            registry.load_from_csv_file(csv_path)
            return registry
        pytest.skip("Community scorecard CSV not found")
    
    def test_comm_rec_q2a_with_real_data(self, real_registry):
        """Test COMM_REC_Q2a resolves to full question text."""
        conflict = Conflict(
            section="answers.COMM_REC_Q2a",
            key="primary",
            values=[("100", "user1"), ("150", "user2")]
        )
        
        label = resolve_conflict_label(conflict, real_registry)
        
        # Should contain the real question text
        assert "NEW" in label.question_label.upper() or "students" in label.question_label.lower()
        assert label.section_label  # Should have a section
        assert label.field_label == "Primary answer"
    
    def test_multiple_community_questions(self, real_registry):
        """Test multiple community questions resolve correctly."""
        questions_to_test = [
            "COMM_ACCESS_Q1",
            "COMM_REC_Q1", 
            "COMM_REC_Q2",
        ]
        
        for qid in questions_to_test:
            if real_registry.has_question(qid):
                conflict = Conflict(
                    section=f"answers.{qid}",
                    key="primary",
                    values=[("Yes", "u1"), ("No", "u2")]
                )
                
                label = resolve_conflict_label(conflict, real_registry)
                
                # All should resolve without errors
                assert label.section_label
                assert label.question_label
                assert len(label.question_label) > 10  # Should be meaningful text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
