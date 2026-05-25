"""
Layer 2 — Legal-aware Chunker
Rules satisfied: A2, C1, C2, C3, C4

HARDENED VERSION:
- safer uppercase heading detection
- oversized chunk protection
- improved numbered clause detection
- semantic heading fallback
- no empty clause numbers
- stronger fallback behavior
- prevents whole-document clause captures
"""

import re

from ..extraction.extractor import ExtractionResult
from ..models.schemas import Clause, ClauseType


# ──────────────────────────────────────────────────────────────────────────────
# LEGAL BOUNDARY PATTERNS
# ──────────────────────────────────────────────────────────────────────────────

_BOUNDARY_PATTERNS = [

    # 5(a)(i)
    re.compile(
        r'^[ \t]*(\d+(?:\([a-zA-Z0-9]+\))+)\.?\s+([^\n]{3,200})$',
        re.MULTILINE
    ),

    # 8A
    re.compile(
        r'^[ \t]*(\d+[A-Z])\.?\s+([^\n]{3,200})$',
        re.MULTILINE
    ),

    # 3.1
    re.compile(
        r'^[ \t]*(\d+\.\d+)\.?\s+([A-Z][A-Za-z\s&,\-/]{2,80})$',
        re.MULTILINE
    ),

    # 7
    re.compile(
        r'^[ \t]*(\d+)\.?\s+([A-Z][A-Za-z\s&,\-/]{2,80})$',
        re.MULTILINE
    ),

    # ARTICLE IV
    re.compile(
        r'^[ \t]*(Article\s+[IVXLC]+)\.?\s+([^\n]{3,100})$',
        re.MULTILINE
    ),

    # SCHEDULE A / ANNEXURE B
    re.compile(
        r'^[ \t]*(SCHEDULE\s+[A-Z0-9]+|ANNEXURE\s+[A-Z0-9]+)\s*$',
        re.MULTILINE
    ),

    # SAFER uppercase heading detector
    re.compile(
        r'^[ \t]*([A-Z][A-Z\s&\-]{3,60})[ \t]*$',
        re.MULTILINE
    ),
]


# ──────────────────────────────────────────────────────────────────────────────
# CLAUSE NUMBER NORMALISATION
# ──────────────────────────────────────────────────────────────────────────────

def _normalise_number(raw: str) -> str:
    """
    "1."   -> "1"
    "1.0"  -> "1"
    "3.1." -> "3.1"
    """

    n = raw.strip().rstrip('.')

    if re.match(r'^\d+\.0$', n):
        n = n.split('.')[0]

    return n


def _parent_number(normalised: str) -> str:
    """
    "3.1" -> "3"
    "3"   -> ""
    """

    if re.match(r'^\d+(?:\([a-zA-Z0-9]+\))+$', normalised):
        return re.match(r'^\d+', normalised).group(0)

    parts = normalised.split('.')

    return parts[0] if len(parts) > 1 else ''


# ──────────────────────────────────────────────────────────────────────────────
# CLAUSE TYPE DETECTION
# ──────────────────────────────────────────────────────────────────────────────

_TYPE_KEYWORDS = [

    (
        ClauseType.definition,
        ['definition', 'means ', 'defined term', '"means"']
    ),

    (
        ClauseType.limitation,
        ['limitation', 'liability', 'cap ', 'maximum liability', 'no liability']
    ),

    (
        ClauseType.termination,
        ['terminat', 'expir', 'cancel', 'end of term']
    ),

    (
        ClauseType.indemnity,
        ['indemnif', 'hold harmless', 'defend ']
    ),

    (
        ClauseType.ip,
        ['intellectual property', 'patent', 'copyright', ' ip ', 'proprietary']
    ),

    (
        ClauseType.confidentiality,
        ['confidential', 'non-disclosure', 'nda', 'secret']
    ),

    (
        ClauseType.obligation,
        ['shall ', 'must ', 'agrees to', 'will ', 'undertakes']
    ),
]


def _detect_type(title: str, text_sample: str) -> ClauseType:

    haystack = (title + ' ' + text_sample[:200]).lower()

    for clause_type, keywords in _TYPE_KEYWORDS:

        if any(kw in haystack for kw in keywords):
            return clause_type

    return ClauseType.general


# ──────────────────────────────────────────────────────────────────────────────
# UPPERCASE HEADING VALIDATION
# ──────────────────────────────────────────────────────────────────────────────

def _valid_uppercase_heading(title: str) -> bool:
    """
    Prevent giant document captures caused by generic uppercase lines.
    """

    t = title.strip()

    blacklist = {

        "EMPLOYMENT AGREEMENT",
        "SHARE PURCHASE AGREEMENT",
        "NON DISCLOSURE AGREEMENT",
        "NON-DISCLOSURE AGREEMENT",
        "THIS AGREEMENT",
        "AGREEMENT",
        "WITNESSETH",
        "NOW THEREFORE",
        "RECITALS",

        # NEW
        "BY AND BETWEEN",
        "WHEREAS",
        "AND",
        "OR",
        "IN WITNESS WHEREOF",
    }

    if t.upper() in blacklist:
        return False

    # reject connective/legal boilerplate phrases
    if any(
        phrase in t.upper()
        for phrase in (
            "BETWEEN",
            "WHEREAS",
            "THEREFORE",
            "WITNESS",
        )
    ):
        return False

    # too many words usually means body text
    if len(t.split()) > 4:
        return False

    return True

# ──────────────────────────────────────────────────────────────────────────────
# GARBAGE DETECTION
# ──────────────────────────────────────────────────────────────────────────────

def _is_garbage(c: dict) -> bool:

    num = c.get('number', '')
    title = c.get('title', '').strip()
    text = c.get('text', '').strip()

    # street/address numbers
    if re.match(r'^\d{4,}$', num):
        return True

    # too small
    if len(text) < 80:
        return True

    # signature boilerplate
    if title.upper() in (
        'TITLE',
        'NAME',
        'BY',
        'DATE',
        'SIGNATURE'
    ):
        return True

    return False


# ──────────────────────────────────────────────────────────────────────────────
# TITLE CLEANUP
# ──────────────────────────────────────────────────────────────────────────────

def _clean_title(number: str, raw_title: str) -> str:

    t = raw_title.strip()

    if (
        len(t) <= 60
        and not t.endswith((',', ' and', ' or', ' to', ' the'))
    ):
        return t

    if number:
        return f"Clause {number}"

    words = t.split()[:5]

    return ' '.join(words) + ('…' if len(t.split()) > 5 else '')


# ──────────────────────────────────────────────────────────────────────────────
# OVERSIZED CHUNK PROTECTION
# ──────────────────────────────────────────────────────────────────────────────

def _force_split_large_chunk(
    text: str,
    max_chars: int = 2200
) -> list[str]:

    """
    Emergency splitter for oversized chunks.
    Preserves paragraph boundaries.
    """

    if len(text) <= max_chars:
        return [text]

    paragraphs = [

        p.strip()

        for p in re.split(r'\n\s*\n+', text)

        if p.strip()
    ]

    chunks = []
    current = ""

    for para in paragraphs:

        if len(current) + len(para) < max_chars:

            current += "\n\n" + para

        else:

            if current.strip():
                chunks.append(current.strip())

            current = para

    if current.strip():
        chunks.append(current.strip())

    return chunks


# ──────────────────────────────────────────────────────────────────────────────
# SEMANTIC HEADING DETECTION
# ──────────────────────────────────────────────────────────────────────────────

def _detect_semantic_heading(lines: list[str]) -> str | None:

    for line in lines[:6]:

        clean = line.strip()

        if not clean:
            continue

        if (
            3 <= len(clean) <= 60
            and clean[0].isupper()
            and not clean.endswith('.')
            and len(clean.split()) <= 6
        ):

            blacklist = {
                "BY AND BETWEEN",
                "NOW THEREFORE",
                "WHEREAS",
                "AND",
            }

            if clean.upper() in blacklist:
                continue

            return clean

    return None


# ──────────────────────────────────────────────────────────────────────────────
# PARAGRAPH FALLBACK
# ──────────────────────────────────────────────────────────────────────────────

def _paragraph_fallback(text: str) -> list[Clause]:

    paragraphs = [

        p.strip()

        for p in re.split(r'\n\s*\n+', text)

        if len(p.strip()) >= 80
    ]

    if len(paragraphs) < 2:
        return []

    clauses = []

    for idx, para in enumerate(paragraphs):

        lines = [
            l.strip()
            for l in para.splitlines()
            if l.strip()
        ]

        heading = _detect_semantic_heading(lines)

        first_line = heading or lines[0][:80]

        clause_number = (
            heading.upper().replace(" ", "_")
            if heading
            else f"AUTO-{idx + 1}"
        )

        clauses.append(Clause(
            chunk_index=idx,
            clause_number=clause_number,
            clause_title=_clean_title(clause_number, first_line),
            clause_type=_detect_type(first_line, para),
            text=para,
        ))

    return clauses


# ──────────────────────────────────────────────────────────────────────────────
# BOUNDARY FINDER
# ──────────────────────────────────────────────────────────────────────────────

def _find_boundaries(text: str) -> list[dict]:

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

                end_heading = m.start(2)

            else:

                raw_num, title = '', groups[0]

                if not _valid_uppercase_heading(title):
                    continue

                newline_pos = text.find('\n', m.start())

                end_heading = (
                    newline_pos + 1
                    if newline_pos != -1
                    else m.end()
                )

            boundaries.append({

                'raw_number': raw_num.strip(),

                'number': (
                    _normalise_number(raw_num.strip())
                    if raw_num.strip()
                    else ''
                ),

                'title': title.strip(),

                'start': m.start(),

                'end_of_heading': end_heading,
            })

    boundaries.sort(key=lambda b: b['start'])

    return boundaries


# ──────────────────────────────────────────────────────────────────────────────
# SUB-CLAUSE GROUPING
# ──────────────────────────────────────────────────────────────────────────────

def _group_sub_clauses(raw_chunks: list[dict]) -> list[dict]:

    """
    Merge ONLY true child clauses:
        3.1 -> 3
        3.2 -> 3

    NEVER merge:
        7 -> 8
        8 -> 9

    NEVER merge large standalone clauses.
    """

    grouped = []

    i = 0

    while i < len(raw_chunks):

        chunk = raw_chunks[i]

        current_number = chunk["number"]

        # only top-level numeric clauses can absorb children
        if not re.match(r'^\d+$', current_number):

            grouped.append(chunk)

            i += 1

            continue

        combined_text = chunk["text"]

        j = i + 1

        while j < len(raw_chunks):

            next_chunk = raw_chunks[j]

            next_number = next_chunk["number"]

            # STRICT CHILD CHECK
            #
            # allowed:
            #   7.1 under 7
            #   7.2 under 7
            #
            # forbidden:
            #   8 under 7
            #   10 under 7
            #

            if not next_number.startswith(current_number + "."):
                break

            # prevent gigantic merged clauses
            if len(combined_text) > 1200:
                break

            combined_text += (
                "\n\n"
                + next_chunk["title"]
                + "\n"
                + next_chunk["text"]
            )

            j += 1

        grouped.append({
            **chunk,
            "text": combined_text
        })

        i = j if j > i + 1 else i + 1

    return grouped


# ──────────────────────────────────────────────────────────────────────────────
# MAIN CHUNKER
# ──────────────────────────────────────────────────────────────────────────────

def chunk(extraction: ExtractionResult) -> list[Clause]:

    text = extraction.text

    boundaries = _find_boundaries(text)

    # ──────────────────────────────────────────────────────────────────
    # FALLBACK
    # ──────────────────────────────────────────────────────────────────

    if not boundaries:

        fallback_clauses = _paragraph_fallback(text)

        if fallback_clauses:
            return fallback_clauses

        return [Clause(
            chunk_index=0,
            clause_number='AUTO-1',
            clause_title='Full Document',
            clause_type=ClauseType.general,
            text=text.strip(),
        )]

    # ──────────────────────────────────────────────────────────────────
    # RAW CHUNK BUILD
    # ──────────────────────────────────────────────────────────────────

    raw_chunks = []

    for idx, b in enumerate(boundaries):

        start = b['end_of_heading']

        end = (
            boundaries[idx + 1]['start']
            if idx + 1 < len(boundaries)
            else len(text)
        )

        body = text[start:end].strip()

        split_bodies = _force_split_large_chunk(body)

        for split_idx, split_body in enumerate(split_bodies):

            chunk_number = b['number']

            if split_idx > 0:

                if chunk_number:
                    chunk_number = f"{chunk_number}.{split_idx}"

                else:
                    chunk_number = f"AUTO-{idx+1}.{split_idx}"

            raw_chunks.append({

                'number': chunk_number,

                'title': _clean_title(
                    b['number'],
                    b['title']
                ),

                'text': split_body,
            })

    # ──────────────────────────────────────────────────────────────────
    # GROUP SUB-CLAUSES
    # ──────────────────────────────────────────────────────────────────

    grouped = _group_sub_clauses(raw_chunks)

    # ──────────────────────────────────────────────────────────────────
    # REMOVE GARBAGE
    # ──────────────────────────────────────────────────────────────────

    grouped = [
        c
        for c in grouped
        if not _is_garbage(c)
    ]

    # ──────────────────────────────────────────────────────────────────
    # SECONDARY FALLBACK
    # ──────────────────────────────────────────────────────────────────

    if not grouped:

        fallback_clauses = _paragraph_fallback(text)

        if fallback_clauses:
            return fallback_clauses

    # ──────────────────────────────────────────────────────────────────
    # BUILD CLAUSE OBJECTS
    # ──────────────────────────────────────────────────────────────────

    clauses = []

    for idx, c in enumerate(grouped):

        clause_number = (
            c['number']
            if c['number']
            else f"AUTO-{idx+1}"
        )

        clauses.append(Clause(

            chunk_index=idx,

            clause_number=clause_number,

            clause_title=c['title'],

            clause_type=_detect_type(
                c['title'],
                c['text']
            ),

            text=c['text'],
        ))

    return clauses