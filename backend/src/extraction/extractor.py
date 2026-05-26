"""
Layer 1 — Extraction (v3)

Public interface:
    extract(file_path: str) -> ExtractionResult

Pipeline:
    LlamaParse (primary)  → structured markdown + page markers
    PyMuPDF / docx (fallback) → plain text when LlamaParse unavailable/empty

Backends live in:
    extraction/llamaparse_backend.py  — LlamaParse cloud API
    extraction/fallback_backend.py    — PyMuPDF / python-docx

Logging:
    Configure via standard logging.  At INFO level you see which backend
    ran and how much content was extracted.  At DEBUG level you see
    per-page previews.  Fallback reasons are always logged at WARNING.
"""

import hashlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from .llamaparse_backend import extract_llamaparse
from .fallback_backend import extract_fallback

# ── Logging setup ─────────────────────────────────────────────────────────────
# Configure the root 'src.extraction' logger from the LOG_LEVEL env var.
# Uvicorn's own logging propagates to root, so this shows in the server console.

_log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=getattr(logging, _log_level, logging.INFO),
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# OUTPUT TYPE
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ExtractionResult:
    text:       str              # full text with <!-- PAGE N --> markers
    markdown:   str              # same as text (alias for Gemini chunker)
    headings:   list             # kept for backward compat — always []
    file_type:  str              # "pdf" | "docx"
    pages:      int
    page_texts: list = field(default_factory=list)
    # page_texts: [{"page": int, "text": str, "char_start": int, "char_end": int}]
    extracted_by: str = "unknown"   # "llamaparse" | "fallback" — useful for debugging


# ──────────────────────────────────────────────────────────────────────────────
# IN-MEMORY CACHE
# ──────────────────────────────────────────────────────────────────────────────

_EXTRACTION_CACHE: dict = {}


def _file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC INTERFACE
# ──────────────────────────────────────────────────────────────────────────────

def extract(file_path: str) -> ExtractionResult:
    """
    Single entry point.  Tries LlamaParse first, falls back to PyMuPDF/docx.
    Caches by file content digest so repeated calls in the same process are instant.

    Logs clearly at every decision point so you can see in the server console:
      - Which backend was attempted
      - Why LlamaParse failed (if it did)
      - How much content was extracted
      - Whether the fallback was used
    """
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext       = path.suffix.lower()
    cache_key = (ext, path.stat().st_size, _file_digest(path))

    if cache_key in _EXTRACTION_CACHE:
        cached = _EXTRACTION_CACHE[cache_key]
        logger.info(
            "Cache hit for '%s' (extracted_by=%s, %d chars)",
            path.name, cached.extracted_by, len(cached.text),
        )
        return cached

    file_type    = 'pdf' if ext == '.pdf' else 'docx'
    extracted_by = "unknown"

    # ── Attempt 1: LlamaParse ─────────────────────────────────────────────────
    full_text  = None
    page_texts = None
    pages      = None
    llama_err  = None

    try:
        logger.info("Extraction: trying LlamaParse for '%s'", path.name)
        full_text, page_texts, pages = extract_llamaparse(str(path))
        extracted_by = "llamaparse"
        logger.info(
            "Extraction: LlamaParse succeeded — %d pages, %d chars",
            pages, len(full_text),
        )
    except Exception as exc:
        llama_err = exc
        logger.warning(
            "Extraction: LlamaParse FAILED for '%s' — reason: %s. "
            "Falling back to PyMuPDF/docx.",
            path.name, exc,
        )

    # ── Attempt 2: Fallback ───────────────────────────────────────────────────
    if full_text is None:
        try:
            logger.info("Extraction: trying fallback (PyMuPDF/docx) for '%s'", path.name)
            full_text, page_texts, pages = extract_fallback(str(path))
            extracted_by = "fallback"
            logger.info(
                "Extraction: fallback succeeded — %d pages, %d chars",
                pages, len(full_text),
            )
        except Exception as fallback_err:
            raise RuntimeError(
                f"Both extractors failed for '{path.name}'.\n"
                f"  LlamaParse : {llama_err}\n"
                f"  Fallback   : {fallback_err}"
            ) from fallback_err

    # ── Warn if content is suspiciously thin ─────────────────────────────────
    actual_content = len(full_text.replace("<!-- PAGE", "").replace("-->", "").strip())
    if actual_content < 200:
        logger.warning(
            "Extraction: result for '%s' is very thin (%d content chars, backend=%s). "
            "The document may be image-only or the extraction failed silently.",
            path.name, actual_content, extracted_by,
        )

    result = ExtractionResult(
        text=full_text,
        markdown=full_text,
        headings=[],
        file_type=file_type,
        pages=pages,
        page_texts=page_texts,
        extracted_by=extracted_by,
    )

    _EXTRACTION_CACHE[cache_key] = result
    return result


# ──────────────────────────────────────────────────────────────────────────────
# PAGE LOOKUP UTILITY  (used by chunker)
# ──────────────────────────────────────────────────────────────────────────────

def page_for_offset(char_offset: int, page_texts: list[dict]) -> int | None:
    """
    Given a character offset in the full markdown, returns the page number.
    """
    for pt in page_texts:
        if pt["char_start"] <= char_offset < pt["char_end"]:
            return pt["page"]
    return None