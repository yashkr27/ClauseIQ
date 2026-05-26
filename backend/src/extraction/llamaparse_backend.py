"""
LlamaParse extraction backend.

Calls the LlamaParse cloud API to convert a PDF/DOCX into structured
markdown, one Document object per page.  Page markers are embedded so
downstream components know which page each clause lives on.

Public interface:
    extract_llamaparse(file_path: str) -> tuple[str, list[dict], int]

Raises:
    EnvironmentError  — LLAMA_CLOUD_API_KEY not set
    ValueError        — API returned no documents, or all pages were empty
    RuntimeError      — any API / network error from llama_parse
"""

import logging
import os

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# PAGE MARKER HELPER  (shared with the fallback module via extractor.py)
# ──────────────────────────────────────────────────────────────────────────────

def embed_page_markers(documents) -> tuple[str, list[dict]]:
    """
    Takes a list of objects with a `.text` attribute (one per page).
    Returns (full_markdown_with_markers, page_texts list).

    Page markers look like:  <!-- PAGE 2 -->
    Gemini reads them to determine which page each clause starts on.
    """
    full_parts  = []
    page_texts  = []
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

        if not page_text:
            logger.warning("LlamaParse: page %d returned empty text", page_num)
        else:
            logger.debug(
                "LlamaParse: page %d — %d chars (preview: %s…)",
                page_num, len(page_text), page_text[:80].replace("\n", " "),
            )

    return "".join(full_parts).strip(), page_texts


# ──────────────────────────────────────────────────────────────────────────────
# LLAMAPARSE EXTRACTOR
# ──────────────────────────────────────────────────────────────────────────────

def extract_llamaparse(file_path: str) -> tuple[str, list[dict], int]:
    """
    Call the LlamaParse cloud API and return structured markdown.

    Returns:
        (markdown_with_page_markers, page_texts, page_count)

    Raises:
        EnvironmentError  — if LLAMA_CLOUD_API_KEY is not set
        ValueError        — if API returned no documents or all pages empty
        RuntimeError      — wraps any API/network exception
    """
    from llama_parse import LlamaParse  # lazy import — avoids import warning when key not set

    api_key = os.getenv("LLAMA_CLOUD_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "LLAMA_CLOUD_API_KEY is not set. "
            "Add it to your .env file or environment variables."
        )

    logger.info("LlamaParse: starting extraction for %s", file_path)

    try:
        parser = LlamaParse(
            api_key=api_key,
            result_type="markdown",   # structured markdown preserving tables/headings
            verbose=False,
            language="en",
            split_by_page=True,       # one Document object per page
        )
        documents = parser.load_data(file_path)
    except Exception as exc:
        raise RuntimeError(
            f"LlamaParse API call failed for '{file_path}': {exc}"
        ) from exc

    # ── Validate response ─────────────────────────────────────────────────────

    if not documents:
        raise ValueError(
            f"LlamaParse returned 0 documents for '{file_path}'. "
            "The file may be corrupt, password-protected, or unsupported."
        )

    logger.info("LlamaParse: received %d page(s) from API", len(documents))

    # Detect completely empty extraction (all pages blank)
    non_empty = [d for d in documents if (d.text or "").strip()]
    if not non_empty:
        raise ValueError(
            f"LlamaParse returned {len(documents)} document(s) but ALL pages are empty "
            f"for '{file_path}'. "
            "This usually means the PDF is image-only/scanned without OCR enabled, "
            "or the LlamaParse API returned malformed content. "
            "Falling back to PyMuPDF."
        )

    if len(non_empty) < len(documents):
        logger.warning(
            "LlamaParse: %d of %d pages were empty — partial extraction. "
            "Consider enabling OCR on your LlamaParse plan.",
            len(documents) - len(non_empty),
            len(documents),
        )

    # ── Build output ──────────────────────────────────────────────────────────

    full_markdown, page_texts = embed_page_markers(documents)

    total_chars = sum(len(pt["text"]) for pt in page_texts)
    logger.info(
        "LlamaParse: extraction complete — %d pages, %d total chars",
        len(documents), total_chars,
    )

    return full_markdown, page_texts, len(documents)
