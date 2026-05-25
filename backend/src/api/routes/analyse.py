"""
POST /api/analyse — Mode A: single document risk heatmap
Rule M1: standalone, complete flow
Rule F5: API shape is fixed, frontend adapts to it
"""
from fastapi import APIRouter, UploadFile, File, HTTPException
import tempfile
import os
import shutil

from ...extraction.extractor import extract
from ...chunker.chunker import chunk
from ...scorer.scorer import score_document
from ...models.schemas import AnalyseResponse, RiskSummary
from ...db import db_available, get_client

router = APIRouter()
MAX_BYTES = 20 * 1024 * 1024


def _persist_analyse(filename: str, extraction, clauses, scores):
    """Write document, chunks and risk scores to Supabase."""
    try:
        client = get_client()

        # 1. documents
        doc_row = client.table("documents").insert({
            "filename": filename,
            "content_text": extraction.text[:5000]
        }).execute().data[0]
        doc_id = doc_row["id"]

        # 2. document_chunks — capture returned UUIDs
        chunk_id_map = {}
        for c in clauses:
            row = client.table("document_chunks").insert({
                "document_id":   doc_id,
                "chunk_index":   c.chunk_index,
                "clause_number": c.clause_number,
                "clause_title":  c.clause_title,
                "clause_type":   c.clause_type,
                "text":          c.text,
            }).execute().data[0]
            chunk_id_map[c.chunk_index] = row["id"]  # ← real UUID

        # 3. risk_scores — use UUID not chunk_index
        for s in scores:
            chunk_uuid = chunk_id_map.get(s.chunk_index)
            if chunk_uuid:
                client.table("risk_scores").insert({
                    "chunk_id":              chunk_uuid,  # ← fixed
                    "score":                 s.score,
                    "risk_factors":          s.risk_factors,
                    "constraint_violations": s.constraint_violations,
                    "recommendation":        s.recommendation,
                }).execute()

    except Exception:
        pass


@router.post("/api/analyse", response_model=AnalyseResponse)
async def analyse(file: UploadFile = File(...)):
    filename = file.filename or "contract.pdf"
    if not filename.lower().endswith(('.pdf', '.docx', '.doc')):
        raise HTTPException(status_code=400, detail="Unsupported file type. Use .pdf or .docx")

    ext = os.path.splitext(filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        file_size = os.path.getsize(tmp_path)
        if file_size > MAX_BYTES:
            raise HTTPException(status_code=400, detail="File exceeds 20 MB limit.")
        if file_size == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        extraction = extract(tmp_path)
        clauses    = chunk(extraction)
        scores     = score_document(clauses)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction or analysis failed: {str(e)}")
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    if db_available():
        _persist_analyse(filename, extraction, clauses, scores)

    summary = RiskSummary(
        high     = sum(1 for s in scores if s.risk_level == 'HIGH'),
        medium   = sum(1 for s in scores if s.risk_level == 'MEDIUM'),
        low      = sum(1 for s in scores if s.risk_level == 'LOW'),
        unscored = sum(1 for s in scores if s.risk_level == 'UNSCORED'),
    )

    return AnalyseResponse(
        filename=filename,
        clauses=clauses,
        risk_scores=scores,
        risk_summary=summary,
    )