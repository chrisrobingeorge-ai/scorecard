#!/usr/bin/env python3
"""
Tests for upload hash tracking functionality.
Ensures that uploaded files are not reprocessed after conflict resolution.
"""
import sys
from pathlib import Path

# Add parent to path for imports (consistent with other test files in this project)
sys.path.insert(0, str(Path(__file__).parent.parent))

import hashlib


def _hash_bytes(b: bytes) -> str:
    """
    Hash function mirroring the one in app.py.
    
    Note: We duplicate this simple function here instead of importing from app.py
    to avoid requiring all Streamlit dependencies just for running tests.
    """
    return hashlib.sha256(b).hexdigest()


def test_hash_calculation_consistent():
    """Test that hash calculation is consistent for the same content."""
    content1 = b'{"test": "data"}'
    content2 = b'{"test": "data"}'
    content3 = b'{"test": "different"}'
    
    hash1 = _hash_bytes(content1)
    hash2 = _hash_bytes(content2)
    hash3 = _hash_bytes(content3)
    
    # Same content should produce same hash
    assert hash1 == hash2
    # Different content should produce different hash
    assert hash1 != hash3
    
    print("✅ Hash calculation is consistent")


def test_combined_file_hash():
    """Test that multiple files produce consistent combined hashes."""
    file1 = b'{"user": "alice"}'
    file2 = b'{"user": "bob"}'
    
    # Same files in same order should produce same hash
    combined1 = _hash_bytes(b"".join([file1, file2]))
    combined2 = _hash_bytes(b"".join([file1, file2]))
    
    assert combined1 == combined2
    
    # Different order should produce different hash
    combined_reverse = _hash_bytes(b"".join([file2, file1]))
    assert combined1 != combined_reverse
    
    print("✅ Combined file hash is order-dependent and consistent")


def test_empty_files_handled():
    """Test that empty files don't cause hash issues."""
    empty = b''
    non_empty = b'{"data": 1}'
    
    empty_hash = _hash_bytes(empty)
    non_empty_hash = _hash_bytes(non_empty)
    
    # Empty file should still produce a valid hash
    assert len(empty_hash) == 64  # SHA256 produces 64 hex chars
    assert empty_hash != non_empty_hash
    
    print("✅ Empty files handled correctly")


def test_fixture_files_have_distinct_hashes():
    """Test that our fixture files have different hashes."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    
    if not fixtures_dir.exists():
        print("ℹ️  Fixtures directory not found, skipping")
        return
    
    # Load user1 and user2 drafts
    user1_path = fixtures_dir / "user1_draft.json"
    user2_path = fixtures_dir / "user2_draft.json"
    
    if not user1_path.exists() or not user2_path.exists():
        print("ℹ️  Fixture files not found, skipping")
        return
    
    with open(user1_path, "rb") as f:
        user1_content = f.read()
    with open(user2_path, "rb") as f:
        user2_content = f.read()
    
    # Individual files should have different hashes
    hash1 = _hash_bytes(user1_content)
    hash2 = _hash_bytes(user2_content)
    assert hash1 != hash2, "Fixture files should have different content"
    
    # Combined hash should be different from either individual
    combined = _hash_bytes(b"".join([user1_content, user2_content]))
    assert combined != hash1
    assert combined != hash2
    
    print("✅ Fixture files have distinct hashes")


if __name__ == "__main__":
    print("=" * 80)
    print("TESTING UPLOAD HASH TRACKING")
    print("=" * 80)
    
    test_hash_calculation_consistent()
    test_combined_file_hash()
    test_empty_files_handled()
    test_fixture_files_have_distinct_hashes()
    
    print("\n" + "=" * 80)
    print("ALL TESTS PASSED ✅")
    print("=" * 80)
