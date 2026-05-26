"""
Chunker helpers — shared utilities for both Gemini and regex chunking paths.

Provides:
    - Clause type detection (keyword-based + safe enum conversion)
    - Boilerplate filtering (watermarks, preamble, signature blocks)
    - Oversized chunk splitting (paragraph-boundary aware)
"""

import re
from ..models.schemas import ClauseType

MAX_CHUNK_CHARS = 2000   # split threshold


# ──────────────────────────────────────────────────────────────────────────────
# CLAUSE TYPE DETECTION
# ──────────────────────────────────────────────────────────────────────────────

_VALID_TYPES = {t.value for t in ClauseType}

_TYPE_KEYWORDS = [
    (ClauseType.definition,      ['definition', 'means ', 'defined term']),
    (ClauseType.limitation,      ['limitation', 'liability', 'cap ', 'no liability']),
    (ClauseType.termination,     ['terminat', 'expir', 'cancel', 'end of term']),
    (ClauseType.indemnity,       ['indemnif', 'hold harmless', 'defend ']),
    (ClauseType.ip,              ['intellectual property', 'patent', 'copyright', ' ip ']),
    (ClauseType.confidentiality, ['confidential', 'non-disclosure', 'nda', 'secret']),
    (ClauseType.obligation,      ['shall ', 'must ', 'agrees to', 'will ', 'undertakes']),
]


def detect_type(title: str, text_sample: str) -> ClauseType:
    """Keyword-based clause type detection from title + first 200 chars of text."""
    haystack = (title + ' ' + text_sample[:200]).lower()
    for clause_type, keywords in _TYPE_KEYWORDS:
        if any(kw in haystack for kw in keywords):
            return clause_type
    return ClauseType.general


def safe_type(raw: str) -> ClauseType:
    """Convert a raw string to ClauseType, falling back to general."""
    return ClauseType(raw) if raw in _VALID_TYPES else ClauseType.general


# ──────────────────────────────────────────────────────────────────────────────
# BOILERPLATE FILTER
# ──────────────────────────────────────────────────────────────────────────────

_BOILERPLATE_TITLE_PATTERNS = [
    re.compile(r'lawyered',                   re.IGNORECASE),
    re.compile(r'template',                   re.IGNORECASE),
    re.compile(r'authored by',                re.IGNORECASE),
]

_BOILERPLATE_TEXT_PREFIXES = [
    'this template is authored',
    'in case of any queries',
    'in witness whereof',
    'by and between',
]


def is_boilerplate(title: str, text: str) -> bool:
    """
    Returns True for chunks that are watermarks, preamble, or signature blocks.
    Runs as a post-process on Gemini output — catches anything the cleaner missed.
    """
    title_lower = title.lower().strip()
    text_lower  = text.lower().strip()

    # Known watermark titles
    if any(p.search(title_lower) for p in _BOILERPLATE_TITLE_PATTERNS):
        return True

    # Text that starts with known boilerplate phrases
    if any(text_lower.startswith(p) for p in _BOILERPLATE_TEXT_PREFIXES):
        return True

    # Signature block: text is mostly a markdown table with no real legal content
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if lines and all(l.startswith('|') for l in lines):
        return True

    # Too short to be a real clause (cleaner may have removed most of it)
    if len(text.strip()) < 30:
        return True

    return False


# ──────────────────────────────────────────────────────────────────────────────
# OVERSIZED CHUNK SPLITTER
# ──────────────────────────────────────────────────────────────────────────────

def split_oversized(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """
    Split a chunk that is too large into 2-3 pieces on paragraph boundaries.
    Never produces more than 3 pieces (evaluators read these — keep them coherent).
    """
    if len(text) <= max_chars:
        return [text]

    paragraphs = [p.strip() for p in re.split(r'\n\s*\n+', text) if p.strip()]

    if len(paragraphs) <= 1:
        mid = len(text) // 2
        return [text[:mid].strip(), text[mid:].strip()]

    target  = len(text) / min(3, max(2, len(text) // max_chars + 1))
    pieces  = []
    current = ""

    for para in paragraphs:
        if current and len(current) >= target and len(pieces) < 2:
            pieces.append(current.strip())
            current = para
        else:
            current = (current + "\n\n" + para).strip() if current else para

    if current:
        pieces.append(current.strip())

    return pieces or [text]
