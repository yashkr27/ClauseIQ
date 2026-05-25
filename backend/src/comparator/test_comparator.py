"""
Tests for Layer 3 — Comparator
Run from backend/: python -m pytest src/comparator/test_comparator.py -v
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.comparator.comparator import compare, _normalise_heading, _word_diff
from src.models.schemas import Clause, ClauseType, MatchType

def _clause(num, title, text, idx=0):
    return Clause(
        chunk_index=idx,
        clause_number=num,
        clause_title=title,
        clause_type=ClauseType.general,
        text=text
    )


# ── CP4 — heading normalisation (no hardcoding) ───────────────────────────────

def test_normalise_strips_prefix():
    assert _normalise_heading('Section 3') == '3'
    assert _normalise_heading('Clause 3.') == '3'
    assert _normalise_heading('3.0')       == '3'
    assert _normalise_heading('3.1')       == '3.1'


# ── CP3 — word diff ───────────────────────────────────────────────────────────

def test_word_diff_detects_change():
    diff = _word_diff("liability is unlimited", "liability is capped at 2x")
    types = [d['type'] for d in diff]
    assert 'remove' in types
    assert 'add' in types

def test_word_diff_equal_texts():
    diff = _word_diff("same text here", "same text here")
    assert all(d['type'] == 'equal' for d in diff)


# ── CP1, CP2 — matching ───────────────────────────────────────────────────────

def test_unchanged_identical_clauses():
    c = _clause('1', 'Definitions', 'Confidential information means any data shared.')
    results = compare([c], [c])
    assert results[0].match_type == MatchType.UNCHANGED

def test_modified_changed_clause():
    c1 = _clause('5', 'Liability', 'liability is unlimited for any breach')
    c2 = _clause('5', 'Liability', 'liability is capped at two times annual contract value')
    results = compare([c1], [c2])
    assert results[0].match_type == MatchType.MODIFIED
    assert results[0].diff_text is not None, "CP3: diff_text must never be None for MODIFIED"

def test_added_clause():
    c1 = _clause('1', 'Definitions', 'Definitions text.')
    c2_existing = _clause('1', 'Definitions', 'Definitions text.')
    c2_new = _clause('11', 'Antitrust', 'Antitrust compliance required.')
    results = compare([c1], [c2_existing, c2_new])
    types = [r.match_type for r in results]
    assert MatchType.ADDED in types

def test_removed_clause():
    c1_existing = _clause('1', 'Definitions', 'Definitions text.')
    c1_removed  = _clause('8', 'Breach Notice', 'Notify within 24 hours.')
    c2 = _clause('1', 'Definitions', 'Definitions text.')
    results = compare([c1_existing, c1_removed], [c2])
    types = [r.match_type for r in results]
    assert MatchType.REMOVED in types


# ── CP1 — semantic match (the key NDA test case) ──────────────────────────────

def test_semantic_match_renumbered_clause():
    """
    v1 Section 3 (Standstill) = v2 Section 9.0 — different numbers, same content.
    L1 heading match fails. L2 TF-IDF must catch it as MODIFIED not REMOVED+ADDED.
    Rule CP1: L2 always runs on unmatched clauses.
    """
    standstill_text = (
        "Each party agrees that it will not acquire securities or assets of the other "
        "party without prior written approval during the standstill period of one year."
    )
    c1 = _clause('3',   'Standstill', standstill_text)
    c2 = _clause('9.0', 'Stand-Still', standstill_text + " This provision applies to affiliates.")
    results = compare([c1], [c2])
    match_types = [r.match_type for r in results]
    # Should be MODIFIED (semantically matched), not REMOVED + ADDED
    assert MatchType.MODIFIED in match_types, (
        "CP1 FAIL: semantic match missed renumbered clause. "
        "v1 §3 Standstill must match v2 §9.0 Stand-Still via TF-IDF."
    )


# ── T2 — integration: known NDA differences must be found ─────────────────────

def test_nda_comparison_finds_changes():
    from src.extraction.extractor import extract
    from src.chunker.chunker import chunk
    TEST_DATA = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'test-data')
    v1_clauses = chunk(extract(os.path.join(TEST_DATA, 'ndav1.pdf')))
    v2_clauses = chunk(extract(os.path.join(TEST_DATA, 'ndav2.pdf')))
    results = compare(v1_clauses, v2_clauses)
    added   = [r for r in results if r.match_type == MatchType.ADDED]
    modified = [r for r in results if r.match_type == MatchType.MODIFIED]
    # From T2: must find added clauses (Antitrust, Attorney-Client Privilege, Survival)
    assert len(added) >= 2,    f"Expected >=2 ADDED clauses, got {len(added)}"
    assert len(modified) >= 2, f"Expected >=2 MODIFIED clauses, got {len(modified)}"


def test_split_clause_not_reported_as_added():
    old = _clause(
        '8',
        'Indemnification',
        'Seller shall indemnify Buyer for direct losses, third party claims, defense costs, and settlement amounts arising from breach.'
    )
    new_direct = _clause(
        '8',
        'Direct Indemnity',
        'Seller shall indemnify Buyer for direct losses and defense costs arising from breach.'
    )
    new_third_party = _clause(
        '8A',
        'Third Party Claims',
        'Seller shall indemnify Buyer for third party claims, defense costs, and settlement amounts arising from breach.'
    )

    results = compare([old], [new_direct, new_third_party])
    split_rows = [r for r in results if r.clause_number_v1 == '8' and r.clause_number_v2 == '8A']
    added_8a = [r for r in results if r.match_type == MatchType.ADDED and r.clause_number_v2 == '8A']

    assert split_rows, "Split clause 8A should remain linked to original clause 8"
    assert not added_8a, "Split clause 8A should not be reported as a brand-new addition"
