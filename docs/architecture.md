# ClauseIQ Architecture

## Pipeline

1. `backend/src/extraction/extractor.py`
   Extracts PDF text with PyMuPDF first, then OCR fallback. DOCX extraction uses `python-docx`. The extractor strips browser print noise such as timestamps, URLs, and page numbers.

2. `backend/src/chunker/chunker.py`
   Splits text at legal boundaries rather than token windows. It recognizes numbered headings, decimal subclauses, parenthetical subclauses, alphanumeric inserted clauses such as `8A`, uppercase section titles, articles, schedules, and annexures. If no headings are found, it falls back to long paragraph chunks so surprise contracts do not collapse into one giant document.

3. `backend/src/comparator/comparator.py`
   Runs two matching layers. L1 matches normalized clause numbers. L2 uses TF-IDF cosine similarity for unmatched clauses. A split-detection pass links clauses like old `8` to new `8A` when a provision has been broken into multiple parts, avoiding false ADDED/REMOVED reports for restructures.

4. `backend/src/scorer/scorer.py`
   Applies deterministic firm constraints before LLM scoring. Constraints can force minimum scores and cite firm policy nodes. Bedrock is optional enrichment; when unavailable, the scorer returns `UNSCORED` instead of falsely marking clauses low risk.

5. `backend/src/api/routes`
   `analyse.py` runs extraction, chunking, and scoring for one document. `compare.py` runs the same pipeline for both versions, compares clauses, attaches risk deltas, and computes net risk movement.

6. `frontend`
   A static FastAPI-served interface for upload, risk heatmaps, side-by-side comparison rows, expandable word-level diffs, and reset/retry during demos.

## Matching Strategy

- Exact text match above `0.95` similarity is `UNCHANGED`.
- Same heading but changed content is `MODIFIED`.
- Unmatched clauses above semantic threshold are `MODIFIED`.
- Remaining v1 clauses are `REMOVED`.
- Remaining v2 clauses are `ADDED`.
- Split clauses reuse the original v1 clause number when a v2 alphanumeric or semantically close clause clearly derives from an already matched parent.

## Risk Strategy

Firm knowledge nodes are loaded from Supabase when configured, otherwise from `supabase/seed.sql`. Deterministic constraints cover:

- `C-010`: uncapped liability.
- `C-011`: non-compete/non-solicitation/standstill over 12 months.
- `C-012`: broad IP assignment without pre-existing IP carve-out.
- `C-013`: dispute/governing law clauses without arbitration.
- `C-014`: termination notice under 90 days.

Added high-risk clauses increase net risk. Removed high-risk clauses decrease net risk. Modified clauses compare v1 and v2 scores directly.
