# ClauseIQ — Full Implementation Guide
# For: IDE-integrated Claude agent
# Purpose: Complete build instructions for every layer of the system.
#          Every rule from CLAUDE_MEMORY.md is embedded and cross-referenced here.
#          Follow this document sequentially. Do not skip sections.
#          When in doubt, a rule ID (e.g. A2, E1, C3) refers to CLAUDE_MEMORY.md.

---

## CRITICAL GROUND RULES — READ BEFORE WRITING ANY CODE

1. **OS is Windows.** Always use `python` not `python3`. Never suggest `apt` or `brew`. Use PowerShell syntax.
2. **Monolith only (rule A1).** Single FastAPI app. No Docker Compose with multiple services. No microservices.
3. **Layers are strictly ordered (rule A2).** Never merge two layers into one file. Never skip a layer.
4. **DB is always optional (rule A3).** Every layer must work without Supabase. In-memory fallback in `db.py` is always the default.
5. **Frontend is last (rule A4).** Do not touch `frontend/` until all 4 backend layers pass their tests.
6. **OCR is mandatory for PDF (rule A5).** Do NOT use PyMuPDF or pypdf. Both return empty strings on our vector-drawn PDFs. Only `pdf2image → pytesseract` works.
7. **Schema is locked (rule D1).** Never rename a column in `supabase/schema.sql` without simultaneously updating `models/schemas.py` and every layer that touches that field.
8. **No hardcoded contract names (rule CP4).** Zero references to "NDA", "Standstill", "Non-Solicitation" in matching or chunking logic. Must work on any contract type.
9. **Push back if a suggestion violates any rule.** Cite the rule ID. Do not silently comply.

---

## PROJECT STRUCTURE (locked — rule FILE STRUCTURE)

```
ClauseIQ/
├── CLAUDE_MEMORY.md           ← constraint rules (source of truth)
├── IMPLEMENTATION.md          ← this file
├── README.md                  ← setup instructions (rule SB3)
├── .env.example               ← env var template, never commit real .env
├── backend/
│   ├── requirements.txt
│   └── src/
│       ├── __init__.py
│       ├── db.py              ← Supabase client + in-memory fallback (rule A3, D2)
│       ├── api/
│       │   ├── __init__.py
│       │   ├── main.py        ← FastAPI app entry point
│       │   └── routes/
│       │       ├── __init__.py
│       │       ├── analyse.py ← POST /api/analyse (Mode A, rule M1)
│       │       └── compare.py ← POST /api/compare (Mode B, rule M2)
│       ├── extraction/
│       │   ├── __init__.py
│       │   ├── extractor.py   ← Layer 1 (rules A2, A5, E1, E2, E3)
│       │   └── test_extractor.py
│       ├── chunker/
│       │   ├── __init__.py
│       │   ├── chunker.py     ← Layer 2 (rules A2, C1, C2, C3, C4)
│       │   └── test_chunker.py
│       ├── comparator/
│       │   ├── __init__.py
│       │   ├── comparator.py  ← Layer 3 (rules A2, CP1, CP2, CP3, CP4)
│       │   └── test_comparator.py
│       ├── scorer/
│       │   ├── __init__.py
│       │   ├── scorer.py      ← Layer 4 (rules A2, S1, S2, S3, S4)
│       │   ├── knowledge.py   ← loads 10 CONSTRAINT nodes (rule SB1)
│       │   └── test_scorer.py
│       └── models/
│           ├── __init__.py
│           └── schemas.py     ← Pydantic models (rule D1)
├── frontend/                  ← Next.js app — build LAST (rule A4)
│   └── (scaffold with: npx create-next-app@latest . --typescript --tailwind --app)
├── supabase/
│   ├── schema.sql             ← DB schema (rule D1)
│   └── seed.sql               ← 10 knowledge nodes (rule SB1)
├── test-data/
│   ├── ndav1.pdf              ← vector-drawn PDF, OCR required (rule T1)
│   └── ndav2.pdf              ← vector-drawn PDF, OCR required (rule T1)
├── docs/
│   ├── architecture.md        ← required for submission (rule SB2)
│   └── assessment_brief.md    ← deliverable spec (read-only reference)
└── evaluation/                ← surprise contract test results (rule SB5)
```

---

## SYSTEM DEPENDENCIES (Windows — install before anything else)

### 1. Tesseract OCR
- Download: https://github.com/UB-Mannheim/tesseract/wiki
- Install `tesseract-ocr-w64-setup-*.exe`
- Default install path: `C:\Program Files\Tesseract-OCR\`
- Add to PATH: System Properties → Environment Variables → System Variables → Path → Add `C:\Program Files\Tesseract-OCR\`
- Verify in new PowerShell: `tesseract --version`

### 2. Poppler (required by pdf2image)
- Download: https://github.com/oschwartz10612/poppler-windows/releases
- Extract zip to `C:\poppler\`
- Add `C:\poppler\Library\bin` to PATH
- Verify in new PowerShell: `pdftoppm -v`

### 3. Python packages
```powershell
cd C:\Users\USER\Desktop\ClauseIQ\backend
pip install fastapi uvicorn[standard] python-multipart pydantic
pip install pdf2image pytesseract python-docx pillow
pip install scikit-learn numpy
pip install anthropic
pip install python-dotenv httpx pytest
pip install supabase
```

### 4. Verify full setup
```powershell
python -c "import pytesseract; print(pytesseract.get_tesseract_version())"
python -c "from pdf2image import convert_from_path; print('pdf2image ok')"
python -c "from docx import Document; print('python-docx ok')"
python -c "from sklearn.feature_extraction.text import TfidfVectorizer; print('sklearn ok')"
python -c "import anthropic; print('anthropic ok')"
```

---

## ENVIRONMENT VARIABLES

### `.env.example` (commit this)
```
ANTHROPIC_API_KEY=sk-ant-...
SUPABASE_URL=
SUPABASE_ANON_KEY=
ENV=development
```

### `.env` (never commit — rule SB4)
Copy `.env.example` to `.env` and fill in your actual keys.
The app works without `SUPABASE_URL` and `SUPABASE_ANON_KEY` — in-memory mode activates automatically (rule A3).

---

## DATABASE SCHEMA (rule D1 — locked)

File: `supabase/schema.sql`

```sql
CREATE TABLE knowledge_nodes (
  id            TEXT PRIMARY KEY,
  node_type     TEXT NOT NULL,       -- CONSTRAINT | ANTI_PATTERN | DECISION
  title         TEXT NOT NULL,
  content       TEXT NOT NULL,
  practice_area TEXT,
  tags          JSONB DEFAULT '[]'
);

CREATE TABLE documents (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  filename     TEXT NOT NULL,
  uploaded_at  TIMESTAMPTZ DEFAULT now(),
  content_text TEXT
);

CREATE TABLE document_chunks (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id   UUID REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index   INT NOT NULL,
  clause_number TEXT,
  clause_title  TEXT,
  clause_type   TEXT,
  text          TEXT NOT NULL
);

CREATE TABLE risk_scores (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  chunk_id              UUID REFERENCES document_chunks(id) ON DELETE CASCADE,
  score                 INT NOT NULL CHECK (score BETWEEN 1 AND 10),
  risk_factors          JSONB DEFAULT '[]',
  constraint_violations JSONB DEFAULT '[]',
  recommendation        TEXT
);

CREATE TABLE comparison_results (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  doc_v1_id        UUID REFERENCES documents(id),
  doc_v2_id        UUID REFERENCES documents(id),
  chunk_v1_id      UUID REFERENCES document_chunks(id),
  chunk_v2_id      UUID REFERENCES document_chunks(id),
  match_type       TEXT NOT NULL,
  similarity_score FLOAT,
  diff_text        TEXT
);
```

**Rule D1 enforcement:** If you ever need to add a column, you MUST update:
1. `supabase/schema.sql`
2. `backend/src/models/schemas.py`
3. Every layer function that reads/writes that table
All three in the same commit.

---

## PYDANTIC MODELS (rule D1)

File: `backend/src/models/schemas.py`

```python
from pydantic import BaseModel
from typing import Optional
from enum import Enum

class ClauseType(str, Enum):
    definition     = "definition"
    obligation     = "obligation"
    limitation     = "limitation"
    termination    = "termination"
    indemnity      = "indemnity"
    ip             = "ip"
    confidentiality = "confidentiality"
    general        = "general"

class MatchType(str, Enum):
    UNCHANGED = "UNCHANGED"
    MODIFIED  = "MODIFIED"
    ADDED     = "ADDED"
    REMOVED   = "REMOVED"

class Clause(BaseModel):
    chunk_index:   int
    clause_number: str
    clause_title:  str
    clause_type:   ClauseType
    text:          str

class RiskScore(BaseModel):
    chunk_index:          int
    clause_number:        str
    clause_title:         str
    score:                int          # 1–10
    risk_level:           str          # LOW | MEDIUM | HIGH
    risk_factors:         list[str]
    constraint_violations: list[str]
    recommendation:       str

class ComparisonResult(BaseModel):
    match_type:       MatchType
    clause_number_v1: Optional[str]
    clause_number_v2: Optional[str]
    clause_title:     str
    similarity_score: float
    diff_text:        Optional[str]
    risk_delta:       Optional[str]    # INCREASED | DECREASED | UNCHANGED | N/A
    score_v1:         Optional[int]
    score_v2:         Optional[int]

# API response shapes (rules M1, M2, M3)
class RiskSummary(BaseModel):
    high:   int
    medium: int
    low:    int

class AnalyseResponse(BaseModel):
    filename:     str
    clauses:      list[Clause]
    risk_scores:  list[RiskScore]
    risk_summary: RiskSummary

class CompareResponse(BaseModel):
    comparison: list[ComparisonResult]
    net_delta:  str    # INCREASED | DECREASED | UNCHANGED (rule M3)
```

---

## DB LAYER (rules A3, D2)

File: `backend/src/db.py`

```python
"""
DB layer — Supabase when env vars set, in-memory fallback otherwise (rule A3).
In-memory store field names MUST mirror schema.sql exactly (rule D2).
"""
import os

_client = None

def get_client():
    global _client
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_ANON_KEY", "")
    if url and key and _client is None:
        from supabase import create_client
        _client = create_client(url, key)
    return _client

def db_available() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_ANON_KEY"))

# In-memory store — field names match schema.sql exactly (rule D2)
_store: dict = {
    "knowledge_nodes":    [],
    "documents":          [],
    "document_chunks":    [],
    "risk_scores":        [],
    "comparison_results": [],
}

def mem_insert(table: str, row: dict) -> dict:
    _store[table].append(row)
    return row

def mem_get(table: str, filters: dict | None = None) -> list:
    rows = _store[table]
    if filters:
        for k, v in filters.items():
            rows = [r for r in rows if r.get(k) == v]
    return rows

def mem_clear(table: str):
    _store[table].clear()
```

---

## LAYER 1 — EXTRACTION (rules A2, A5, E1, E2, E3)

### Purpose
Convert a PDF or DOCX file into clean text with headings identified.
This is the ONLY layer that touches the file system and file formats.
Output feeds directly into Layer 2 (Chunker).

### Rules enforced
- **A2**: Extraction is its own module. Does not chunk.
- **A5**: PDF path uses ONLY `pdf2image → pytesseract`. PyMuPDF and pypdf are banned — they return empty strings on our vector-drawn NDAs.
- **E1**: Heading lines (numbered + UPPERCASE) are preserved in output text intact.
- **E2**: Single `extract(file_path)` function handles both PDF and DOCX.
- **E3**: Browser-print noise stripped — timestamp headers and URL footers removed.

### Why OCR on these PDFs (rule A5 — verified fact)
Both `test-data/ndav1.pdf` and `test-data/ndav2.pdf` store text as SVG vector paths,
not as embedded text characters. This is because they were printed from a web browser.
PyMuPDF returns 0 text blocks. pypdf returns empty strings. OCR via pdf2image+tesseract
extracts clean, complete text. This was empirically verified. Do not change this.

### File: `backend/src/extraction/extractor.py`

```python
"""
Layer 1 — Extraction
Rules: A2, A5, E1, E2, E3
Public interface: extract(file_path: str) -> ExtractionResult
"""
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Windows: point pytesseract at installed binary if not on PATH
if sys.platform == 'win32':
    import pytesseract
    _tess = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    if Path(_tess).exists():
        pytesseract.pytesseract.tesseract_cmd = _tess


@dataclass
class ExtractionResult:
    text:      str        # clean text, headings preserved (E1)
    headings:  list       # [{number, title, char_offset}]
    file_type: str        # "pdf" | "docx"
    pages:     int        # page count


# ── noise stripping (E3) ──────────────────────────────────────────────────────
# Our PDFs are browser-printed. Every page has:
#   - Header: "5/24/26, 12:21 AM  Mutual Non-Disclosure Agreement"
#   - Footer: "https://www.sec.gov/Archives/..."
#   - Page marker: "Page 3 of 6"
# Strip all three patterns before passing to chunker.

_NOISE_PATTERNS = [
    re.compile(r'^\d{1,2}/\d{1,2}/\d{2,4},\s+\d{1,2}:\d{2}\s+(AM|PM)\s*.*$', re.MULTILINE),
    re.compile(r'^https?://\S+\s*$', re.MULTILINE),
    re.compile(r'^Page\s+\d+\s+of\s+\d+\s*$', re.MULTILINE | re.IGNORECASE),
]

def _strip_noise(text: str) -> str:
    for pat in _NOISE_PATTERNS:
        text = pat.sub('', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── heading detection (E1, C2) ────────────────────────────────────────────────
# Must detect BOTH numbering styles present in our NDAs:
#   ndav1.pdf: flat integers    → "1.", "2.", "3." ... "14."
#   ndav2.pdf: decimal notation → "1.0", "2.0", "3.1", "3.2" ...
# Also detects: UPPERCASE SECTION TITLES, SCHEDULE A, ANNEXURE 1

_HEADING_PATTERNS = [
    re.compile(r'^(\d+\.\d+)\.?\s+([A-Z][^\n]{2,60})$', re.MULTILINE),   # decimal
    re.compile(r'^(\d+)\.?\s+([A-Z][^\n]{2,60})$', re.MULTILINE),         # integer
    re.compile(r'^([A-Z]{4,}(?:\s+[A-Z]+){0,5})$', re.MULTILINE),         # UPPERCASE
    re.compile(r'^(SCHEDULE\s+[A-Z0-9]+|ANNEXURE\s+[A-Z0-9]+)$', re.MULTILINE),
]

def _extract_headings(text: str) -> list:
    headings = []
    seen = set()
    for pat in _HEADING_PATTERNS:
        for m in pat.finditer(text):
            if m.start() in seen:
                continue
            seen.add(m.start())
            groups = m.groups()
            number, title = (groups[0], groups[1]) if len(groups) == 2 else ('', groups[0])
            headings.append({
                'number':      number.strip(),
                'title':       title.strip(),
                'char_offset': m.start(),
            })
    headings.sort(key=lambda h: h['char_offset'])
    return headings


# ── PDF extraction (A5) ───────────────────────────────────────────────────────
# MANDATORY: use pdf2image → pytesseract.
# DO NOT use pymupdf, pypdf, pdfplumber, or docling for PDFs.
# Reason: our test PDFs store text as SVG vector paths — only OCR works.

def _extract_pdf(file_path: str) -> tuple[str, int]:
    from pdf2image import convert_from_path
    import pytesseract
    pages = convert_from_path(file_path, dpi=200)
    texts = [pytesseract.image_to_string(p) for p in pages]
    return '\n'.join(texts), len(pages)


# ── DOCX extraction (E2) ──────────────────────────────────────────────────────

def _extract_docx(file_path: str) -> tuple[str, int]:
    from docx import Document
    doc = Document(file_path)
    lines = [para.text.strip() for para in doc.paragraphs]
    return '\n'.join(lines), 1


# ── public interface (E2) ─────────────────────────────────────────────────────

def extract(file_path: str) -> ExtractionResult:
    """Single entry point. Dispatches by extension. Always strips noise (E3)."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    ext = path.suffix.lower()
    if ext == '.pdf':
        raw, pages = _extract_pdf(file_path)
        ftype = 'pdf'
    elif ext in ('.docx', '.doc'):
        raw, pages = _extract_docx(file_path)
        ftype = 'docx'
    else:
        raise ValueError(f"Unsupported: {ext}. Use .pdf or .docx")
    clean = _strip_noise(raw)
    return ExtractionResult(text=clean, headings=_extract_headings(clean),
                            file_type=ftype, pages=pages)
```

### Tests: `backend/src/extraction/test_extractor.py`

Every test maps to a rule. Tests must ALL pass before committing (rule SB4).

```python
import re, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.extraction.extractor import extract, _strip_noise, _extract_headings

TEST_DATA = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'test-data')
NDA_V1    = os.path.join(TEST_DATA, 'ndav1.pdf')
NDA_V2    = os.path.join(TEST_DATA, 'ndav2.pdf')

# E3 — noise stripping
def test_strips_timestamp():
    assert '12:21 AM' not in _strip_noise("5/24/26, 12:21 AM Header\n\nContent.")
def test_strips_url():
    assert 'sec.gov' not in _strip_noise("Text.\nhttps://www.sec.gov/abc.htm\nMore.")
def test_strips_page_marker():
    assert 'Page 3 of 6' not in _strip_noise("Text.\nPage 3 of 6\nMore.")
def test_no_triple_blank_lines():
    assert '\n\n\n' not in _strip_noise("A\n\n\n\n\nB")

# E1, C2 — heading detection
def test_integer_headings():
    h = _extract_headings("1. Definitions\n\nText.\n\n2. Obligations\n\nText.")
    nums = [x['number'] for x in h]
    assert '1' in nums and '2' in nums

def test_decimal_headings():
    h = _extract_headings("1.0 DEFINITIONS\n\nText.\n\n3.1 Confidentiality\n\nText.")
    nums = [x['number'] for x in h]
    assert '1.0' in nums and '3.1' in nums

def test_uppercase_headings():
    h = _extract_headings("BACKGROUND\n\nText.\n\nOPERATIVE TERMS\n\nText.")
    titles = [x['title'] for x in h]
    assert any('BACKGROUND' in t for t in titles)

def test_headings_sorted():
    h = _extract_headings("1. First\n\nText.\n\n2. Second\n\nText.")
    assert [x['char_offset'] for x in h] == sorted(x['char_offset'] for x in h)

# A5, T1 — PDF OCR (vector-drawn PDFs)
def test_v1_extracts_text():
    r = extract(NDA_V1)
    assert r.file_type == 'pdf'
    assert len(r.text) > 500

def test_v1_noise_stripped():
    r = extract(NDA_V1)
    assert 'sec.gov' not in r.text
    assert not re.search(r'\d{1,2}/\d{1,2}/\d{2,4},\s+\d{1,2}:\d{2}\s+(AM|PM)', r.text)

def test_v1_has_headings():
    r = extract(NDA_V1)
    assert len(r.headings) >= 5, f"Expected >=5 headings, got: {r.headings}"

def test_v2_decimal_headings():
    r = extract(NDA_V2)
    decimals = [h for h in r.headings if '.' in h['number']]
    assert len(decimals) >= 3, f"Expected decimal headings, got: {r.headings}"

def test_v1_page_count():
    assert extract(NDA_V1).pages == 6

# E2 — interface contract
def test_result_has_all_fields():
    r = extract(NDA_V1)
    assert all(hasattr(r, f) for f in ['text', 'headings', 'file_type', 'pages'])

# Error handling
def test_missing_file():
    try:
        extract('/tmp/nope.pdf')
        assert False
    except FileNotFoundError:
        pass

def test_bad_extension():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
        f.write(b'x'); tmp = f.name
    try:
        extract(tmp); assert False
    except ValueError:
        pass
    finally:
        os.unlink(tmp)
```

### Run Layer 1 tests
```powershell
cd C:\Users\USER\Desktop\ClauseIQ\backend
python -m pytest src/extraction/test_extractor.py -v
```

All tests green → commit:
```powershell
git add -A
git commit -m "Layer 1 — Extraction complete"
```

---

## LAYER 2 — CHUNKER (rules A2, C1, C2, C3, C4)

### Purpose
Takes the `ExtractionResult.text` from Layer 1 and splits it into individual legal clauses.
This is the hardest layer. Everything downstream depends on correct clause boundaries.

### Rules enforced
- **C1**: Split ONLY on legal clause boundaries — numbered headings, UPPERCASE titles, SCHEDULE/ANNEXURE markers. NEVER by token count, character count, or paragraph breaks.
- **C2**: Normalise both numbering styles to canonical form: `"1"`, `"1."`, `"1.0"` all → `"1"`. This enables cross-document matching in Layer 3.
- **C3**: Sub-clauses (3.1, 3.2) stay grouped under their parent (3.0) UNLESS the parent block exceeds 800 chars. Never split mid-sentence or mid-definition.
- **C4**: Tag each clause with a type using keyword heuristics only — NOT the LLM (too slow).

### Canonical number normalisation (rule C2)
```
"1"    → "1"
"1."   → "1"
"1.0"  → "1"
"3.1"  → "3.1"   (sub-clause — keep decimal, used for grouping)
"3.1." → "3.1"
```
Parent number = everything before the last `.` in a decimal: "3.1" → parent is "3".

### Clause type keyword heuristics (rule C4)
```
"definition" | "means" | "defined"           → definition
"shall" | "must" | "agrees to" | "will"      → obligation
"limitation" | "liability" | "cap" | "maximum" → limitation
"terminat" | "expir" | "cancel"              → termination
"indemnif" | "hold harmless"                 → indemnity
"intellectual property" | "patent" | "copyright" | "IP" → ip
"confidential" | "non-disclosure" | "secret" → confidentiality
(default)                                    → general
```
Apply to the clause title first; if no match, scan first 200 chars of clause text.

### File: `backend/src/chunker/chunker.py`

```python
"""
Layer 2 — Legal-aware Chunker
Rules: A2, C1, C2, C3, C4
Input:  ExtractionResult (from Layer 1)
Output: list[Clause]  (Pydantic model from models/schemas.py)
"""
import re
from backend.src.extraction.extractor import ExtractionResult
from backend.src.models.schemas import Clause, ClauseType


# ── boundary patterns (C1) ────────────────────────────────────────────────────
# These are the ONLY valid split points. No paragraph splitting. No token limits.

_BOUNDARY_PATTERNS = [
    re.compile(r'^(\d+\.\d+)\.?\s+([A-Z][^\n]{0,80})$', re.MULTILINE),   # decimal sub
    re.compile(r'^(\d+)\.?\s+([A-Z][^\n]{0,80})$', re.MULTILINE),         # integer
    re.compile(r'^([A-Z]{4,}(?:\s+[A-Z]+){0,6})\s*$', re.MULTILINE),      # UPPERCASE
    re.compile(r'^(SCHEDULE\s+[A-Z0-9]+|ANNEXURE\s+[A-Z0-9]+)\s*$', re.MULTILINE),
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
                if next_parent == chunk['number']:
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
```

### Tests: `backend/src/chunker/test_chunker.py`

```python
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.extraction.extractor import ExtractionResult
from src.chunker.chunker import chunk, _normalise_number, _parent_number, _detect_type
from src.models.schemas import ClauseType

def _make_extraction(text: str) -> ExtractionResult:
    return ExtractionResult(text=text, headings=[], file_type='docx', pages=1)

# C2 — number normalisation
def test_normalise_integer():        assert _normalise_number('1')   == '1'
def test_normalise_dot():            assert _normalise_number('1.')  == '1'
def test_normalise_decimal_zero():   assert _normalise_number('1.0') == '1'
def test_normalise_sub_clause():     assert _normalise_number('3.1') == '3.1'
def test_normalise_sub_dot():        assert _normalise_number('3.1.') == '3.1'
def test_parent_of_sub():            assert _parent_number('3.1') == '3'
def test_parent_of_top():            assert _parent_number('3') == ''

# C1 — legal-aware splitting
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

# C3 — sub-clause grouping
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

# C4 — type tagging
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

# Integration — run on actual NDAs
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
```

### Run Layer 2 tests
```powershell
python -m pytest src/chunker/test_chunker.py -v
```

All green → commit:
```powershell
git add -A
git commit -m "Layer 2 — Chunker complete"
```

---

## LAYER 3 — COMPARATOR (rules A2, CP1, CP2, CP3, CP4)

### Purpose
Takes two `list[Clause]` (from Layer 2) and classifies each clause pair as
UNCHANGED / MODIFIED / ADDED / REMOVED. For MODIFIED clauses, produces word-level diff.

### Rules enforced
- **CP1**: Always run BOTH L1 (heading match) AND L2 (TF-IDF semantic match). Never only one.
- **CP2**: Thresholds: >0.95 cosine = UNCHANGED. 0.4–0.95 = MODIFIED. <0.4 = ADDED/REMOVED.
- **CP3**: Word-level diff for every MODIFIED clause using `difflib`. Never return "changed" without showing what.
- **CP4**: Zero hardcoded clause names. No `if clause.title == "Standstill"`. Pure structural matching.

### Why L2 is mandatory (rule CP1)
Our NDAs have structural renumbering: v1 Section 3 (Standstill) is the same content as
v2 Section 9.0 — but heading match alone will classify it as REMOVED (v1) + ADDED (v2).
TF-IDF cosine similarity on the clause text body correctly identifies them as MODIFIED.
This is the single hardest test case. L2 MUST run on all unmatched clauses.

### L1 Heading normalisation logic
```
"clause 3" → "3"
"3."       → "3"
"3.0"      → "3"
"section 3" → "3"
strip: "clause ", "section ", "article ", dots, whitespace, lowercase
```

### L2 TF-IDF matching
Use `sklearn.feature_extraction.text.TfidfVectorizer` + cosine similarity.
Fit on all clause texts from both documents combined.
Match unmatched v1 clauses to unmatched v2 clauses using greedy highest-similarity assignment.

### Word-level diff format (rule CP3)
```python
[
  {"type": "equal",  "text": "The parties agree to "},
  {"type": "remove", "text": "keep confidential"},
  {"type": "add",    "text": "maintain in strict confidence"},
  {"type": "equal",  "text": " all information."}
]
```

### File: `backend/src/comparator/comparator.py`

```python
"""
Layer 3 — Clause Comparator
Rules: A2, CP1, CP2, CP3, CP4
Input:  list[Clause] v1,  list[Clause] v2
Output: list[ComparisonResult]
"""
import re
import difflib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from backend.src.models.schemas import Clause, ComparisonResult, MatchType


# ── thresholds (CP2) ──────────────────────────────────────────────────────────
UNCHANGED_THRESHOLD = 0.95
MODIFIED_THRESHOLD  = 0.40


# ── heading normalisation for L1 (CP1, CP4) ──────────────────────────────────
# NO hardcoded clause names. Pure structural normalisation.

def _normalise_heading(raw: str) -> str:
    """
    Strips: "clause ", "section ", "article ", dots, extra whitespace.
    Strips trailing .0 from decimal numbers.
    Lowercases.
    Result: bare number or bare word — comparable across documents.
    """
    s = raw.lower().strip()
    for prefix in ('clause ', 'section ', 'article ', 'part '):
        s = s.replace(prefix, '')
    s = s.rstrip('.')
    # "1.0" → "1"
    if re.match(r'^\d+\.0$', s):
        s = s.split('.')[0]
    return s.strip()


# ── word-level diff (CP3) ─────────────────────────────────────────────────────

def _word_diff(text_v1: str, text_v2: str) -> list[dict]:
    """
    Returns word-level diff as list of {type, text}.
    Types: "equal" | "add" | "remove"
    Rule CP3: never return "changed" without this diff.
    """
    words_v1 = text_v1.split()
    words_v2 = text_v2.split()
    matcher  = difflib.SequenceMatcher(None, words_v1, words_v2)
    result   = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == 'equal':
            result.append({'type': 'equal',  'text': ' '.join(words_v1[i1:i2])})
        elif op == 'replace':
            result.append({'type': 'remove', 'text': ' '.join(words_v1[i1:i2])})
            result.append({'type': 'add',    'text': ' '.join(words_v2[j1:j2])})
        elif op == 'delete':
            result.append({'type': 'remove', 'text': ' '.join(words_v1[i1:i2])})
        elif op == 'insert':
            result.append({'type': 'add',    'text': ' '.join(words_v2[j1:j2])})
    return result


# ── L1: heading match (CP1) ───────────────────────────────────────────────────

def _l1_match(clauses_v1: list[Clause], clauses_v2: list[Clause]
              ) -> tuple[list[tuple], set, set]:
    """
    Returns: (matched_pairs, unmatched_v1_indices, unmatched_v2_indices)
    matched_pairs: [(clause_v1, clause_v2), ...]
    """
    norm_v2 = {_normalise_heading(c.clause_number): i for i, c in enumerate(clauses_v2)
               if c.clause_number}
    matched_pairs    = []
    matched_v1_idx   = set()
    matched_v2_idx   = set()

    for i, c1 in enumerate(clauses_v1):
        key = _normalise_heading(c1.clause_number)
        if key and key in norm_v2:
            j = norm_v2[key]
            if j not in matched_v2_idx:
                matched_pairs.append((c1, clauses_v2[j]))
                matched_v1_idx.add(i)
                matched_v2_idx.add(j)

    unmatched_v1 = set(range(len(clauses_v1))) - matched_v1_idx
    unmatched_v2 = set(range(len(clauses_v2))) - matched_v2_idx
    return matched_pairs, unmatched_v1, unmatched_v2


# ── L2: TF-IDF semantic match (CP1) ──────────────────────────────────────────

def _l2_match(clauses_v1: list[Clause], clauses_v2: list[Clause],
              unmatched_v1: set, unmatched_v2: set
              ) -> list[tuple[Clause, Clause, float]]:
    """
    TF-IDF cosine similarity on clause text bodies.
    Returns list of (clause_v1, clause_v2, similarity_score) for pairs above MODIFIED_THRESHOLD.
    Rule CP1: this runs on ALL unmatched clauses, every time.
    Rule CP4: no hardcoded titles — purely content-based.
    """
    if not unmatched_v1 or not unmatched_v2:
        return []

    um_v1 = [clauses_v1[i] for i in sorted(unmatched_v1)]
    um_v2 = [clauses_v2[j] for j in sorted(unmatched_v2)]

    all_texts = [c.text for c in um_v1] + [c.text for c in um_v2]
    vectorizer = TfidfVectorizer(stop_words='english', ngram_range=(1, 2))
    tfidf = vectorizer.fit_transform(all_texts)

    v1_vecs = tfidf[:len(um_v1)]
    v2_vecs = tfidf[len(um_v1):]
    sim_matrix = cosine_similarity(v1_vecs, v2_vecs)

    # Greedy assignment — highest similarity first
    pairs = []
    used_v2 = set()
    indices = np.argsort(-sim_matrix, axis=None)
    for flat_idx in indices:
        i, j = divmod(int(flat_idx), len(um_v2))
        if j in used_v2:
            continue
        score = float(sim_matrix[i, j])
        if score < MODIFIED_THRESHOLD:
            break
        pairs.append((um_v1[i], um_v2[j], score))
        used_v2.add(j)

    return pairs


# ── public interface ──────────────────────────────────────────────────────────

def compare(clauses_v1: list[Clause], clauses_v2: list[Clause]) -> list[ComparisonResult]:
    """
    Layer 3 public interface.
    Rules: CP1 (L1+L2 always), CP2 (thresholds), CP3 (word diff), CP4 (no hardcoding).
    """
    results = []

    # L1: heading match
    matched_l1, unmatched_v1, unmatched_v2 = _l1_match(clauses_v1, clauses_v2)

    for c1, c2 in matched_l1:
        sim = cosine_similarity(
            TfidfVectorizer(stop_words='english').fit_transform([c1.text, c2.text])
        )[0][1] if c1.text and c2.text else 1.0

        if sim > UNCHANGED_THRESHOLD:
            match_type = MatchType.UNCHANGED
            diff       = None
        else:
            match_type = MatchType.MODIFIED
            diff       = _word_diff(c1.text, c2.text)

        results.append(ComparisonResult(
            match_type=match_type,
            clause_number_v1=c1.clause_number,
            clause_number_v2=c2.clause_number,
            clause_title=c1.clause_title or c2.clause_title,
            similarity_score=round(sim, 3),
            diff_text=str(diff) if diff else None,
            risk_delta=None, score_v1=None, score_v2=None,
        ))

    # L2: semantic match on remaining unmatched (CP1 — always run)
    semantic_pairs = _l2_match(clauses_v1, clauses_v2, unmatched_v1, unmatched_v2)
    semantic_v1_matched = set()
    semantic_v2_matched = set()

    for c1, c2, sim in semantic_pairs:
        diff = _word_diff(c1.text, c2.text)
        results.append(ComparisonResult(
            match_type=MatchType.MODIFIED,
            clause_number_v1=c1.clause_number,
            clause_number_v2=c2.clause_number,
            clause_title=c1.clause_title or c2.clause_title,
            similarity_score=round(sim, 3),
            diff_text=str(diff),
            risk_delta=None, score_v1=None, score_v2=None,
        ))
        semantic_v1_matched.add(c1.clause_number)
        semantic_v2_matched.add(c2.clause_number)

    # Remaining unmatched v1 = REMOVED
    for i in unmatched_v1:
        c1 = clauses_v1[i]
        if c1.clause_number not in semantic_v1_matched:
            results.append(ComparisonResult(
                match_type=MatchType.REMOVED,
                clause_number_v1=c1.clause_number,
                clause_number_v2=None,
                clause_title=c1.clause_title,
                similarity_score=0.0,
                diff_text=None, risk_delta=None, score_v1=None, score_v2=None,
            ))

    # Remaining unmatched v2 = ADDED
    for j in unmatched_v2:
        c2 = clauses_v2[j]
        if c2.clause_number not in semantic_v2_matched:
            results.append(ComparisonResult(
                match_type=MatchType.ADDED,
                clause_number_v1=None,
                clause_number_v2=c2.clause_number,
                clause_title=c2.clause_title,
                similarity_score=0.0,
                diff_text=None, risk_delta=None, score_v1=None, score_v2=None,
            ))

    return results
```

### Tests: `backend/src/comparator/test_comparator.py`

```python
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.comparator.comparator import compare, _normalise_heading, _word_diff
from src.models.schemas import Clause, ClauseType, MatchType

def _clause(num, title, text, idx=0):
    return Clause(chunk_index=idx, clause_number=num, clause_title=title,
                  clause_type=ClauseType.general, text=text)

# CP4 — heading normalisation (no hardcoding)
def test_normalise_strips_prefix():
    assert _normalise_heading('Section 3') == '3'
    assert _normalise_heading('Clause 3.') == '3'
    assert _normalise_heading('3.0')       == '3'
    assert _normalise_heading('3.1')       == '3.1'

# CP3 — word diff
def test_word_diff_detects_change():
    diff = _word_diff("liability is unlimited", "liability is capped at 2x")
    types = [d['type'] for d in diff]
    assert 'remove' in types
    assert 'add' in types

def test_word_diff_equal_texts():
    diff = _word_diff("same text here", "same text here")
    assert all(d['type'] == 'equal' for d in diff)

# CP1, CP2 — matching
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

# CP1 — semantic match (the key NDA test case)
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

# T2 — integration: known NDA differences must be found
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
```

### Run Layer 3 tests
```powershell
python -m pytest src/comparator/test_comparator.py -v
```

All green → commit:
```powershell
git add -A
git commit -m "Layer 3 — Comparator complete"
```

---

## LAYER 4 — RISK SCORER (rules A2, S1, S2, S3, S4, SB1)

### Purpose
Scores each clause 1–10 for risk using the Claude API plus firm CONSTRAINT nodes.
The CONSTRAINT override (rule S2) is what makes this system better than generic AI tools.

### Rules enforced
- **S1**: Every API call MUST include all relevant `knowledge_nodes` as context. No exceptions.
- **S2**: CONSTRAINT node threshold triggers override the LLM score in Python — not in the prompt. If `C-010` (uncapped liability) fires, score = 8 minimum, regardless of what Claude returned.
- **S3**: Output schema is fixed: `{score, risk_level, risk_factors, constraint_violations, recommendation}`.
- **S4**: Risk delta = `score_v2 - score_v1`. Computed after both documents are scored.
- **SB1**: 10 knowledge nodes from `seed.sql` must be loaded at startup into in-memory store when DB not configured.

### Risk level mapping (S3)
```
1–3  → LOW    (green)
4–6  → MEDIUM (orange)
7–10 → HIGH   (red)
```

### CONSTRAINT override logic (S2) — in Python, not the prompt
```python
# After receiving LLM score, check each CONSTRAINT:
# C-010: "liability" + "unlimited" in clause text → score = max(score, 8)
# C-011: "non-compete" or "non-solicitation" + duration > 12 months → score = max(score, 7)
# C-012: "all ip" or "all intellectual property" without "carve-out" → score = max(score, 7)
# C-013: no "arbitration" in dispute clause → score = max(score, 6)
# C-014: "termination" + notice < 90 days → score = max(score, 6)
```

### File: `backend/src/scorer/knowledge.py`

```python
"""
Loads 10 firm knowledge nodes.
Rule SB1: loads from Supabase if available, from seed.sql parse if not.
Rule S1: these nodes are injected into every scoring call.
"""
import os, re
from backend.src.db import db_available, mem_insert, mem_get

SEED_PATH = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'supabase', 'seed.sql')

def _parse_seed_sql(path: str) -> list[dict]:
    """Parse seed.sql INSERT statements into dicts."""
    nodes = []
    with open(path, 'r') as f:
        content = f.read()
    pattern = re.compile(
        r"VALUES\s*\('([^']+)','([^']+)','([^']+)','([^']+)','([^']+)','([^']+)'\)"
    )
    for m in pattern.finditer(content):
        nodes.append({
            'id': m.group(1), 'node_type': m.group(2), 'title': m.group(3),
            'content': m.group(4), 'practice_area': m.group(5), 'tags': m.group(6),
        })
    return nodes

def load_knowledge_nodes() -> list[dict]:
    """Returns all 10 knowledge nodes from DB or in-memory store."""
    if db_available():
        from backend.src.db import get_client
        res = get_client().table('knowledge_nodes').select('*').execute()
        return res.data
    existing = mem_get('knowledge_nodes')
    if not existing:
        for node in _parse_seed_sql(SEED_PATH):
            mem_insert('knowledge_nodes', node)
    return mem_get('knowledge_nodes')
```

### File: `backend/src/scorer/scorer.py`

```python
"""
Layer 4 — Risk Scorer
Rules: A2, S1, S2, S3, S4, SB1
Input:  list[Clause], list[knowledge_nodes]
Output: list[RiskScore]
"""
import os, re, json
from anthropic import Anthropic
from backend.src.models.schemas import Clause, RiskScore
from backend.src.scorer.knowledge import load_knowledge_nodes

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


# ── CONSTRAINT override rules (S2) ────────────────────────────────────────────
# Logic lives in Python, NOT in the LLM prompt.
# Each entry: (constraint_id, check_function, minimum_score)

def _check_constraints(clause: Clause, nodes: list[dict]) -> tuple[int, list[str]]:
    """
    Returns (minimum_score_from_constraints, [triggered_constraint_ids])
    Rule S2: this result overrides whatever the LLM returned if it's higher.
    """
    text  = clause.text.lower()
    title = clause.clause_title.lower()
    violations = []
    min_score  = 0

    # C-010: uncapped liability
    if ('liability' in text or 'liable' in text):
        if any(w in text for w in ['unlimited', 'uncapped', 'no limit', 'no cap']):
            violations.append('C-010')
            min_score = max(min_score, 8)

    # C-011: non-compete / non-solicitation > 12 months
    if any(w in text for w in ['non-compete', 'non-solicitation', 'noncompete', 'nonsolicitation']):
        months = re.findall(r'(\d+)\s*month', text)
        years  = re.findall(r'(\d+)\s*year', text)
        duration_months = max([int(m) for m in months], default=0)
        duration_months = max(duration_months, max([int(y)*12 for y in years], default=0))
        if duration_months > 12:
            violations.append('C-011')
            min_score = max(min_score, 7)

    # C-012: broad IP assignment without carve-out
    if any(w in text for w in ['all intellectual property', 'all ip', 'all inventions']):
        if 'carve' not in text and 'pre-existing' not in text and 'prior ip' not in text:
            violations.append('C-012')
            min_score = max(min_score, 7)

    # C-013: no arbitration in dispute/governing law clause
    if any(w in title for w in ['dispute', 'governing', 'jurisdiction', 'resolution']):
        if 'arbitration' not in text and 'arbitrate' not in text:
            violations.append('C-013')
            min_score = max(min_score, 6)

    # C-014: termination notice < 90 days
    if 'terminat' in text and 'notice' in text:
        days  = re.findall(r'(\d+)\s*day', text)
        if days:
            min_days = min(int(d) for d in days)
            if min_days < 90:
                violations.append('C-014')
                min_score = max(min_score, 6)

    return min_score, violations


def _build_prompt(clause: Clause, nodes: list[dict]) -> str:
    """
    Rule S1: inject ALL knowledge nodes into prompt.
    The LLM sees firm policy alongside the clause text.
    """
    node_text = '\n'.join(
        f"[{n['id']} — {n['node_type']}] {n['title']}: {n['content']}"
        for n in nodes
    )
    return f"""You are a legal risk analyst. Score the following contract clause for risk.

FIRM KNOWLEDGE BASE (these rules override general legal norms):
{node_text}

CLAUSE TO SCORE:
Number: {clause.clause_number}
Title: {clause.clause_title}
Type: {clause.clause_type}
Text:
{clause.text}

Respond with ONLY a JSON object, no other text:
{{
  "score": <integer 1-10>,
  "risk_factors": ["factor 1", "factor 2"],
  "recommendation": "<one sentence action>"
}}

Score guide: 1-3=LOW risk, 4-6=MEDIUM risk, 7-10=HIGH risk.
Reference specific firm knowledge node IDs (e.g. C-010) when they apply."""


def _score_level(score: int) -> str:
    if score <= 3:  return 'LOW'
    if score <= 6:  return 'MEDIUM'
    return 'HIGH'


def score_clause(clause: Clause, nodes: list[dict]) -> RiskScore:
    """
    Scores a single clause. Applies CONSTRAINT override after LLM call (rule S2).
    """
    prompt = _build_prompt(clause, nodes)

    response = client.messages.create(
        model='claude-sonnet-4-20250514',
        max_tokens=500,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = response.content[0].text.strip()
    # Strip any accidental markdown fences
    raw = re.sub(r'^```json\s*|```$', '', raw, flags=re.MULTILINE).strip()
    data = json.loads(raw)

    llm_score   = max(1, min(10, int(data.get('score', 5))))
    risk_factors = data.get('risk_factors', [])
    recommendation = data.get('recommendation', '')

    # Apply CONSTRAINT overrides (S2) — Python logic, not prompt
    constraint_min, violations = _check_constraints(clause, nodes)
    final_score = max(llm_score, constraint_min)

    return RiskScore(
        chunk_index=clause.chunk_index,
        clause_number=clause.clause_number,
        clause_title=clause.clause_title,
        score=final_score,
        risk_level=_score_level(final_score),
        risk_factors=risk_factors,
        constraint_violations=violations,
        recommendation=recommendation,
    )


def score_document(clauses: list[Clause]) -> list[RiskScore]:
    """Score all clauses in a document. Rule SB1: loads nodes automatically."""
    nodes = load_knowledge_nodes()
    return [score_clause(c, nodes) for c in clauses]


def compute_risk_delta(scores_v1: list[RiskScore],
                       scores_v2: list[RiskScore],
                       comparison_results: list) -> list:
    """
    Rule S4: attach risk delta to each ComparisonResult.
    delta = score_v2 - score_v1
    > 0 → INCREASED, < 0 → DECREASED, = 0 → UNCHANGED
    """
    v1_map = {s.clause_number: s.score for s in scores_v1}
    v2_map = {s.clause_number: s.score for s in scores_v2}

    updated = []
    for r in comparison_results:
        s1 = v1_map.get(r.clause_number_v1)
        s2 = v2_map.get(r.clause_number_v2)
        if s1 is not None and s2 is not None:
            delta = s2 - s1
            r = r.model_copy(update={
                'risk_delta': 'INCREASED' if delta > 0 else ('DECREASED' if delta < 0 else 'UNCHANGED'),
                'score_v1': s1,
                'score_v2': s2,
            })
        elif s2 is not None:
            r = r.model_copy(update={'risk_delta': 'N/A', 'score_v2': s2})
        elif s1 is not None:
            r = r.model_copy(update={'risk_delta': 'N/A', 'score_v1': s1})
        updated.append(r)
    return updated
```

### Tests: `backend/src/scorer/test_scorer.py`

```python
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.scorer.scorer import _check_constraints, _score_level, compute_risk_delta
from src.scorer.knowledge import load_knowledge_nodes
from src.models.schemas import Clause, ClauseType, RiskScore, ComparisonResult, MatchType

def _clause(num, title, text):
    return Clause(chunk_index=0, clause_number=num, clause_title=title,
                  clause_type=ClauseType.general, text=text)
def _score(num, s):
    return RiskScore(chunk_index=0, clause_number=num, clause_title='T',
                     score=s, risk_level='LOW', risk_factors=[], constraint_violations=[], recommendation='')

# S3 — score level mapping
def test_score_level_low():    assert _score_level(3) == 'LOW'
def test_score_level_medium(): assert _score_level(5) == 'MEDIUM'
def test_score_level_high():   assert _score_level(8) == 'HIGH'

# S2 — CONSTRAINT overrides (Python logic, not prompt)
def test_c010_uncapped_liability():
    c = _clause('5', 'Liability', 'The liability of each party shall be unlimited for any breach.')
    min_score, violations = _check_constraints(c, [])
    assert 'C-010' in violations, "C-010 must fire on uncapped liability"
    assert min_score >= 8

def test_c011_noncompete_too_long():
    c = _clause('6', 'Non-Compete', 'Employee agrees to a non-compete for 18 months after termination.')
    min_score, violations = _check_constraints(c, [])
    assert 'C-011' in violations, "C-011 must fire when non-compete > 12 months"
    assert min_score >= 7

def test_c011_noncompete_ok():
    c = _clause('6', 'Non-Compete', 'Employee agrees to a non-compete for 12 months.')
    _, violations = _check_constraints(c, [])
    assert 'C-011' not in violations, "C-011 must NOT fire at exactly 12 months"

def test_c013_no_arbitration():
    c = _clause('12', 'Governing Law', 'This agreement is governed by laws of Delaware. Courts of Delaware have jurisdiction.')
    _, violations = _check_constraints(c, [])
    assert 'C-013' in violations, "C-013 must fire when no arbitration in dispute clause"

def test_c014_short_notice():
    c = _clause('9', 'Termination', 'Either party may terminate with 30 days written notice.')
    _, violations = _check_constraints(c, [])
    assert 'C-014' in violations, "C-014 must fire when termination notice < 90 days"

# SB1 — knowledge nodes load
def test_loads_10_nodes():
    nodes = load_knowledge_nodes()
    assert len(nodes) == 10, f"Expected 10 knowledge nodes, got {len(nodes)}"

def test_nodes_have_required_ids():
    nodes = load_knowledge_nodes()
    ids = [n['id'] for n in nodes]
    for required in ['C-010', 'C-011', 'C-012', 'C-013', 'C-014',
                     'AP-010', 'AP-011', 'D-010', 'D-011', 'D-012']:
        assert required in ids, f"Missing knowledge node: {required}"

# S4 — risk delta computation
def test_risk_delta_increased():
    r = ComparisonResult(match_type=MatchType.MODIFIED, clause_number_v1='5',
                         clause_number_v2='5', clause_title='Liability',
                         similarity_score=0.6, diff_text=None, risk_delta=None,
                         score_v1=None, score_v2=None)
    updated = compute_risk_delta([_score('5', 3)], [_score('5', 8)], [r])
    assert updated[0].risk_delta == 'INCREASED'
    assert updated[0].score_v1 == 3
    assert updated[0].score_v2 == 8

def test_risk_delta_decreased():
    r = ComparisonResult(match_type=MatchType.MODIFIED, clause_number_v1='5',
                         clause_number_v2='5', clause_title='Liability',
                         similarity_score=0.6, diff_text=None, risk_delta=None,
                         score_v1=None, score_v2=None)
    updated = compute_risk_delta([_score('5', 8)], [_score('5', 3)], [r])
    assert updated[0].risk_delta == 'DECREASED'
```

### Run Layer 4 tests (non-API tests only first)
```powershell
python -m pytest src/scorer/test_scorer.py -v -k "not score_clause"
```

All green → commit:
```powershell
git add -A
git commit -m "Layer 4 — Scorer complete"
```

---

## API ROUTES (rules M1, M2, M3, F5)

### File: `backend/src/api/routes/analyse.py` — Mode A (rule M1)

```python
"""
POST /api/analyse — Mode A: single document risk heatmap
Rule M1: standalone, complete flow
Rule F5: API shape is fixed, frontend adapts to it
"""
from fastapi import APIRouter, UploadFile, File, HTTPException
import tempfile, os, shutil
from backend.src.extraction.extractor import extract
from backend.src.chunker.chunker import chunk
from backend.src.scorer.scorer import score_document
from backend.src.models.schemas import AnalyseResponse, RiskSummary

router = APIRouter()

@router.post("/api/analyse", response_model=AnalyseResponse)
async def analyse(file: UploadFile = File(...)):
    if not file.filename.endswith(('.pdf', '.docx', '.doc')):
        raise HTTPException(400, "Unsupported file type. Use .pdf or .docx")

    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        extraction = extract(tmp_path)
        clauses    = chunk(extraction)
        scores     = score_document(clauses)
    finally:
        os.unlink(tmp_path)

    summary = RiskSummary(
        high   = sum(1 for s in scores if s.risk_level == 'HIGH'),
        medium = sum(1 for s in scores if s.risk_level == 'MEDIUM'),
        low    = sum(1 for s in scores if s.risk_level == 'LOW'),
    )

    return AnalyseResponse(
        filename=file.filename,
        clauses=clauses,
        risk_scores=scores,
        risk_summary=summary,
    )
```

### File: `backend/src/api/routes/compare.py` — Mode B (rules M2, M3)

```python
"""
POST /api/compare — Mode B: two-document comparison
Rule M2: reuses Mode A logic for both docs, does not re-extract
Rule M3: net_delta is mandatory in response
Rule F5: API shape is fixed, frontend adapts
"""
from fastapi import APIRouter, UploadFile, File, HTTPException
import tempfile, os, shutil
from backend.src.extraction.extractor import extract
from backend.src.chunker.chunker import chunk
from backend.src.scorer.scorer import score_document, compute_risk_delta
from backend.src.comparator.comparator import compare
from backend.src.models.schemas import CompareResponse

router = APIRouter()

@router.post("/api/compare", response_model=CompareResponse)
async def compare_docs(file_v1: UploadFile = File(...), file_v2: UploadFile = File(...)):
    paths = []
    try:
        for f in [file_v1, file_v2]:
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(f.filename)[1]) as tmp:
                shutil.copyfileobj(f.file, tmp)
                paths.append(tmp.name)

        # Rule M2: same pipeline for both — no special-casing
        extraction_v1 = extract(paths[0])
        extraction_v2 = extract(paths[1])
        clauses_v1    = chunk(extraction_v1)
        clauses_v2    = chunk(extraction_v2)
        scores_v1     = score_document(clauses_v1)
        scores_v2     = score_document(clauses_v2)
        comparison    = compare(clauses_v1, clauses_v2)
        comparison    = compute_risk_delta(scores_v1, scores_v2, comparison)

        # Rule M3: net_delta is mandatory
        deltas = [r.risk_delta for r in comparison if r.risk_delta not in (None, 'N/A')]
        increased = deltas.count('INCREASED')
        decreased = deltas.count('DECREASED')
        if increased > decreased:    net_delta = 'INCREASED'
        elif decreased > increased:  net_delta = 'DECREASED'
        else:                        net_delta = 'UNCHANGED'

    finally:
        for p in paths:
            if os.path.exists(p): os.unlink(p)

    return CompareResponse(comparison=comparison, net_delta=net_delta)
```

### File: `backend/src/api/main.py`

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.src.api.routes.analyse import router as analyse_router
from backend.src.api.routes.compare import router as compare_router

app = FastAPI(title="ClauseIQ API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyse_router)
app.include_router(compare_router)

@app.get("/health")
def health():
    return {"status": "ok"}
```

### Run the backend
```powershell
cd C:\Users\USER\Desktop\ClauseIQ\backend
uvicorn src.api.main:app --reload --port 8000
```

Test it:
```powershell
curl http://localhost:8000/health
```

---

## LAYER 5 — FRONTEND (rules A4, F1, F2, F3, F4, F5)

### Setup (only after all backend layers pass tests — rule A4)
```powershell
cd C:\Users\USER\Desktop\ClauseIQ\frontend
npx create-next-app@latest . --typescript --tailwind --app --src-dir --no-import-alias
npm install
```

### Key components to build

**`src/components/UploadZone.tsx`**
- Drag-and-drop file input accepting `.pdf` and `.docx`
- Two modes: single file (Mode A) or two files (Mode B)
- On submit: POST to `/api/analyse` or `/api/compare`

**`src/components/RiskHeatmap.tsx`** (rule F1)
- List of clause cards, sorted by score descending
- Card colour: `score >= 7` → red bg, `score >= 4` → orange bg, else green bg
- Each card shows: clause number, title, score/10, risk_level badge
- CONSTRAINT violations shown as tags directly on card (rule F3 — not in tooltip)
- Example: `⚠ C-010 Uncapped liability` visible without clicking

**`src/components/ComparisonView.tsx`** (rules F2, F4)
- Side-by-side layout: v1 left column, v2 right column
- Status badge per row: UNCHANGED (gray) / MODIFIED (amber) / ADDED (green) / REMOVED (red)
- For MODIFIED rows: render word-level diff inline
  - Parse `diff_text` JSON array
  - `type: "remove"` → `<span style="text-decoration: line-through; color: red">`
  - `type: "add"` → `<span style="background: #d4edda; color: green">`
- Per-clause risk delta: ↑ INCREASED (red arrow), ↓ DECREASED (green arrow), = UNCHANGED (gray)
- Summary panel at top: "Net risk **INCREASED** — 3 clauses riskier, 1 clause safer" (rule F4)

**`src/app/page.tsx`**
- Toggle between Mode A and Mode B
- Mode A: shows UploadZone (single) → RiskHeatmap
- Mode B: shows UploadZone (two files) → ComparisonView

### Rule F5 enforcement
If building a UI component requires data not currently in the API response:
1. STOP
2. Add the field to the relevant Pydantic model in `backend/src/models/schemas.py`
3. Update the route that populates it
4. THEN build the UI component
Never build UI that relies on frontend-computed values that should come from the backend.

### Start frontend dev server
```powershell
cd C:\Users\USER\Desktop\ClauseIQ\frontend
npm run dev   # → http://localhost:3000
```

---

## SUBMISSION CHECKLIST (all items backed by memory layer rules)

Before demo day, verify every item:

```
[ ] SB3  — README.md has: env vars, backend run command, frontend run command, seed load instructions
[ ] SB3  — .env.example committed with placeholder values
[ ] D1   — supabase/schema.sql matches models/schemas.py exactly
[ ] SB1  — supabase/seed.sql has all 10 nodes; scorer loads them at startup without DB
[ ] C1   — chunker uses legal boundaries, never token/char splits
[ ] CP1  — comparator runs both L1 heading match AND L2 TF-IDF on every comparison
[ ] S1   — every scoring call injects all 10 knowledge nodes
[ ] S2   — CONSTRAINT overrides computed in Python, not prompt; verified by test_scorer.py
[ ] F1   — risk heatmap shows red/orange/green correctly
[ ] F2   — comparison is side-by-side with word-level diff
[ ] F3   — constraint violations visible on clause cards without interaction
[ ] F4   — per-clause delta arrows + net delta summary panel present
[ ] M3   — net_delta field in /api/compare response
[ ] T2   — run ndav1 vs ndav2 comparison, verify all known differences found
[ ] T3   — run one non-NDA contract through full pipeline; log result in evaluation/
[ ] SB5  — evaluation/ folder has surprise contract test output
[ ] SB2  — docs/architecture.md written with 3 sections (chunking, matching, scoring)
[ ] SB4  — git log shows clean commits: Layer 1 → Layer 2 → Layer 3 → Layer 4 → Frontend
[ ] SB4  — no .env in git history; run: git log --all --full-history -- .env
```

---

## KNOWN CONFLICTS WITH ASSESSMENT TEXT (do not revert these decisions)

### X1 — "Don't worry about OCR"
Assessment assumed clean DOCX test files. Our files are vector-drawn PDFs.
OCR is mandatory. Rule A5 holds. PyMuPDF returns empty strings on our files (verified).

### X2 — "Use PyMuPDF"
Assessment data flow says "python-docx / PyMuPDF". PyMuPDF fails on our files.
Rule A5: OCR pipeline only. This is not negotiable without re-verifying the files.

### X3 — Assessment merges extraction + chunking in one step
Rule A2 requires strict separation. Chunker takes plain text only — no file paths.
This enables independent testing of each layer and surprise contract readiness.

---

## DEMO SCRIPT (20-25 minutes)

**[0:00–3:00] Architecture walkthrough**
Show: extractor → chunker → comparator → scorer pipeline diagram.
Say: "Each layer is independent. The chunker works on any contract because it looks for
legal structure — numbered headings, UPPERCASE titles — not NDA-specific patterns."

**[3:00–7:00] Mode A — Single document heatmap (Scenario 2)**
Upload ndav1.pdf. Show risk heatmap.
Point to a HIGH clause. Show the CONSTRAINT node ID on the card.
Say: "Score is 8 not because the AI guessed — it's because C-010 fired: firm policy says
uncapped liability is automatically HIGH."

**[7:00–14:00] Mode B — Comparison (Scenario 1)**
Upload ndav1.pdf + ndav2.pdf. Show comparison view.
Walk through each change found. Show word-level diff on a MODIFIED clause.
Point to net delta summary. Say: "Net risk INCREASED — the added non-solicitation clause
triggered C-011: our firm policy caps non-compete at 12 months."

**[14:00–17:00] Semantic matching (Scenario 3)**
Show v1 Section 3 matched to v2 Section 9.0 despite different numbers.
Say: "Heading match alone would have called this REMOVED and ADDED. TF-IDF cosine
similarity recognised the same content restructured — correctly classified as MODIFIED."

**[17:00–20:00] Innovation**
Present your innovation feature (cross-reference detection, negotiation suggestions, etc.)

**[20:00–25:00] Surprise contract + Q&A**
Evaluator uploads unknown contract type. Run it live.
Chunker produces clauses → scorer fires CONSTRAINTs → comparison finds changes.
Expected response to "how would this scale to 200 contracts?":
"Same pipeline with a batch wrapper. 5 documents in parallel via asyncio.
Same chunker, same scorer, no code changes — just a loop."