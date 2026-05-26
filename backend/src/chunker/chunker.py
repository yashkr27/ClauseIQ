"""
Layer 2 — Semantic Chunker

Public interface:
    chunk(extraction: ExtractionResult) -> list[Clause]

Strategy:
    Gemini semantic chunking (primary) → regex boundary detection (fallback).
    Both paths use shared helpers from chunker.helpers and the prompt
    from prompts.chunker_prompt.
"""

from ..extraction.extractor import ExtractionResult
from ..models.schemas import Clause
from .gemini import gemini_chunk
from .regex import regex_chunk


def chunk(extraction: ExtractionResult) -> list[Clause]:
    """
    Try Gemini semantic chunking first.
    Fall back to regex chunker if Gemini is unavailable or returns bad JSON.
    """
    try:
        clauses = gemini_chunk(extraction)
        if clauses:
            return clauses
        raise ValueError("Gemini returned 0 clauses")
    except Exception:
        return regex_chunk(extraction)