"""
POST /api/compare — Mode B: two-document comparison
Rule M2: reuses Mode A logic for both docs, does not re-extract
Rule M3: net_delta is mandatory in response
Rule F5: API shape is fixed, frontend adapts
"""

from fastapi import APIRouter, UploadFile, File, HTTPException
import tempfile

import os
import shutil

from ...extraction.cleaner import clean
from ...extraction.extractor import extract
from ...chunker.chunker import chunk
from ...scorer.scorer import (
    score_document,
    compute_risk_delta,
    suggest_negotiation
)
from ...comparator.comparator import compare
from ...models.schemas import CompareResponse
from ...db import db_available, get_client

router = APIRouter()

MAX_BYTES = 20 * 1024 * 1024


def _persist_doc(filename: str, extraction, clauses, scores):
    """
    Persist a single document and return:
    {
        "doc_id": str,
        "clause_uuid_map": dict[str, str]
    }

    IMPORTANT:
    - risk_scores.chunk_id must reference document_chunks.id (UUID)
    - comparison_results.chunk_v1_id/v2_id must reference document_chunks.id
    """

    try:
        client = get_client()

        # ─────────────────────────────────────────────────────────────
        # documents
        # ─────────────────────────────────────────────────────────────
        doc_row = client.table("documents").insert({
            "filename": filename,
            "content_text": extraction.text[:5000],
        }).execute().data[0]

        doc_id = doc_row["id"]

        # clause_number -> document_chunks.id
        clause_uuid_map = {}

        # ─────────────────────────────────────────────────────────────
        # document_chunks
        # ─────────────────────────────────────────────────────────────
        for c in clauses:

            chunk_row = client.table("document_chunks").insert({
                "document_id": doc_id,
                "chunk_index": c.chunk_index,
                "clause_number": c.clause_number,
                "clause_title": c.clause_title,
                "clause_type": c.clause_type,
                "text": c.text,
            }).execute().data[0]

            clause_uuid_map[c.clause_number] = chunk_row["id"]

        # ─────────────────────────────────────────────────────────────
        # risk_scores
        # FIX:
        # chunk_id must be UUID FK, NOT chunk_index integer
        # ─────────────────────────────────────────────────────────────
        for s in scores:

            chunk_uuid = clause_uuid_map.get(s.clause_number)

            if not chunk_uuid:
                print(f"Missing chunk UUID for clause: {s.clause_number}")
                continue

            client.table("risk_scores").insert({
                "chunk_id": chunk_uuid,
                "score": s.score,
                "risk_factors": s.risk_factors,
                "constraint_violations": s.constraint_violations,
                "recommendation": s.recommendation,
            }).execute()

        return {
            "doc_id": doc_id,
            "clause_uuid_map": clause_uuid_map
        }

    except Exception as e:
        print("PERSIST DOC FAILED")
        print(str(e))
        return None


def _persist_compare(comparison, v1_data, v2_data):
    """
    Persist comparison results.

    FIX:
    comparison_results.chunk_v1_id/chunk_v2_id
    must reference document_chunks.id UUIDs,
    NOT clause labels like '5.2' or '11A'
    """

    try:
        client = get_client()

        v1_map = v1_data["clause_uuid_map"]
        v2_map = v2_data["clause_uuid_map"]

        for r in comparison:

            chunk_v1_id = (
                v1_map.get(r.clause_number_v1)
                if r.clause_number_v1 else None
            )

            chunk_v2_id = (
                v2_map.get(r.clause_number_v2)
                if r.clause_number_v2 else None
            )

            payload = {
                "doc_v1_id": v1_data["doc_id"],
                "doc_v2_id": v2_data["doc_id"],
                "chunk_v1_id": chunk_v1_id,
                "chunk_v2_id": chunk_v2_id,
                "match_type": r.match_type,
                "similarity_score": r.similarity_score,
                "diff_text": r.diff_text,
            }

            result = client.table("comparison_results").insert(payload).execute()

            # Optional debugging visibility
            if not result.data:
                print("Comparison insert returned no data")
                print(payload)

    except Exception as e:
        print("COMPARE PERSIST FAILED")
        print(str(e))


@router.post("/api/compare", response_model=CompareResponse)
async def compare_docs(
    file_v1: UploadFile = File(...),
    file_v2: UploadFile = File(...)
):

    paths = []

    extraction_v1 = None
    extraction_v2 = None

    clauses_v1 = []
    clauses_v2 = []

    scores_v1 = []
    scores_v2 = []

    comparison = []
    suggestions = []

    net_delta = "UNCHANGED"

    try:

        # ─────────────────────────────────────────────────────────────
        # Validation + temp file creation
        # ─────────────────────────────────────────────────────────────
        for f in [file_v1, file_v2]:

            filename = f.filename or "contract.pdf"

            if not filename.lower().endswith((".pdf", ".docx", ".doc")):
                raise HTTPException(
                    status_code=400,
                    detail="Unsupported file type. Use .pdf or .docx"
                )

            ext = os.path.splitext(filename)[1]

            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=ext
            ) as tmp:

                shutil.copyfileobj(f.file, tmp)
                paths.append(tmp.name)

            file_size = os.path.getsize(paths[-1])

            if file_size > MAX_BYTES:
                raise HTTPException(
                    status_code=400,
                    detail="File exceeds 20 MB limit."
                )

            if file_size == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Uploaded file is empty."
                )

        # ─────────────────────────────────────────────────────────────
        # Rule M2:
        # Same pipeline for both documents
        # ─────────────────────────────────────────────────────────────
        extraction_v1 = extract(paths[0])
        extraction_v1 = clean(extraction_v1)
        
        extraction_v2 = extract(paths[1])
        extraction_v2 = clean(extraction_v2)

        clauses_v1 = chunk(extraction_v1)
        clauses_v2 = chunk(extraction_v2)

        scores_v1 = score_document(clauses_v1)
        scores_v2 = score_document(clauses_v2)

        # ─────────────────────────────────────────────────────────────
        # Compare
        # ─────────────────────────────────────────────────────────────
        comparison = compare(clauses_v1, clauses_v2)

        # ─────────────────────────────────────────────────────────────
        # Risk delta
        # ─────────────────────────────────────────────────────────────
        comparison = compute_risk_delta(
            scores_v1,
            scores_v2,
            comparison
        )

        # ─────────────────────────────────────────────────────────────
        # Negotiation suggestions
        # ─────────────────────────────────────────────────────────────
        suggestions = suggest_negotiation(
            comparison,
            scores_v1,
            scores_v2
        )

        # ─────────────────────────────────────────────────────────────
        # Rule M3:
        # net_delta is mandatory
        # ─────────────────────────────────────────────────────────────
        deltas = [
            r.risk_delta
            for r in comparison
            if r.risk_delta not in (None, "N/A")
        ]

        increased = deltas.count("INCREASED")
        decreased = deltas.count("DECREASED")

        if increased > decreased:
            net_delta = "INCREASED"

        elif decreased > increased:
            net_delta = "DECREASED"

        else:
            net_delta = "UNCHANGED"

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Comparison failed: {str(e)}"
        )

    finally:

        # Cleanup temp files
        for p in paths:

            if os.path.exists(p):

                try:
                    os.unlink(p)

                except Exception:
                    pass

    # ─────────────────────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────────────────────
    if db_available() and extraction_v1 and extraction_v2:

        doc_v1_data = _persist_doc(
            file_v1.filename or "v1.pdf",
            extraction_v1,
            clauses_v1,
            scores_v1
        )

        doc_v2_data = _persist_doc(
            file_v2.filename or "v2.pdf",
            extraction_v2,
            clauses_v2,
            scores_v2
        )

        if doc_v1_data and doc_v2_data:
            _persist_compare(
                comparison,
                doc_v1_data,
                doc_v2_data
            )

    return CompareResponse(
        comparison=comparison,
        net_delta=net_delta,
        suggestions=suggestions
    )