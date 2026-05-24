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

router = APIRouter()

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
        extraction = extract(tmp_path)
        clauses    = chunk(extraction)
        scores     = score_document(clauses)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction or analysis failed: {str(e)}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    summary = RiskSummary(
        high   = sum(1 for s in scores if s.risk_level == 'HIGH'),
        medium = sum(1 for s in scores if s.risk_level == 'MEDIUM'),
        low    = sum(1 for s in scores if s.risk_level == 'LOW'),
    )

    return AnalyseResponse(
        filename=filename,
        clauses=clauses,
        risk_scores=scores,
        risk_summary=summary,
    )
