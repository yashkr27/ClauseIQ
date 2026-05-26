"""
Regex-based fallback chunker.

Finds clause boundaries via pattern matching on numbered headings,
article markers, schedule labels, and uppercase section titles.
Used when Gemini is unavailable or returns bad JSON.

Public interface:
    regex_chunk(extraction: ExtractionResult) -> list[Clause]
"""

import re

from ..extraction.extractor import ExtractionResult
from ..models.schemas import Clause, ClauseType
from .helpers import detect_type, is_boilerplate, split_oversized


# ──────────────────────────────────────────────────────────────────────────────
# BOUNDARY PATTERNS
# ──────────────────────────────────────────────────────────────────────────────

_BOUNDARY_PATTERNS = [
    re.compile(r'^[ \t]*(\d+(?:\([a-zA-Z0-9]+\))+)\.?\s+([^\n]{3,80})', re.MULTILINE),
    re.compile(r'^[ \t]*(\d+[A-Z])\.?\s+([^\n]{3,80})',                  re.MULTILINE),
    re.compile(r'^[ \t]*(\d+\.\d+)\.?\s+([A-Z][A-Za-z\s&,\-/]{2,80})',  re.MULTILINE),
    re.compile(r'^[ \t]*(\d+)\.\s+([^\n]{3,80})',                        re.MULTILINE),
    re.compile(r'^[ \t]*(Article\s+[IVXLC]+)\.?\s+([^\n]{3,100})',       re.MULTILINE),
    re.compile(r'^[ \t]*(SCHEDULE\s+[A-Z0-9]+|ANNEXURE\s+[A-Z0-9]+)\s*$', re.MULTILINE),
    re.compile(r'^[ \t]*([A-Z][A-Z\s&\-]{3,60})[ \t]*$',                re.MULTILINE),
]

_UPPERCASE_BLACKLIST = {
    "EMPLOYMENT AGREEMENT", "SHARE PURCHASE AGREEMENT", "NON DISCLOSURE AGREEMENT",
    "NON-DISCLOSURE AGREEMENT", "THIS AGREEMENT", "AGREEMENT", "WITNESSETH",
    "NOW THEREFORE", "RECITALS", "BY AND BETWEEN", "WHEREAS", "AND", "OR",
    "IN WITNESS WHEREOF",
}


# ──────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _valid_uppercase(title: str) -> bool:
    t = title.strip()
    if t.upper() in _UPPERCASE_BLACKLIST:
        return False
    if any(p in t.upper() for p in ("BETWEEN", "WHEREAS", "THEREFORE", "WITNESS")):
        return False
    return len(t.split()) <= 4


def _normalise_number(raw: str) -> str:
    n = raw.strip().rstrip('.')
    return n.split('.')[0] if re.match(r'^\d+\.0$', n) else n


def _parent_number(clause_num: str) -> str:
    """Return the parent clause number, e.g. '3.1' -> '3', '3' -> ''."""
    parts = clause_num.rsplit('.', 1)
    return parts[0] if len(parts) > 1 else ''


def _clean_title(number: str, raw: str) -> str:
    t = raw.strip()
    if len(t.split()) > 8 or t.endswith('.'):
        return f"Clause {number}" if number else "Clause"
    return t if len(t) <= 60 else (f"Clause {number}" if number else "Clause")


def _is_garbage(text: str, number: str, title: str) -> bool:
    if re.match(r'^\d{4,}$', number):                                    return True
    if len(text.strip()) < 30:                                           return True
    if title.upper() in ('TITLE', 'NAME', 'BY', 'DATE', 'SIGNATURE'):   return True
    if is_boilerplate(title, text):                                      return True
    return False


def _page_from_offset(offset: int, page_texts: list) -> int | None:
    for pt in page_texts:
        if pt["char_start"] <= offset < pt["char_end"]:
            return pt["page"]
    return None


def _preprocess(text: str) -> str:
    text = re.sub(r'(\d)\s*\n\s*(\d\.)', r'\1\2', text)
    text = re.sub(r'([a-zA-Z\.\)])\s+(\d{1,2}\.)\s+', r'\1\n\2 ', text)
    text = re.sub(r'(?<!\n)(\d{1,2}\.\t)', r'\n\1', text)
    return text


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC: REGEX CHUNK
# ──────────────────────────────────────────────────────────────────────────────

def regex_chunk(extraction: ExtractionResult) -> list[Clause]:
    """
    Regex boundary chunker.  Finds clause boundaries via pattern matching,
    groups sub-clauses, filters garbage, and builds Clause objects.
    """
    text       = _preprocess(extraction.text)
    page_texts = extraction.page_texts

    # ── Find boundaries ───────────────────────────────────────────────────────
    boundaries = []
    seen       = set()

    for pat in _BOUNDARY_PATTERNS:
        for m in pat.finditer(text):
            key = (m.start(), m.group(0)[:20])
            if key in seen:
                continue
            seen.add(key)

            groups = m.groups()
            if len(groups) == 2:
                raw_num, title = groups
                end_heading    = m.start(2)
            else:
                raw_num, title = '', groups[0]
                if not _valid_uppercase(title):
                    continue
                nl  = text.find('\n', m.start())
                end_heading = nl + 1 if nl != -1 else m.end()

            boundaries.append({
                'number':         _normalise_number(raw_num.strip()) if raw_num.strip() else '',
                'title':          title.strip(),
                'start':          m.start(),
                'end_of_heading': end_heading,
            })

    boundaries.sort(key=lambda b: b['start'])

    # ── No boundaries found: paragraph fallback ──────────────────────────────
    if not boundaries:
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n+', text) if len(p.strip()) >= 30]
        clauses    = []
        for idx, para in enumerate(paragraphs):
            num = f"AUTO-{idx+1}"
            clauses.append(Clause(
                chunk_index=idx, clause_number=num,
                clause_title=f"Clause {idx+1}",
                clause_type=detect_type('', para),
                text=para, page_number=None,
            ))
        return clauses or [Clause(
            chunk_index=0, clause_number='AUTO-1',
            clause_title='Full Document',
            clause_type=ClauseType.general,
            text=text.strip(), page_number=None,
        )]

    # ── Extract raw chunks ───────────────────────────────────────────────────
    raw_chunks  = []
    chunk_index = 0

    for idx, b in enumerate(boundaries):
        start = b['end_of_heading']
        end   = boundaries[idx+1]['start'] if idx+1 < len(boundaries) else len(text)
        body  = text[start:end].strip()
        page  = _page_from_offset(b['start'], page_texts)

        for piece_idx, piece in enumerate(split_oversized(body)):
            num = b['number']
            if piece_idx > 0:
                num = f"{num}.{piece_idx}" if num else f"AUTO-{idx+1}.{piece_idx}"
            if not _is_garbage(piece, num, b['title']):
                raw_chunks.append({
                    'number': num,
                    'title':  _clean_title(b['number'], b['title']),
                    'text':   piece,
                    'page':   page,
                })

    # ── Group sub-clauses under parents ──────────────────────────────────────
    grouped = []
    i = 0
    while i < len(raw_chunks):
        c   = raw_chunks[i]
        num = c["number"]
        if not re.match(r'^\d+$', num):
            grouped.append(c); i += 1; continue
        combined = c["text"]
        j = i + 1
        while j < len(raw_chunks):
            nxt = raw_chunks[j]
            if not nxt["number"].startswith(num + ".") or len(combined) > 1200:
                break
            combined += "\n\n" + nxt["title"] + "\n" + nxt["text"]
            j += 1
        grouped.append({**c, "text": combined})
        i = j if j > i + 1 else i + 1

    # ── Build Clause objects ─────────────────────────────────────────────────
    clauses = []
    for idx, c in enumerate(grouped):
        num = c['number'] if c['number'] else f"AUTO-{idx+1}"
        clauses.append(Clause(
            chunk_index=idx,
            clause_number=num,
            clause_title=c['title'],
            clause_type=detect_type(c['title'], c['text']),
            text=c['text'],
            page_number=c.get('page'),
        ))

    return clauses
