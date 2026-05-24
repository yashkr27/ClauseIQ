"""
Tests for Layer 1 — Extraction
Run from backend/: python -m pytest src/extraction/test_extractor.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.extraction.extractor import extract, _strip_noise, _extract_headings

TEST_DATA = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'test-data')
NDA_V1    = os.path.join(TEST_DATA, 'ndav1.pdf')
NDA_V2    = os.path.join(TEST_DATA, 'ndav2.pdf')


# ── noise stripping (E3) ──────────────────────────────────────────────────────

def test_strips_timestamp_header():
    raw = "5/24/26, 12:21 AM Mutual Non-Disclosure Agreement\n\nActual content here."
    clean = _strip_noise(raw)
    assert '12:21 AM' not in clean
    assert 'Actual content here.' in clean

def test_strips_url_footer():
    raw = "Some clause text.\n\nhttps://www.sec.gov/Archives/edgar/data/123/abc.htm\n\nNext clause."
    clean = _strip_noise(raw)
    assert 'sec.gov' not in clean
    assert 'Some clause text.' in clean
    assert 'Next clause.' in clean

def test_strips_page_number():
    raw = "Some text.\n\nPage 3 of 6\n\nMore text."
    clean = _strip_noise(raw)
    assert 'Page 3 of 6' not in clean

def test_no_excessive_blank_lines():
    raw = "A\n\n\n\n\nB"
    clean = _strip_noise(raw)
    assert '\n\n\n' not in clean


# ── heading detection (E1, C2) ────────────────────────────────────────────────

def test_detects_integer_headings():
    text = "1. Definitions\n\nSome definition text here.\n\n2. Obligations\n\nObligation text."
    headings = _extract_headings(text)
    numbers = [h['number'] for h in headings]
    assert '1' in numbers
    assert '2' in numbers

def test_detects_decimal_headings():
    text = "1.0 DEFINITIONS\n\nSome text.\n\n3.1 Confidentiality\n\nMore text."
    headings = _extract_headings(text)
    numbers = [h['number'] for h in headings]
    assert '1.0' in numbers
    assert '3.1' in numbers

def test_detects_uppercase_titles():
    text = "BACKGROUND\n\nSome background text.\n\nOPERATIVE TERMS\n\nTerms here."
    headings = _extract_headings(text)
    titles = [h['title'] for h in headings]
    assert any('BACKGROUND' in t for t in titles)

def test_headings_sorted_by_offset():
    text = "1. First\n\nText.\n\n2. Second\n\nMore text.\n\n3. Third\n\nEven more."
    headings = _extract_headings(text)
    offsets = [h['char_offset'] for h in headings]
    assert offsets == sorted(offsets)


# ── PDF extraction (A5, T1) ───────────────────────────────────────────────────

def test_pdf_v1_extracts_text():
    result = extract(NDA_V1)
    assert result.file_type == 'pdf'
    assert len(result.text) > 500, "Expected substantial text from ndav1.pdf"

def test_pdf_v1_no_noise():
    import re
    result = extract(NDA_V1)
    assert 'sec.gov' not in result.text, "URL noise should be stripped (E3)"
    # Check full timestamp pattern is gone, not just the substring "AM"
    timestamp_pattern = re.compile(r'\d{1,2}/\d{1,2}/\d{2,4},\s+\d{1,2}:\d{2}\s+(AM|PM)')
    assert not timestamp_pattern.search(result.text), "Timestamp noise should be stripped (E3)"

def test_pdf_v1_has_headings():
    result = extract(NDA_V1)
    assert len(result.headings) >= 5, (
        f"Expected >=5 headings from ndav1, got {len(result.headings)}: {result.headings}"
    )

def test_pdf_v2_extracts_text():
    result = extract(NDA_V2)
    assert result.file_type == 'pdf'
    assert len(result.text) > 500

def test_pdf_v2_has_decimal_headings():
    result = extract(NDA_V2)
    decimal_headings = [h for h in result.headings if '.' in h['number']]
    assert len(decimal_headings) >= 3, (
        f"Expected decimal headings (1.0, 3.1 etc) in ndav2, got: {result.headings}"
    )

def test_pdf_page_count():
    result = extract(NDA_V1)
    assert result.pages == 6, f"ndav1.pdf has 6 pages, got {result.pages}"

def test_result_interface():
    """E2: verify the output contract is exactly {text, headings, file_type, pages}"""
    result = extract(NDA_V1)
    assert hasattr(result, 'text')
    assert hasattr(result, 'headings')
    assert hasattr(result, 'file_type')
    assert hasattr(result, 'pages')
    assert isinstance(result.text, str)
    assert isinstance(result.headings, list)


# ── error handling ────────────────────────────────────────────────────────────

def test_missing_file_raises():
    try:
        extract('/tmp/does_not_exist.pdf')
        assert False, "Should have raised FileNotFoundError"
    except FileNotFoundError:
        pass

def test_unsupported_type_raises():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
        f.write(b'some text')
        tmp = f.name
    try:
        extract(tmp)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    finally:
        os.unlink(tmp)

# ── performance + robustness ──────────────────────────────────────────────────

def test_extraction_under_2_seconds():
    """Performance baseline: extraction should remain fast."""
    import time
    start = time.time()
    extract(NDA_V1)
    elapsed = time.time() - start
    assert elapsed < 2.0, f"Extraction too slow: {elapsed:.2f}s"


def test_detects_nested_subclauses():
    """Ensure nested legal numbering patterns are preserved."""
    text = """
    5(a)(i) Confidential Information
    Some text here.

    5(a)(ii) Exclusions
    More text here.

    5(b) Return of Materials
    Final text.
    """
    headings = _extract_headings(text)
    numbers = [h['number'] for h in headings]

    assert '5(a)(i)' in numbers
    assert '5(a)(ii)' in numbers
    assert '5(b)' in numbers


def test_normalization_stable():
    """Whitespace normalization should be deterministic."""
    raw = "Clause   1\n\n\n\nText"
    clean = _strip_noise(raw)

    assert '\n\n\n' not in clean
    assert 'Clause 1' in clean
    assert 'Text' in clean


def test_heading_order_integrity():
    """Headings must remain in original document order."""
    text = """
    1. Definitions
    Some text.

    3. Liability
    More text.

    2. Confidentiality
    Earlier-numbered clause appearing later intentionally.
    """

    headings = _extract_headings(text)
    offsets = [h['char_offset'] for h in headings]

    assert offsets == sorted(offsets)