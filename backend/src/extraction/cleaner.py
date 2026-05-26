"""
Layer 1.5 — Markdown Cleaner
Sits between extractor and chunker.

Pipeline:
    extract() → clean() → chunk()

Strips from LlamaParse markdown:
  - Template/platform watermark lines  ("This template is authored by...")
  - Ad/CTA lines                       ("In case of any queries...")
  - Page footer lines                  ("Page 1 of 6", "1/6")
  - Signature block tables             (markdown tables with Name/Signature rows)
  - Preamble boilerplate               (WHEREAS, BY AND BETWEEN, IN WITNESS WHEREOF)

Preserves:
  - <!-- PAGE N --> markers            (page index must survive for Gemini)
  - All numbered clause text
  - Headings (# Title)
"""

import re
from dataclasses import replace
from ..extraction.extractor import ExtractionResult


# ── Line-level patterns to drop entirely ─────────────────────────────────────

_DROP_LINE_PATTERNS = [
    # Platform watermarks
    re.compile(r'this template is authored by', re.IGNORECASE),
    re.compile(r'in collaboration with lawyered', re.IGNORECASE),
    re.compile(r'lakshmikumaran.*sridharan', re.IGNORECASE),

    # Ad / CTA lines
    re.compile(r'in case of any queries', re.IGNORECASE),
    re.compile(r'book a free consultation', re.IGNORECASE),
    re.compile(r'customization requirements', re.IGNORECASE),

    # Page footers  ("Page 1 of 6", "Page 1 of 6 ", "1/6")
    re.compile(r'^page\s+\d+\s+of\s+\d+', re.IGNORECASE),
    re.compile(r'^\d+\s*/\s*\d+\s*$'),

    # Timestamp / URL noise (carried over from extractor fallback)
    re.compile(r'^\d{1,2}/\d{1,2}/\d{2,4},\s+\d{1,2}:\d{2}\s+(AM|PM)'),
    re.compile(r'^https?://'),
]


# ── Block-level patterns to drop (multi-line sections) ───────────────────────

_DROP_BLOCK_PATTERNS = [
    # Signature tables: markdown table rows containing Name / Signature / Date
    re.compile(
        r'\|.*(?:signature|name|designation|place|date).*\|.*\n'
        r'(?:\|.*\|.*\n)+',
        re.IGNORECASE
    ),

    # Preamble boilerplate blocks
    # "BY AND BETWEEN ... OF THE ONE PART"
    re.compile(
        r'(?:^|\n)#?\s*BY AND BETWEEN\b.+?(?=\n#|\n\d+\.|\Z)',
        re.IGNORECASE | re.DOTALL
    ),

    # "IN WITNESS WHEREOF ..." to end of document
    re.compile(
        r'(?:^|\n)IN WITNESS WHEREOF\b.+?\Z',
        re.IGNORECASE | re.DOTALL
    ),

    # "WHEREAS ... IN CONNECTION WITH THE ABOVE" preamble block
    re.compile(
        r'(?:^|\n)WHEREAS\b.+?(?=IN CONNECTION WITH THE ABOVE|(?:\n\n\d+\.)|\Z)',
        re.IGNORECASE | re.DOTALL
    ),
]


# ── Heading-only lines that are pure boilerplate (not real clause headings) ──

_BOILERPLATE_HEADINGS = {
    'NON-DISCLOSURE AGREEMENT',
    'NON DISCLOSURE AGREEMENT',
    'CONFIDENTIALITY AGREEMENT',
    'THIS AGREEMENT',
    'AGREEMENT',
    'BY AND BETWEEN',
    'AND',
    'OR',
    'RECITALS',
    'WITNESSETH',
    'NOW THEREFORE',
    'IN WITNESS WHEREOF',
}


def _drop_boilerplate_headings(text: str) -> str:
    """Remove markdown headings (# Title) that are pure boilerplate."""
    lines  = text.splitlines()
    output = []
    for line in lines:
        stripped = line.strip()
        # Match "# TITLE" or "## TITLE"
        heading_match = re.match(r'^#{1,3}\s+(.+)$', stripped)
        if heading_match:
            heading_text = heading_match.group(1).strip().upper()
            if heading_text in _BOILERPLATE_HEADINGS:
                continue   # drop this line
        output.append(line)
    return '\n'.join(output)


def _drop_lines(text: str) -> str:
    """Remove individual lines matching drop patterns."""
    lines  = text.splitlines()
    output = []
    for line in lines:
        # Always preserve page markers
        if re.match(r'^\s*<!--\s*PAGE\s+\d+\s*-->', line):
            output.append(line)
            continue
        if any(p.search(line) for p in _DROP_LINE_PATTERNS):
            continue
        output.append(line)
    return '\n'.join(output)


def _drop_blocks(text: str) -> str:
    """Remove multi-line boilerplate blocks."""
    for pattern in _DROP_BLOCK_PATTERNS:
        text = pattern.sub('', text)
    return text


def _collapse_whitespace(text: str) -> str:
    """Collapse 3+ blank lines to 2, strip leading/trailing whitespace."""
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── Public interface ──────────────────────────────────────────────────────────

def clean(extraction: ExtractionResult) -> ExtractionResult:
    """
    Returns a new ExtractionResult with cleaned markdown.
    All other fields (file_type, pages, page_texts, headings) are unchanged.

    Usage:
        extraction = extract(file_path)
        extraction = clean(extraction)       # ← add this line
        clauses    = chunk(extraction)
    """
    text = extraction.markdown

    text = _drop_blocks(text)
    text = _drop_lines(text)
    text = _drop_boilerplate_headings(text)
    text = _collapse_whitespace(text)

    return replace(extraction, text=text, markdown=text)