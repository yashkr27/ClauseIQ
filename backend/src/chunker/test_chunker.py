"""
Tests for Layer 2 — Chunker
Run from backend/: python -m pytest src/chunker/test_chunker.py -v
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.extraction.extractor import ExtractionResult
from src.chunker.chunker import chunk, _normalise_number, _parent_number, _detect_type, _is_garbage, _clean_title
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
    text = ("1. Definitions\n\n" + "Definition clause body text that is long enough to pass the minimum length filter. " + "\n\n"
            "2. Obligations\n\n" + "Obligation clause body text that is also long enough to pass the minimum length filter.")
    clauses = chunk(_make_extraction(text))
    assert len(clauses) >= 2

def test_does_not_split_on_paragraph():
    text = ("1. Definitions\n\nFirst paragraph of clause one with enough text to be valid. "
            "\n\nSecond paragraph still in clause one with more padding to be well over eighty characters total.")
    clauses = chunk(_make_extraction(text))
    assert len(clauses) == 1, "Paragraph breaks must NOT create new clauses (C1)"

def test_splits_uppercase_title():
    text = ("BACKGROUND\n\n" + "Background information text that is long enough to pass the garbage filter minimum. " + "\n\n"
            "OPERATIVE TERMS\n\n" + "Operative terms body text that is also long enough to pass the garbage filter here.")
    clauses = chunk(_make_extraction(text))
    assert len(clauses) >= 2


# ── C3 — sub-clause grouping ──────────────────────────────────────────────────

def test_sub_clauses_grouped_under_parent():
    text = ("3. Confidentiality\n\nMain obligation text that is long enough to pass the garbage filter here. "
            "\n\n3.1 Scope\n\nSub-clause scope text with enough padding to pass the minimum length filter. "
            "\n\n3.2 Exceptions\n\nSub-clause exceptions with enough padding to pass the minimum length filter. "
            "\n\n4. Term\n\nTerm text body that is long enough to pass the garbage filter for minimum length.")
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
    text = ("1. Definitions\n\n" + "Definition body text long enough to pass garbage filter minimum length. " * 2 + "\n\n"
            "2. Obligations\n\n" + "Obligation body text long enough to pass garbage filter minimum length. " * 2 + "\n\n"
            "3. Term\n\n" + "Term body text that is also long enough to pass the garbage filter minimum. " * 2)
    for c in chunk(_make_extraction(text)):
        assert c.clause_type in list(ClauseType), f"Missing type on clause {c.clause_number}"


# ── Fix 2 — garbage chunk filter ──────────────────────────────────────────────

def test_garbage_address_number():
    assert _is_garbage({'number': '1530', 'title': 'Shields Drive', 'text': 'a' * 100}) is True

def test_garbage_short_text():
    assert _is_garbage({'number': '1', 'title': 'Some Title', 'text': 'Short.'}) is True

def test_garbage_signature_title():
    assert _is_garbage({'number': '', 'title': 'TITLE', 'text': 'a' * 100}) is True
    assert _is_garbage({'number': '', 'title': 'NAME', 'text': 'a' * 100}) is True
    assert _is_garbage({'number': '', 'title': 'BY', 'text': 'a' * 100}) is True

def test_garbage_single_short_uppercase():
    assert _is_garbage({'number': '', 'title': 'ABC', 'text': 'a' * 100}) is True

def test_not_garbage_real_clause():
    assert _is_garbage({'number': '1', 'title': 'Definitions', 'text': 'a' * 100}) is False

def test_garbage_filtered_in_pipeline():
    """Street address chunks should be removed from final output."""
    text = ("1. Definitions\n\n" + "Def text. " * 20 + "\n\n"
            "1530 Shields Drive\n\nSome address line continues here to be long enough." + " pad" * 20 + "\n\n"
            "2. Obligations\n\n" + "Obligation text. " * 20)
    clauses = chunk(_make_extraction(text))
    clause_numbers = [c.clause_number for c in clauses]
    assert '1530' not in clause_numbers, "Address chunk should be filtered out"


# ── Fix 1 — title cleanup ────────────────────────────────────────────────────

def test_clean_title_short_heading():
    assert _clean_title('1', 'Definitions') == 'Definitions'

def test_clean_title_long_body_text():
    long = 'Each Party in its capacity as a Disclosing Party agrees to the following obligations set forth herein'
    assert _clean_title('2', long) == 'Clause 2'

def test_clean_title_trailing_conjunction():
    assert _clean_title('5', 'Obligations of the') == 'Clause 5'

def test_clean_title_no_number_fallback():
    long = 'This is a very long title that is definitely more than sixty characters in total length'
    result = _clean_title('', long)
    assert result.endswith('…')
    assert len(result.split()) <= 6  # 5 words + ellipsis
