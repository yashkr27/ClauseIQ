✓ chunker.py exists at backend/src/chunker/chunker.py
✓ test_chunker.py exists at backend/src/chunker/test_chunker.py
✓ All 16 tests pass (pytest -v shows 16 passed)
✓ Actual NDA clauses printed to terminal match expected structure
✓ Git commit "Layer 2 — Chunker complete" is in log
✓ No hardcoded clause names in chunker.py (rule CP4 early check)
✓ Number normalisation works (rule C2): verify "1.0" → "1" in output
✓ Sub-clause grouping works (rule C3): verify "3.1" absorbed under "3" (unless parent > 800 chars)
✓ Type tagging works (rule C4): verify mix of definition/obligation/limitation in output