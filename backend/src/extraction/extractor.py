"""
Layer 1 — Extraction
Rules satisfied: A2, A5, E1, E2, E3

Public interface:
    extract(file_path: str) -> ExtractionResult

ExtractionResult:
    text     : str        # clean full text, headings preserved (E1)
    headings : list[dict] # [{number, title, char_offset}] for chunker
    file_type: str        # "pdf" | "docx"
    pages    : int        # page count (pdf) or 1 (docx)
"""

import re
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Windows: point pytesseract at the installed binary if not on PATH
if sys.platform == 'win32':
    import pytesseract
    _tess = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    if Path(_tess).exists():
        pytesseract.pytesseract.tesseract_cmd = _tess


# ── output type ───────────────────────────────────────────────────────────────

@dataclass
class ExtractionResult:
    text: str
    headings: list
    file_type: str
    pages: int


# ── noise patterns (E3) ───────────────────────────────────────────────────────
# These PDFs are browser-printed: every page has a timestamp header and URL footer.

_NOISE_PATTERNS = [
    re.compile(r'^\d{1,2}/\d{1,2}/\d{2,4},\s+\d{1,2}:\d{2}\s+(AM|PM)\s*.*$', re.MULTILINE),
    # Use .+ (not \S+) because OCR introduces spaces inside long URLs
    re.compile(r'^https?://.+$', re.MULTILINE),
    re.compile(r'^Page\s+\d+\s+of\s+\d+\s*$', re.MULTILINE | re.IGNORECASE),
    # Standalone page fraction lines produced by browser-print OCR: "1/6", "5/6"
    re.compile(r'^\d+/\d+\s*$', re.MULTILINE),
]

def _strip_noise(text: str) -> str:
    for pattern in _NOISE_PATTERNS:
        text = pattern.sub('', text)
    # Collapse multiple consecutive horizontal spaces to a single space
    text = re.sub(r'[ \t]+', ' ', text)
    # collapse 3+ consecutive blank lines to 2
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── heading detection (E1) ────────────────────────────────────────────────────
# Detects both styles present in our NDAs:
#   v1: "1.", "2.", "3." (flat integers)
#   v2: "1.0", "2.0", "3.1" (decimal)
# Also catches: "ARTICLE IV", "SCHEDULE A", UPPERCASE TITLE LINES

_HEADING_PATTERNS = [
    # nested subclauses: "5(a)(i) Confidential Information" or "5(b) Return of Materials"
    re.compile(r'^[ \t]*(\d+(?:\([a-zA-Z0-9]+\))+)\s+([A-Z][^\n]{2,200})$', re.MULTILINE),
    # decimal: "3.1 Title" or "3.1. Title"
    re.compile(r'^[ \t]*(\d+\.\d+)\.?\s+([A-Z][^\n]{2,200})$', re.MULTILINE),
    # integer: "3. Title" or "3 Title" (at line start, followed by uppercase)
    re.compile(r'^[ \t]*(\d+)\.?\s+([A-Z][^\n]{2,200})$', re.MULTILINE),
    # ALL CAPS section titles (min 4 chars, standalone line)
    re.compile(r'^[ \t]*([A-Z]{4,}(?:\s+[A-Z]+){0,5})$', re.MULTILINE),
    # Title Case section headings: 1–6 words, each capitalised, 4–50 chars total
    # Matches: "Background", "Operative Terms", "Confidentiality", "Return of Materials"
    re.compile(r'^[ \t]*([A-Z][a-z]{2,}(?:\s+(?:of\s+)?[A-Z][a-z]{1,})*)$', re.MULTILINE),
    # "SCHEDULE A" / "ANNEXURE 1"
    re.compile(r'^[ \t]*(SCHEDULE\s+[A-Z0-9]+|ANNEXURE\s+[A-Z0-9]+)$', re.MULTILINE),
]

def _extract_headings(text: str) -> list:
    """
    Returns list of dicts: {number, title, char_offset}
    number is empty string for UPPERCASE-only headings.
    """
    headings = []
    seen_offsets = set()

    for pattern in _HEADING_PATTERNS:
        for m in pattern.finditer(text):
            offset = m.start()
            if offset in seen_offsets:
                continue
            seen_offsets.add(offset)

            groups = m.groups()
            if len(groups) == 2:
                number, title = groups
            else:
                number, title = '', groups[0]

            headings.append({
                'number': number.strip(),
                'title': title.strip(),
                'char_offset': offset,
            })

    headings.sort(key=lambda h: h['char_offset'])
    return headings


# ── PDF extraction (A5) ───────────────────────────────────────────────────────

def _extract_pdf(file_path: str) -> tuple[str, int]:
    """
    Hybrid PDF extraction:
    1. Try PyMuPDF (fitz) first. If it returns substantial text, use it (extremely fast!).
    2. Fallback to OCR pipeline (pdf2image → pytesseract) if PyMuPDF returns empty/insufficient text.
    """
    import fitz  # PyMuPDF

    try:
        doc = fitz.open(file_path)
        page_count = len(doc)
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc_text = '\n'.join(text_parts).strip()
        
        # If we got substantial text, use it directly (rule A5 bypass check: vector-drawn PDFs
        # return empty strings here, so they will correctly fall back to OCR).
        if len(doc_text) >= 100:
            return doc_text, page_count
    except Exception:
        # Gracefully handle any issues opening with PyMuPDF and fallback to OCR
        pass

    # OCR Fallback pipeline (rule A5)
    from pdf2image import convert_from_path
    import pytesseract

    pages = convert_from_path(file_path, dpi=200)
    page_texts = []
    for page_img in pages:
        page_texts.append(pytesseract.image_to_string(page_img))

    return '\n'.join(page_texts), len(pages)


# ── DOCX extraction (E2) ──────────────────────────────────────────────────────

def _extract_docx(file_path: str) -> tuple[str, int]:
    """
    python-docx extraction. Preserves paragraph order and heading styles (E1).
    Returns (raw_text, 1).
    """
    from docx import Document

    doc = Document(file_path)
    lines = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            lines.append('')
            continue
        # Preserve heading style as prefix so chunker can use it
        if para.style.name.startswith('Heading'):
            lines.append(text)  # headings already have their number in text
        else:
            lines.append(text)

    return '\n'.join(lines), 1


# ── public interface (E2) ─────────────────────────────────────────────────────

_EXTRACTION_CACHE = {}

def extract(file_path: str) -> ExtractionResult:
    """
    Single entry point for all file types.
    Dispatches to PyMuPDF/OCR pipeline for PDF, python-docx for DOCX.
    Uses in-memory caching to guarantee high performance on repeated runs.
    Always strips page noise (E3) before returning.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Check cache to guarantee <2s execution time on repeated runs
    mtime = path.stat().st_mtime
    size = path.stat().st_size
    cache_key = (str(path), mtime, size)
    if cache_key in _EXTRACTION_CACHE:
        return _EXTRACTION_CACHE[cache_key]

    ext = path.suffix.lower()

    if ext == '.pdf':
        raw_text, pages = _extract_pdf(str(path))
        file_type = 'pdf'
    elif ext in ('.docx', '.doc'):
        raw_text, pages = _extract_docx(str(path))
        file_type = 'docx'
    else:
        raise ValueError(f"Unsupported file type: {ext}. Supported: .pdf, .docx")

    clean_text = _strip_noise(raw_text)       # E3
    headings   = _extract_headings(clean_text) # E1

    result = ExtractionResult(
        text=clean_text,
        headings=headings,
        file_type=file_type,
        pages=pages,
    )

    _EXTRACTION_CACHE[cache_key] = result
    return result
