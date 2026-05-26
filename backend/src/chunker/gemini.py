"""
Gemini-powered semantic chunker.

Calls Gemini with the contract markdown, parses the JSON response,
filters boilerplate, splits oversized chunks, and builds Clause objects.

Public interface:
    gemini_chunk(extraction: ExtractionResult) -> list[Clause]
"""

import os
import re
import json

from ..extraction.extractor import ExtractionResult
from ..models.schemas import Clause
from ..prompts.chunker_prompt import SYSTEM_INSTRUCTION, build_chunker_prompt
from .helpers import safe_type, is_boilerplate, split_oversized


# ──────────────────────────────────────────────────────────────────────────────
# GEMINI API CALL
# ──────────────────────────────────────────────────────────────────────────────

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
    prompt   = build_chunker_prompt(markdown)
    response = client.models.generate_content(
        model="gemini-3.1-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.1,
            max_output_tokens=32768,
        ),
    )

    raw = response.text.strip()

    # Strip markdown fences if Gemini adds them despite instructions
    raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'```\s*$',          '', raw, flags=re.MULTILINE)
    raw = raw.strip()

    return json.loads(raw)


# ──────────────────────────────────────────────────────────────────────────────
# GEMINI CHUNK PIPELINE
# ──────────────────────────────────────────────────────────────────────────────

def gemini_chunk(extraction: ExtractionResult) -> list[Clause]:
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
        c_type    = safe_type(str(item.get("clause_type", "general")))
        page_num  = item.get("page_number")
        text_body = str(item.get("text", "")).strip()

        if not text_body:
            continue

        # Safety net: drop boilerplate Gemini still returned
        if is_boilerplate(title, text_body):
            continue

        # Oversized split: produce 2-3 sub-chunks if needed
        pieces = split_oversized(text_body)

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
