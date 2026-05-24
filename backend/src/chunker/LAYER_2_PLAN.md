# Layer 2 — Chunker: Step-by-Step Implementation

## Quick Reference
- **Time estimate:** 2 hours (with testing + debugging)
- **Files to create:** 2 (chunker.py + test_chunker.py)
- **Rules to satisfy:** C1, C2, C3, C4
- **Test count:** 16 tests, must all pass

## Five Phases

### Phase 0: Prep (10 min)
- [ ] Read CLAUDE_MEMORY.md rules C1–C4
- [ ] Read IMPLEMENTATION.md Layer 2 section
- [ ] Verify Layer 1 tests pass: `pytest src/extraction/test_extractor.py -v`

### Phase 1: Write chunker.py (45 min)
- [ ] Copy full chunker.py from IMPLEMENTATION.md
- [ ] Verify imports resolve: `python -c "from src.chunker.chunker import chunk"`
- [ ] Check rule C2 (number normalisation) function exists
- [ ] Check rule C3 (sub-clause grouping) function exists
- [ ] Check rule C4 (type tagging) function exists

### Phase 2: Write test_chunker.py (30 min)
- [ ] Copy all 16 tests from IMPLEMENTATION.md
- [ ] Run: `pytest src/chunker/test_chunker.py -v`
- [ ] If any fail: debug against ndav1/ndav2 actual output
- [ ] Print first 5 clauses from each NDA to verify structure

### Phase 3: Integration test (20 min)
- [ ] Extract ndav1, chunk it, print clauses
- [ ] Extract ndav2, chunk it, print clauses
- [ ] Verify v1 has flat integers (1, 2, 3 ...)
- [ ] Verify v2 has decimals (1.0, 3.1, 3.2 ...)
- [ ] Verify sub-clauses grouped (3.1, 3.2 absorbed into 3 output)

### Phase 4: Run full test suite (10 min)
- [ ] `pytest src/chunker/test_chunker.py -v`
- [ ] All 16 pass
- [ ] Exit code 0

### Phase 5: Commit (5 min)
- [ ] `git add backend/src/chunker/`
- [ ] `git commit -m "Layer 2 — Chunker complete (16/16 tests pass)"`
- [ ] `git log --oneline | head -3` — verify commit is there

## Success Checklist
- [ ] 16/16 tests pass
- [ ] ndav1 produces ~14 clauses (flat integers)
- [ ] ndav2 produces ~12 clauses (decimals + grouping)
- [ ] No hardcoded clause names in code (rule CP4 prep)
- [ ] Sub-clauses grouped by rule C3 (3.1 not in output as separate)
- [ ] All clause types tagged (definition/obligation/limitation/...)
- [ ] Git commit exists
- [ ] Both NDA outputs examined manually

## Next: Layer 3 — Comparator
After commit, ping me for Layer 3 plan (clause matching + semantic similarity).

---
Created: Phase 0 of Layer 2
Status: Ready to start Phase 1
