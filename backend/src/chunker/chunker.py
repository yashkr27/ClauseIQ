"""
Layer 2 — Semantic Chunker (v2)
Rules satisfied: A2, C1, C2, C3, C4

Primary:  Gemini reads LlamaParse markdown → returns clause JSON
Fallback: regex boundary detection (original approach, hardened)

Public interface:
    chunk(extraction: ExtractionResult) -> list[Clause]

Gemini output contract (one item per clause):
{
  "clause_number" : "11",
  "clause_title"  : "Indemnification",
  "clause_type"   : "indemnity",
  "page_number"   : 3,
  "text"          : "The Receiving Party shall indemnify..."
}

Oversized split rule:
  Any clause text > MAX_CHUNK_CHARS is split into 2-3 pieces
  on paragraph boundaries before being returned.
"""

import os
import re
import json

from ..extraction.extractor import ExtractionResult
from ..models.schemas import Clause, ClauseType

MAX_CHUNK_CHARS = 2000   # split threshold


# ──────────────────────────────────────────────────────────────────────────────
# CLAUSE TYPE HELPER (shared by both paths)
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

def _detect_type(title: str, text_sample: str) -> ClauseType:
    haystack = (title + ' ' + text_sample[:200]).lower()
    for clause_type, keywords in _TYPE_KEYWORDS:
        if any(kw in haystack for kw in keywords):
            return clause_type
    return ClauseType.general

def _safe_type(raw: str) -> ClauseType:
    """Convert Gemini string to ClauseType, fallback to general."""
    return ClauseType(raw) if raw in _VALID_TYPES else ClauseType.general


# ──────────────────────────────────────────────────────────────────────────────
# BOILERPLATE FILTER  (safety net after Gemini)
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

def _is_boilerplate(title: str, text: str) -> bool:
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
# OVERSIZED SPLIT
# ──────────────────────────────────────────────────────────────────────────────

def _split_oversized(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
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


# ──────────────────────────────────────────────────────────────────────────────
# PRIMARY: GEMINI SEMANTIC CHUNKER
# ──────────────────────────────────────────────────────────────────────────────

_GEMINI_PROMPT = """You are a legal document analyst. The text below is a legal contract in markdown format.
Page boundaries are marked with <!-- PAGE N --> comments.

Your task: identify every distinct clause and return a JSON array.

Rules:
- Every numbered clause is its own item (1, 2, 3... or 1.1, 1.2... or 8A, 8B...)
- Sub-clauses (1.1, 1.2) may be grouped under their parent IF the parent has no body text of its own
- If a clause has no visible number, generate one: "AUTO-N"
- page_number = the integer N from the nearest <!-- PAGE N --> marker ABOVE the clause (1 if none found)
- clause_type must be exactly one of: definition, obligation, limitation, termination, indemnity, ip, confidentiality, general
- text = the FULL clause body verbatim, including all sub-items
- Do NOT include preamble, recitals, signature blocks, or party definitions as clauses
- Return ONLY the JSON array, no explanation, no markdown fences

JSON schema (array of):
{
  "clause_number": string,
  "clause_title":  string,
  "clause_type":   string,
  "page_number":   integer,
  "text":          string
}

CONTRACT:
{markdown}
"""

def _call_gemini(markdown: str) -> list[dict]:
    """
    Send markdown to Gemini 1.5 Flash, parse JSON response.
    Raises on API error or invalid JSON.
    """
    from google import genai
    from google.genai import types

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY not set")

    client   = genai.Client(api_key=api_key)
    prompt   = _GEMINI_PROMPT.replace("{markdown}", markdown)
    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=8192,
        ),
    )

    raw = response.text.strip()

    # Strip markdown fences if Gemini adds them despite instructions
    raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'```\s*$',          '', raw, flags=re.MULTILINE)
    raw = raw.strip()

    return json.loads(raw)


def _gemini_chunk(extraction: ExtractionResult) -> list[Clause]:
    """
    Full Gemini path: call API → filter boilerplate → split oversized → build Clause objects.
    """
    raw_clauses = _call_gemini(extraction.markdown)

    if not isinstance(raw_clauses, list) or not raw_clauses:
        raise ValueError("Gemini returned empty or non-list response")

    clauses     = []
    chunk_index = 0

    for item in raw_clauses:
        number    = str(item.get("clause_number") or f"AUTO-{chunk_index+1}").strip()
        title     = str(item.get("clause_title")  or f"Clause {number}").strip()
        c_type    = _safe_type(str(item.get("clause_type", "general")))
        page_num  = item.get("page_number")
        text_body = str(item.get("text", "")).strip()

        if not text_body:
            continue

        # ── Safety net: drop boilerplate Gemini still returned ────────────────
        if _is_boilerplate(title, text_body):
            continue

        # Oversized split: produce 2-3 sub-chunks if needed
        pieces = _split_oversized(text_body)

        for piece_idx, piece in enumerate(pieces):
            sub_number = number if piece_idx == 0 else f"{number}.{piece_idx}"
            clauses.append(Clause(
                chunk_index=chunk_index,
                clause_number=sub_number,
                clause_title=title,
                clause_type=c_type,
                text=piece,
                page_number=int(page_num) if page_num else None,
            ))
            chunk_index += 1

    return clauses


# ──────────────────────────────────────────────────────────────────────────────
# FALLBACK: REGEX BOUNDARY CHUNKER (hardened original)
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

def _clean_title(number: str, raw: str) -> str:
    t = raw.strip()
    if len(t.split()) > 8 or t.endswith('.'):
        return f"Clause {number}" if number else "Clause"
    return t if len(t) <= 60 else (f"Clause {number}" if number else "Clause")

def _is_garbage(text: str, number: str, title: str) -> bool:
    if re.match(r'^\d{4,}$', number):                                    return True
    if len(text.strip()) < 30:                                           return True
    if title.upper() in ('TITLE', 'NAME', 'BY', 'DATE', 'SIGNATURE'):   return True
    if _is_boilerplate(title, text):                                     return True
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

def _regex_chunk(extraction: ExtractionResult) -> list[Clause]:
    text       = _preprocess(extraction.text)
    page_texts = extraction.page_texts

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

    if not boundaries:
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n+', text) if len(p.strip()) >= 30]
        clauses    = []
        for idx, para in enumerate(paragraphs):
            num = f"AUTO-{idx+1}"
            clauses.append(Clause(
                chunk_index=idx, clause_number=num,
                clause_title=f"Clause {idx+1}",
                clause_type=_detect_type('', para),
                text=para, page_number=None,
            ))
        return clauses or [Clause(
            chunk_index=0, clause_number='AUTO-1',
            clause_title='Full Document',
            clause_type=ClauseType.general,
            text=text.strip(), page_number=None,
        )]

    raw_chunks  = []
    chunk_index = 0

    for idx, b in enumerate(boundaries):
        start = b['end_of_heading']
        end   = boundaries[idx+1]['start'] if idx+1 < len(boundaries) else len(text)
        body  = text[start:end].strip()
        page  = _page_from_offset(b['start'], page_texts)

        for piece_idx, piece in enumerate(_split_oversized(body)):
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

    clauses = []
    for idx, c in enumerate(grouped):
        num = c['number'] if c['number'] else f"AUTO-{idx+1}"
        clauses.append(Clause(
            chunk_index=idx,
            clause_number=num,
            clause_title=c['title'],
            clause_type=_detect_type(c['title'], c['text']),
            text=c['text'],
            page_number=c.get('page'),
        ))

    return clauses


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC INTERFACE
# ──────────────────────────────────────────────────────────────────────────────

def chunk(extraction: ExtractionResult) -> list[Clause]:
    """
    Try Gemini semantic chunking first.
    Fall back to regex chunker if Gemini is unavailable or returns bad JSON.
    """
    try:
        clauses = _gemini_chunk(extraction)
        if clauses:
            return clauses
        raise ValueError("Gemini returned 0 clauses")
    except Exception:
        return _regex_chunk(extraction)