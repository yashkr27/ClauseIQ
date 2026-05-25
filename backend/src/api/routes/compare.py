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

from ...extraction.extractor import extract
from ...chunker.chunker import chunk
from ...scorer.scorer import score_document, compute_risk_delta, suggest_negotiation
from ...comparator.comparator import compare
from ...models.schemas import CompareResponse
from ...db import db_available, get_client

router = APIRouter()
MAX_BYTES = 20 * 1024 * 1024


def _persist_doc(filename: str, extraction, clauses, scores) -> str | None:
    """Persist a single document side and return its DB id."""
    try:
        client = get_client()
        doc_row = client.table("documents").insert({
            "filename":     filename,
            "content_text": extraction.text[:5000],
        }).execute().data[0]
        doc_id = doc_row["id"]

        for c in clauses:
            client.table("document_chunks").insert({
                "document_id":   doc_id,
                "chunk_index":   c.chunk_index,
                "clause_number": c.clause_number,
                "clause_title":  c.clause_title,
                "clause_type":   c.clause_type,
                "text":          c.text,
            }).execute()

        for s in scores:
            client.table("risk_scores").insert({
                "chunk_id":              s.chunk_index,
                "score":                 s.score,
                "risk_factors":          s.risk_factors,
                "constraint_violations": s.constraint_violations,
                "recommendation":        s.recommendation,
            }).execute()

        return doc_id
    except Exception:
        return None


def _persist_compare(comparison, doc_v1_id: str, doc_v2_id: str):
    """Write comparison results to Supabase."""
    try:
        client = get_client()
        for r in comparison:
            client.table("comparison_results").insert({
                "doc_v1_id":        doc_v1_id,
                "doc_v2_id":        doc_v2_id,
                "chunk_v1_id":      r.clause_number_v1,
                "chunk_v2_id":      r.clause_number_v2,
                "match_type":       r.match_type,
                "similarity_score": r.similarity_score,
                "diff_text":        r.diff_text,
            }).execute()
    except Exception:
        pass


@router.post("/api/compare", response_model=CompareResponse)
async def compare_docs(file_v1: UploadFile = File(...), file_v2: UploadFile = File(...)):
    paths         = []
    extraction_v1 = None
    extraction_v2 = None
    clauses_v1    = []
    clauses_v2    = []
    scores_v1     = []
    scores_v2     = []
    comparison    = []
    suggestions   = []
    net_delta     = 'UNCHANGED'

    try:
        for f in [file_v1, file_v2]:
            filename = f.filename or "contract.pdf"
            if not filename.lower().endswith(('.pdf', '.docx', '.doc')):
                raise HTTPException(status_code=400, detail="Unsupported file type. Use .pdf or .docx")

            ext = os.path.splitext(filename)[1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                shutil.copyfileobj(f.file, tmp)
                paths.append(tmp.name)

            file_size = os.path.getsize(paths[-1])
            if file_size > MAX_BYTES:
                raise HTTPException(status_code=400, detail="File exceeds 20 MB limit.")
            if file_size == 0:
                raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        # Rule M2: same pipeline for both docs
        extraction_v1 = extract(paths[0])
        extraction_v2 = extract(paths[1])

        clauses_v1 = chunk(extraction_v1)
        clauses_v2 = chunk(extraction_v2)

        scores_v1 = score_document(clauses_v1)
        scores_v2 = score_document(clauses_v2)

        comparison = compare(clauses_v1, clauses_v2)
        comparison = compute_risk_delta(scores_v1, scores_v2, comparison)

        suggestions = suggest_negotiation(comparison, scores_v1, scores_v2)

        # Rule M3: net_delta is mandatory
        deltas    = [r.risk_delta for r in comparison if r.risk_delta not in (None, 'N/A')]
        increased = deltas.count('INCREASED')
        decreased = deltas.count('DECREASED')

        if increased > decreased:
            net_delta = 'INCREASED'
        elif decreased > increased:
            net_delta = 'DECREASED'
        else:
            net_delta = 'UNCHANGED'

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Comparison failed: {str(e)}")
    finally:
        for p in paths:
            if os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass

    if db_available() and extraction_v1 and extraction_v2:
        doc_v1_id = _persist_doc(file_v1.filename or "v1.pdf", extraction_v1, clauses_v1, scores_v1)
        doc_v2_id = _persist_doc(file_v2.filename or "v2.pdf", extraction_v2, clauses_v2, scores_v2)
        if doc_v1_id and doc_v2_id:
            _persist_compare(comparison, doc_v1_id, doc_v2_id)

    return CompareResponse(comparison=comparison, net_delta=net_delta, suggestions=suggestions)