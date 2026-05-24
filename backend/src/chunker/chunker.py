"""
Layer 2 — Legal-aware Chunker
Rules satisfied: A2, C1, C2, C3, C4

Input:  ExtractionResult (from Layer 1)
Output: list[Clause]  (Pydantic model from models/schemas.py)
"""

import re
from ..extraction.extractor import ExtractionResult
from ..models.schemas import Clause, ClauseType


# ── boundary patterns (C1) ────────────────────────────────────────────────────
# These are the ONLY valid split points. No paragraph splitting. No token limits.
# Added optional leading whitespace support [ \t]* for robustness.

_BOUNDARY_PATTERNS = [
    re.compile(r'^[ \t]*(\d+\.\d+)\.?\s+([A-Z][^\n]{0,200})$', re.MULTILINE),   # decimal sub
    re.compile(r'^[ \t]*(\d+)\.?\s+([A-Z][^\n]{0,200})$', re.MULTILINE),         # integer
    re.compile(r'^[ \t]*([A-Z]{4,}(?:\s+[A-Z]+){0,6})\s*$', re.MULTILINE),      # UPPERCASE
    re.compile(r'^[ \t]*(SCHEDULE\s+[A-Z0-9]+|ANNEXURE\s+[A-Z0-9]+)\s*$', re.MULTILINE),
]


# ── number normalisation (C2) ─────────────────────────────────────────────────

def _normalise_number(raw: str) -> str:
    """
    "1" → "1",  "1." → "1",  "1.0" → "1",  "3.1" → "3.1",  "3.1." → "3.1"
    Strips trailing dots. Strips .0 suffix from top-level decimals.
    """
    n = raw.strip().rstrip('.')
    # "1.0" → "1", but "3.1" → "3.1" (genuine sub-clause)
    if re.match(r'^\d+\.0$', n):
        n = n.split('.')[0]
    return n

def _parent_number(normalised: str) -> str:
    """"3.1" → "3",  "3" → "" """
    parts = normalised.split('.')
    return parts[0] if len(parts) > 1 else ''


# ── clause type detection (C4) ────────────────────────────────────────────────
# Keyword heuristics only. No LLM calls here.

_TYPE_KEYWORDS: list[tuple[ClauseType, list[str]]] = [
    (ClauseType.definition,      ['definition', 'means ', 'defined term', '"means"']),
    (ClauseType.limitation,      ['limitation', 'liability', 'cap ', 'maximum liability', 'no liability']),
    (ClauseType.termination,     ['terminat', 'expir', 'cancel', 'end of term']),
    (ClauseType.indemnity,       ['indemnif', 'hold harmless', 'defend ']),
    (ClauseType.ip,              ['intellectual property', 'patent', 'copyright', ' ip ', 'proprietary']),
    (ClauseType.confidentiality, ['confidential', 'non-disclosure', 'nda', 'secret', 'proprietary information']),
    (ClauseType.obligation,      ['shall ', 'must ', 'agrees to', 'will ', 'undertakes']),
]

def _detect_type(title: str, text_sample: str) -> ClauseType:
    haystack = (title + ' ' + text_sample[:200]).lower()
    for clause_type, keywords in _TYPE_KEYWORDS:
        if any(kw in haystack for kw in keywords):
            return clause_type
    return ClauseType.general


# ── boundary finding ──────────────────────────────────────────────────────────

def _find_boundaries(text: str) -> list[dict]:
    """
    Find all clause boundary positions in text.
    Returns sorted list of {number, title, start, end_of_heading}.
    """
    boundaries = []
    seen = set()

    for pat in _BOUNDARY_PATTERNS:
        for m in pat.finditer(text):
            if m.start() in seen:
                continue
            seen.add(m.start())
            groups = m.groups()
            if len(groups) == 2:
                raw_num, title = groups
            else:
                raw_num, title = '', groups[0]
            boundaries.append({
                'raw_number':    raw_num.strip(),
                'number':        _normalise_number(raw_num.strip()) if raw_num.strip() else '',
                'title':         title.strip(),
                'start':         m.start(),
                'end_of_heading': m.end(),
            })

    boundaries.sort(key=lambda b: b['start'])
    return boundaries


# ── sub-clause grouping (C3) ──────────────────────────────────────────────────

def _group_sub_clauses(raw_chunks: list[dict]) -> list[dict]:
    """
    Groups sub-clauses (3.1, 3.2) into their parent (3) unless parent > 800 chars.
    Rule C3: never split mid-sentence or mid-definition.
    """
    grouped = []
    i = 0
    while i < len(raw_chunks):
        chunk = raw_chunks[i]
        parent_num = _parent_number(chunk['number'])

        if not parent_num:
            # Top-level clause — look ahead and absorb sub-clauses
            combined_text = chunk['text']
            j = i + 1
            while j < len(raw_chunks):
                next_chunk = raw_chunks[j]
                next_parent = _parent_number(next_chunk['number'])
                # Only group if the next chunk is actually a sub-clause (has a non-empty parent) and its parent matches this chunk's number
                if next_parent and next_parent == chunk['number']:
                    # This is a sub-clause of current
                    if len(combined_text) <= 800:
                        combined_text += '\n\n' + next_chunk['title'] + '\n' + next_chunk['text']
                        j += 1
                    else:
                        # Parent too long — keep sub-clauses separate (C3 exception)
                        break
                else:
                    break
            grouped.append({**chunk, 'text': combined_text})
            i = j
        else:
            # Sub-clause not yet absorbed (parent was > 800 chars)
            grouped.append(chunk)
            i += 1

    return grouped


# ── main chunker (C1) ─────────────────────────────────────────────────────────

def chunk(extraction: ExtractionResult) -> list[Clause]:
    """
    Layer 2 public interface.
    Input:  ExtractionResult from Layer 1
    Output: list[Clause] — each clause is a legal boundary unit
    Rule C1: only splits on legal clause boundaries, never generic splits.
    """
    text = extraction.text
    boundaries = _find_boundaries(text)

    if not boundaries:
        # No headings found — return entire text as one chunk (graceful degradation)
        return [Clause(
            chunk_index=0,
            clause_number='',
            clause_title='Full Document',
            clause_type=ClauseType.general,
            text=text.strip(),
        )]

    # Build raw chunks from boundary positions
    raw_chunks = []
    for idx, b in enumerate(boundaries):
        start = b['end_of_heading']
        end   = boundaries[idx + 1]['start'] if idx + 1 < len(boundaries) else len(text)
        body  = text[start:end].strip()
        raw_chunks.append({
            'number': b['number'],
            'title':  b['title'],
            'text':   body,
        })

    # Group sub-clauses under parents (C3)
    grouped = _group_sub_clauses(raw_chunks)

    # Build Clause objects with type tagging (C4)
    clauses = []
    for idx, c in enumerate(grouped):
        clauses.append(Clause(
            chunk_index=idx,
            clause_number=c['number'],
            clause_title=c['title'],
            clause_type=_detect_type(c['title'], c['text']),
            text=c['text'],
        ))

    return clauses
