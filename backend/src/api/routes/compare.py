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
from ...scorer.scorer import score_document, compute_risk_delta
from ...comparator.comparator import compare
from ...models.schemas import CompareResponse

router = APIRouter()

@router.post("/api/compare", response_model=CompareResponse)
async def compare_docs(file_v1: UploadFile = File(...), file_v2: UploadFile = File(...)):
    paths = []
    try:
        for f in [file_v1, file_v2]:
            filename = f.filename or "contract.pdf"
            if not filename.lower().endswith(('.pdf', '.docx', '.doc')):
                raise HTTPException(status_code=400, detail="Unsupported file type. Use .pdf or .docx")
            
            ext = os.path.splitext(filename)[1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                shutil.copyfileobj(f.file, tmp)
                paths.append(tmp.name)

        # Rule M2: same pipeline for both docs, reusing Mode A logic blocks
        extraction_v1 = extract(paths[0])
        extraction_v2 = extract(paths[1])
        
        clauses_v1    = chunk(extraction_v1)
        clauses_v2    = chunk(extraction_v2)
        
        scores_v1     = score_document(clauses_v1)
        scores_v2     = score_document(clauses_v2)
        
        comparison    = compare(clauses_v1, clauses_v2)
        comparison    = compute_risk_delta(scores_v1, scores_v2, comparison)

        # Rule M3: net_delta is mandatory
        deltas = [r.risk_delta for r in comparison if r.risk_delta not in (None, 'N/A')]
        increased = deltas.count('INCREASED')
        decreased = deltas.count('DECREASED')
        
        if increased > decreased:
            net_delta = 'INCREASED'
        elif decreased > increased:
            net_delta = 'DECREASED'
        else:
            net_delta = 'UNCHANGED'

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Comparison failed: {str(e)}")
    finally:
        for p in paths:
            if os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass

    return CompareResponse(comparison=comparison, net_delta=net_delta)
