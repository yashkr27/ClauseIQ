# Assessment Brief — BRAHMO Document Intelligence
# Source: ASSESSMENT_05_Document_Intelligence.md
# This is the deliverable specification. Implementation decisions live in CLAUDE_MEMORY.md.

---

## WHAT YOU'RE BUILDING (2-minute read)

A Document Intelligence system that does three things:

1. **Extracts and chunks** legal documents into individual clauses (not generic text splitting — actual legal clause boundaries)
2. **Compares** two versions clause-by-clause: UNCHANGED, MODIFIED, ADDED, REMOVED — with word-level diffs for modified clauses
3. **Scores** each clause for risk using AI analysis + firm-specific rules from knowledge nodes

**The data flow:**
```
Lawyer uploads NDA v1 (DOCX/PDF)
  → Text extraction (python-docx / PyMuPDF)
  → Legal-aware chunker:
    ├── Identifies clause boundaries (numbered headings, section titles)
    ├── Tags each clause: number, title, type (definition/obligation/liability)
    └── NEVER splits inside a sub-clause or quoted definition
  → Risk scorer runs on each clause:
    ├── the AI analyzes: "is this clause risky?"
    └── Firm CONSTRAINT nodes override: "our policy says >12 months = HIGH risk"
  → Risk heatmap displayed: 3 RED, 2 ORANGE, 7 GREEN

Lawyer uploads NDA v2 (revised)
  → Same extraction + chunking
  → Clause comparator matches v1 ↔ v2:
    ├── Level 1: Heading match (same clause number)
    ├── Level 2: Semantic match (clause restructured but same content)
    └── Classification: UNCHANGED / MODIFIED / ADDED / REMOVED
  → Word-level diff for MODIFIED clauses
  → Risk DELTA: "this change INCREASED risk" / "DECREASED risk"
  → Side-by-side comparison with color coding
```

## TWO MODES

**Mode A — Risk Assessment (single document):** Upload one contract → chunk into clauses → score each clause for risk → display heatmap. 30-second triage tool.

**Mode B — Comparison (two documents):** Upload two versions → chunk both → match clauses → show what changed → score risk delta. 15-second change detection.

## DECISION PRIORITY

| Priority | Component | Weight |
|---|---|---|
| 1 | Legal-aware chunker | 20% |
| 2 | Clause comparator | 30% |
| 3 | Risk scorer with firm knowledge | 25% |
| 4 | Comparison UI + code quality | 10% |
| 5 | Innovation | 15% |

## EVALUATION CRITERIA

| Criteria | Weight | 10/10 |
|---|---|---|
| Comparison accuracy | 30% | All known changes found. Zero false negatives. SPA restructure via semantic matching. |
| Risk scoring with firm knowledge | 25% | CONSTRAINT nodes drive scores. Not just generic risk. |
| Chunking quality | 20% | Correct boundaries. Works across contract types. |
| Demo impact + code quality | 10% | Clear UI. Clean, extensible code. |
| Innovation | 15% | Solves a real problem from thinking guide. |

## WHAT 10/10 LOOKS LIKE

"The chunker nailed every clause boundary. The comparison found all 4 NDA changes with zero misses.
The risk scorer said 'high risk because your firm's policy caps liability at 2x' — not just 'unlimited = risky.'
The comparison UI made changes immediately visible. The surprise contract worked on the first try."

## SURPRISE TEST

After demos, evaluator uploads a NEW contract type (commercial lease, services agreement, shareholders agreement).
System must handle it with ZERO code changes.
Hardcoding NDA patterns = automatic fail.

## DEMO STRUCTURE (20-25 min)

1. [3 min] Architecture: extractor → chunker → comparator → scorer
2. [4 min] Scenario 2: Single NDA risk heatmap. CONSTRAINT nodes driving scores.
3. [7 min] Scenario 1: NDA comparison. All 4 changes found. Word-level diffs. Risk delta.
4. [3 min] Scenario 3: SPA restructure. Semantic matching catches split clause.
5. [3 min] Innovation.
6. [5 min] Questions + surprise document test.

## SUBMISSION CHECKLIST

- [ ] README.md with setup instructions
- [ ] .env.local.example
- [ ] supabase/schema.sql
- [ ] supabase/seed.sql (10 knowledge nodes loaded)
- [ ] Legal-aware chunker works (not generic text splitting)
- [ ] Comparison finds changes between two contract versions
- [ ] Risk scorer uses firm CONSTRAINT nodes (not just generic scoring)
- [ ] Risk heatmap visually clear (red/orange/green)
- [ ] Side-by-side comparison with colour-coded word-level diffs
- [ ] Risk delta shown after comparison (NET INCREASED/DECREASED)
- [ ] System handles NEW contract types beyond demo docs (surprise-ready)
- [ ] Clean git history
- [ ] docs/architecture.md explains chunking approach + matching strategy
