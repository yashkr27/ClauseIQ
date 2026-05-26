"""
PyMuPDF / python-docx fallback extraction backend.

Used when LlamaParse is unavailable, returns empty content, or errors.
Extracts plain text from PDFs page-by-page (PyMuPDF) or full-doc (python-docx).

Public interface:
    extract_fallback(file_path: str) -> tuple[str, list[dict], int]

Note: This path strips noise (timestamps, URLs, page numbers) that LlamaParse
handles automatically. Image-only PDFs will return empty text — the caller
should handle this gracefully.
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# NOISE STRIPPING
# ──────────────────────────────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────────────────────────────
# PAGE MARKER HELPER  (same shape as llamaparse_backend.embed_page_markers)
# ──────────────────────────────────────────────────────────────────────────────

def _embed_page_markers(pages: list[str]) -> tuple[str, list[dict]]:
    """
    Takes a list of plain-text page strings.
    Returns (full_text_with_markers, page_texts list).
    """
    full_parts  = []
    page_texts  = []
    char_offset = 0

    for i, page_text in enumerate(pages):
        page_num = i + 1
        marker   = f"\n\n<!-- PAGE {page_num} -->\n\n"

        full_parts.append(marker + page_text)

        page_texts.append({
            "page":       page_num,
            "text":       page_text,
            "char_start": char_offset + len(marker),
            "char_end":   char_offset + len(marker) + len(page_text),
        })
        char_offset += len(marker) + len(page_text)

        if not page_text.strip():
            logger.warning("Fallback: page %d is empty (likely image-only)", page_num)
        else:
            logger.debug(
                "Fallback: page %d — %d chars (preview: %s…)",
                page_num, len(page_text), page_text[:80].replace("\n", " "),
            )

    return "".join(full_parts).strip(), page_texts


# ──────────────────────────────────────────────────────────────────────────────
# PDF via PyMuPDF
# ──────────────────────────────────────────────────────────────────────────────

def _extract_pdf(file_path: str) -> tuple[str, list[dict], int]:
    import fitz  # PyMuPDF

    logger.info("Fallback: opening PDF with PyMuPDF — %s", file_path)

    doc = fitz.open(file_path)
    page_count = len(doc)
    logger.info("Fallback: PDF has %d page(s)", page_count)

    pages = []
    for i, page in enumerate(doc):
        raw = page.get_text()
        cleaned = _strip_noise(raw)
        pages.append(cleaned)
        if not cleaned.strip():
            logger.warning(
                "Fallback: PDF page %d/%d returned no text — "
                "page may be image-only (no embedded text layer). "
                "Consider using LlamaParse with OCR enabled.",
                i + 1, page_count,
            )
    doc.close()

    full_text, page_texts = _embed_page_markers(pages)

    total_chars = sum(len(p) for p in pages)
    logger.info(
        "Fallback (PyMuPDF): done — %d pages, %d total chars extracted",
        page_count, total_chars,
    )

    if total_chars == 0:
        logger.error(
            "Fallback (PyMuPDF): ALL pages returned empty text for '%s'. "
            "The PDF appears to be entirely image-based. "
            "LlamaParse with OCR is required for this document.",
            file_path,
        )

    return full_text, page_texts, page_count


# ──────────────────────────────────────────────────────────────────────────────
# DOCX via python-docx
# ──────────────────────────────────────────────────────────────────────────────

def _extract_docx(file_path: str) -> tuple[str, list[dict], int]:
    from docx import Document

    logger.info("Fallback: opening DOCX with python-docx — %s", file_path)

    doc   = Document(file_path)
    lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    text  = _strip_noise("\n".join(lines))

    logger.info(
        "Fallback (python-docx): extracted %d chars from %d paragraphs",
        len(text), len(lines),
    )

    full_text, page_texts = _embed_page_markers([text])
    return full_text, page_texts, 1


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC INTERFACE
# ──────────────────────────────────────────────────────────────────────────────

def extract_fallback(file_path: str) -> tuple[str, list[dict], int]:
    """
    Extract plain text using PyMuPDF (PDF) or python-docx (DOCX).
    Embeds <!-- PAGE N --> markers in the same format as LlamaParse backend.

    Returns:
        (full_text_with_page_markers, page_texts, page_count)

    Raises:
        ValueError  — unsupported file type
    """
    ext = Path(file_path).suffix.lower()

    if ext == '.pdf':
        return _extract_pdf(file_path)
    elif ext in ('.docx', '.doc'):
        return _extract_docx(file_path)
    else:
        raise ValueError(
            f"Unsupported file type '{ext}' for fallback extractor. "
            "Supported: .pdf, .docx, .doc"
        )
