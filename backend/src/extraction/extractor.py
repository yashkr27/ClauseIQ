"""
Layer 1 — Extraction (v2)
Rules satisfied: A2, A5, E1, E2, E3

Public interface:
    extract(file_path: str) -> ExtractionResult

ExtractionResult:
    text       : str         # full markdown (page markers embedded)
    markdown   : str         # alias for text
    headings   : list[dict]  # kept for backward compat — now empty (Gemini chunks instead)
    file_type  : str         # "pdf" | "docx"
    pages      : int         # page count from LlamaParse
    page_texts : list[dict]  # [{"page": 1, "text": "...", "char_start": N, "char_end": M}]

Pipeline:
    LlamaParse (primary) → structured markdown per page → page markers embedded
    PyMuPDF   (fallback) → plain text if LlamaParse unavailable
"""

import os
import re
import hashlib
from dataclasses import dataclass, field
from pathlib import Path


# ── Output type ───────────────────────────────────────────────────────────────

@dataclass
class ExtractionResult:
    text:       str              # full text with <!-- PAGE N --> markers
    markdown:   str              # same as text (alias for Gemini chunker)
    headings:   list             # kept for backward compat — now always []
    file_type:  str
    pages:      int
    page_texts: list = field(default_factory=list)
    # [{"page": int, "text": str, "char_start": int, "char_end": int}]


# ── In-memory cache ───────────────────────────────────────────────────────────

_EXTRACTION_CACHE: dict = {}


def _file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


# ── Page marker helpers ───────────────────────────────────────────────────────

def _embed_page_markers(documents) -> tuple[str, list[dict]]:
    """
    Takes a list of LlamaParse Document objects (one per page).
    Returns (full_markdown_with_markers, page_texts).

    Page markers look like:  <!-- PAGE 2 -->
    Gemini reads them to determine which page each clause is on.
    """
    full_parts = []
    page_texts = []
    char_offset = 0

    for i, doc in enumerate(documents):
        page_num  = i + 1
        marker    = f"\n\n<!-- PAGE {page_num} -->\n\n"
        page_text = (doc.text or "").strip()

        full_parts.append(marker + page_text)

        page_texts.append({
            "page":       page_num,
            "text":       page_text,
            "char_start": char_offset + len(marker),
            "char_end":   char_offset + len(marker) + len(page_text),
        })
        char_offset += len(marker) + len(page_text)

    return "".join(full_parts).strip(), page_texts


# ── Primary: LlamaParse ───────────────────────────────────────────────────────

def _extract_llamaparse(file_path: str) -> tuple[str, list[dict], int]:
    """
    Calls LlamaParse cloud API.
    Returns (markdown_with_page_markers, page_texts, page_count).
    Raises if LLAMA_CLOUD_API_KEY is missing or call fails.
    """
    from llama_parse import LlamaParse

    api_key = os.getenv("LLAMA_CLOUD_API_KEY")
    if not api_key:
        raise EnvironmentError("LLAMA_CLOUD_API_KEY not set")

    parser = LlamaParse(
        api_key=api_key,
        result_type="markdown",   # structured markdown preserving tables, headings
        verbose=False,
        language="en",
        # Parse each page separately so we get a Document per page
        split_by_page=True,
    )

    documents = parser.load_data(file_path)

    if not documents:
        raise ValueError("LlamaParse returned no content")

    full_markdown, page_texts = _embed_page_markers(documents)
    return full_markdown, page_texts, len(documents)


# ── Fallback: PyMuPDF ─────────────────────────────────────────────────────────

def _extract_fallback(file_path: str) -> tuple[str, list[dict], int]:
    """
    Plain-text fallback using PyMuPDF (PDF) or python-docx (DOCX).
    Embeds page markers in the same format so downstream is unchanged.
    """
    ext = Path(file_path).suffix.lower()

    if ext == '.pdf':
        import fitz
        doc        = fitz.open(file_path)
        page_count = len(doc)
        documents  = []

        class _FakePage:
            def __init__(self, text): self.text = text

        for page in doc:
            documents.append(_FakePage(page.get_text()))
        doc.close()

    elif ext in ('.docx', '.doc'):
        from docx import Document
        doc   = Document(file_path)
        lines = [p.text.strip() for p in doc.paragraphs]
        documents = [type('P', (), {'text': '\n'.join(lines)})()]
        page_count = 1
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    full_text, page_texts = _embed_page_markers(documents)
    return full_text, page_texts, page_count


# ── Noise stripping (kept for fallback path) ──────────────────────────────────

_NOISE_PATTERNS = [
    re.compile(r'^\d{1,2}/\d{1,2}/\d{2,4},\s+\d{1,2}:\d{2}\s+(AM|PM)\s*.*$', re.MULTILINE),
    re.compile(r'^https?://.+$', re.MULTILINE),
    re.compile(r'^Page\s+\d+\s+of\s+\d+\s*$', re.MULTILINE | re.IGNORECASE),
    re.compile(r'^\d+/\d+\s*$', re.MULTILINE),
]

def _strip_noise(text: str) -> str:
    for pattern in _NOISE_PATTERNS:
        text = pattern.sub('', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── Public interface ──────────────────────────────────────────────────────────

def extract(file_path: str) -> ExtractionResult:
    """
    Single entry point. Tries LlamaParse first, falls back to PyMuPDF/docx.
    Caches by file digest so repeated calls in the same process are instant.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext       = path.suffix.lower()
    cache_key = (ext, path.stat().st_size, _file_digest(path))
    if cache_key in _EXTRACTION_CACHE:
        return _EXTRACTION_CACHE[cache_key]

    # ── Try LlamaParse ────────────────────────────────────────────────────────
    used_llamaparse = True
    try:
        full_text, page_texts, pages = _extract_llamaparse(str(path))
    except Exception as llama_err:
        used_llamaparse = False
        try:
            full_text, page_texts, pages = _extract_fallback(str(path))
            full_text = _strip_noise(full_text)
        except Exception as fallback_err:
            raise RuntimeError(
                f"Both extractors failed.\n"
                f"  LlamaParse: {llama_err}\n"
                f"  Fallback:   {fallback_err}"
            )

    file_type = 'pdf' if ext == '.pdf' else 'docx'

    result = ExtractionResult(
        text=full_text,
        markdown=full_text,
        headings=[],          # Gemini chunker reads markdown directly
        file_type=file_type,
        pages=pages,
        page_texts=page_texts,
    )

    _EXTRACTION_CACHE[cache_key] = result
    return result


# ── Page lookup utility (used by chunker) ─────────────────────────────────────

def page_for_offset(char_offset: int, page_texts: list[dict]) -> int | None:
    """
    Given a character offset in the full markdown, returns the page number.
    Used by the Gemini chunker as a cross-check when LlamaParse page markers
    are ambiguous.
    """
    for pt in page_texts:
        if pt["char_start"] <= char_offset < pt["char_end"]:
            return pt["page"]
    return None