"""
Tests for Layer 2 — Chunker
Run from backend/: python -m pytest src/chunker/test_chunker.py -v
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.extraction.extractor import ExtractionResult
from src.chunker.chunker import chunk, _normalise_number, _parent_number, _detect_type
from src.models.schemas import ClauseType

def _make_extraction(text: str) -> ExtractionResult:
    return ExtractionResult(text=text, headings=[], file_type='docx', pages=1)


# ── C2 — number normalisation ─────────────────────────────────────────────────

def test_normalise_integer():        assert _normalise_number('1')   == '1'
def test_normalise_dot():            assert _normalise_number('1.')  == '1'
def test_normalise_decimal_zero():   assert _normalise_number('1.0') == '1'
def test_normalise_sub_clause():     assert _normalise_number('3.1') == '3.1'
def test_normalise_sub_dot():        assert _normalise_number('3.1.') == '3.1'
def test_parent_of_sub():            assert _parent_number('3.1') == '3'
def test_parent_of_top():            assert _parent_number('3') == ''


# ── C1 — legal-aware splitting ────────────────────────────────────────────────

def test_splits_on_numbered_headings():
    text = "1. Definitions\n\nDef text here.\n\n2. Obligations\n\nObligation text here."
    clauses = chunk(_make_extraction(text))
    assert len(clauses) >= 2

def test_does_not_split_on_paragraph():
    text = "1. Definitions\n\nFirst paragraph.\n\nSecond paragraph still in clause 1."
    clauses = chunk(_make_extraction(text))
    assert len(clauses) == 1, "Paragraph breaks must NOT create new clauses (C1)"

def test_splits_uppercase_title():
    text = "BACKGROUND\n\nBackground text.\n\nOPERATIVE TERMS\n\nTerms text."
    clauses = chunk(_make_extraction(text))
    assert len(clauses) >= 2


# ── C3 — sub-clause grouping ──────────────────────────────────────────────────

def test_sub_clauses_grouped_under_parent():
    text = ("3. Confidentiality\n\nMain obligation.\n\n"
            "3.1 Scope\n\nSub-clause scope text.\n\n"
            "3.2 Exceptions\n\nSub-clause exceptions.\n\n"
            "4. Term\n\nTerm text.")
    clauses = chunk(_make_extraction(text))
    clause_numbers = [c.clause_number for c in clauses]
    # 3.1 and 3.2 should be absorbed into 3, leaving just "3" and "4"
    assert '3.1' not in clause_numbers, "Sub-clauses should be grouped into parent (C3)"
    assert '3' in clause_numbers


# ── C4 — type tagging ─────────────────────────────────────────────────────────

def test_tags_confidentiality():
    assert _detect_type('Confidentiality', '') == ClauseType.confidentiality

def test_tags_definition():
    assert _detect_type('Definitions', '"means" any information') == ClauseType.definition

def test_tags_termination():
    assert _detect_type('Termination', 'This agreement shall terminate') == ClauseType.termination

def test_tags_indemnity():
    assert _detect_type('Indemnification', 'shall indemnify and hold harmless') == ClauseType.indemnity

def test_tags_general_fallback():
    assert _detect_type('Miscellaneous', 'Various general provisions apply.') == ClauseType.general


# ── Integration — run on actual NDAs ──────────────────────────────────────────

def test_v1_produces_multiple_clauses():
    from src.extraction.extractor import extract
    TEST_DATA = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'test-data')
    result = extract(os.path.join(TEST_DATA, 'ndav1.pdf'))
    clauses = chunk(result)
    assert len(clauses) >= 5, f"Expected >=5 clauses from ndav1, got {len(clauses)}"

def test_v2_produces_multiple_clauses():
    from src.extraction.extractor import extract
    TEST_DATA = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'test-data')
    result = extract(os.path.join(TEST_DATA, 'ndav2.pdf'))
    clauses = chunk(result)
    assert len(clauses) >= 5, f"Expected >=5 clauses from ndav2, got {len(clauses)}"

def test_all_clauses_have_type():
    text = "1. Definitions\n\nText.\n\n2. Obligations\n\nText.\n\n3. Term\n\nText."
    for c in chunk(_make_extraction(text)):
        assert c.clause_type in list(ClauseType), f"Missing type on clause {c.clause_number}"
