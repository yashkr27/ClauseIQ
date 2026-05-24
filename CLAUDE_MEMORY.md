# ClauseIQ — Claude Memory Layer
# Every suggestion in this project must satisfy ALL rules below.
# If a user suggestion violates a rule, push back with the specific rule ID.

---

## PROJECT IDENTITY
- Name: ClauseIQ
- Stack: FastAPI (Python) + Next.js (TypeScript) + Supabase + Anthropic API
- Purpose: Legal contract clause extraction, comparison, and risk scoring
- OS: Windows (PowerShell). Use `python` not `python3`. Use `pytest` not `python -m pytest` if on PATH.
- System deps: Tesseract at C:\Program Files\Tesseract-OCR\, Poppler at C:\poppler\Library\bin — both must be on PATH.
- Never suggest apt/brew commands. Windows equivalents only.

---

## ARCHITECTURE RULES

### A1 — Monolith, not microservices
Single FastAPI app. No separate services, no Docker Compose with 3 containers.
Microservices only if we hit 200+ docs/day in production. Not before.

### A2 — 4 strict layers, in order
Layer 1: Extraction   → pdf2image + pytesseract (OCR) for PDFs, python-docx for DOCX
Layer 2: Chunker      → regex on legal structure (numbered headings, UPPERCASE titles)
Layer 3: Comparator   → L1 heading match → L2 TF-IDF cosine semantic match
Layer 4: Scorer       → Claude API + CONSTRAINT node injection
Each layer takes the previous layer's output. Never skip or merge layers.

### A3 — DB is optional at build time
db.py provides in-memory fallback. Every layer must work without Supabase configured.
Supabase is plugged in last, not first.

### A4 — Frontend is last
Next.js frontend is built after all 4 backend layers are tested and working.
No UI-first decisions that constrain backend design.

### A5 — No OCR bypass
Both NDAs are vector-drawn PDFs (text stored as SVG paths, not embedded text).
pymupdf and pypdf return empty strings on these files.
Extraction MUST use pdf2image → pytesseract pipeline.
Do NOT switch to docling, pdfplumber, or any tool that claims "text-based PDF" support
without first verifying it handles vector-drawn PDFs correctly.

---

## EXTRACTION RULES (Layer 1)

### E1 — Preserve heading structure
Extracted text must retain numbered headings and UPPERCASE section titles.
The chunker depends on these. Stripping formatting = broken chunker.

### E2 — Support both PDF and DOCX
Extraction module must handle both. DOCX via python-docx. PDF via OCR pipeline.
Single interface: extract(file_path) → { text: str, headings: list }

### E3 — Page noise stripping
These PDFs contain browser-generated headers (URL + timestamp on every page).
Pattern: lines matching `^\d+/\d+/\d+,\s+\d+:\d+\s+(AM|PM)` and `https?://` lines.
Strip before passing to chunker.

---

## CHUNKER RULES (Layer 2)

### C1 — Legal-aware only, no generic splitting
Never split by token count, character count, or paragraph breaks alone.
Split only on legal clause boundaries: numbered headings, UPPERCASE titles, SCHEDULE/ANNEXURE markers.

### C2 — Handle both numbering styles
v1 NDA: flat integers (1, 2, 3 ... 14)
v2 NDA: decimal notation (1.0, 2.0, 3.1, 3.2 ...)
Chunker must normalise both to a canonical form for matching.

### C3 — Sub-clause grouping
Sub-clauses (3.1, 3.2, 3.3) belong to their parent (3.0).
Default: group sub-clauses under parent unless parent text > 800 chars.
Never split mid-sentence or mid-definition.

### C4 — Clause type tagging
Every chunk must be tagged with one of:
definition | obligation | limitation | termination | indemnity | ip | confidentiality | general
Tagging via keyword heuristics, not LLM (too slow for this step).

---

## COMPARATOR RULES (Layer 3)

### CP1 — Two-level matching, always both
L1: Normalised heading match (strip dots, lowercase, "clause 3" == "3" == "3.0")
L2: TF-IDF cosine similarity (scikit-learn, no external API) for unmatched clauses
Never skip L2. The NDA pair has structural renumbering (v1 §3 Standstill = v2 §9.0).

### CP2 — Similarity thresholds
> 0.95 cosine → UNCHANGED
0.4–0.95     → MODIFIED (run word-level diff)
< 0.4        → treat as ADDED/REMOVED pair

### CP3 — Word-level diff for MODIFIED
Use Python difflib.ndiff or SequenceMatcher.
Output: list of { type: "add"|"remove"|"equal", text: str }
Never return "clause changed" without showing what changed.

### CP4 — No hardcoded clause titles
Matching logic must work on any contract type. Zero references to
"Standstill", "Non-Solicitation", "NDA" etc. in matching code.

---

## SCORER RULES (Layer 4)

### S1 — CONSTRAINT nodes are mandatory input
Every scoring call must inject all relevant knowledge_nodes into the prompt.
Generic LLM scoring without firm knowledge = fails the assessment.

### S2 — CONSTRAINT overrides LLM score
If a CONSTRAINT node threshold is triggered (e.g. C-010: uncapped liability),
the score must be set to HIGH (7+) regardless of what the LLM returned.
Override logic lives in Python, not in the prompt.

### S3 — Score schema
Return: { score: 1-10, risk_level: LOW|MEDIUM|HIGH, risk_factors: [],
          constraint_violations: [], recommendation: str }
Risk levels: 1-3 = LOW, 4-6 = MEDIUM, 7-10 = HIGH

### S4 — Risk delta after comparison
After scoring both versions, compute delta per clause:
score_v2 - score_v1 > 0  → INCREASED
score_v2 - score_v1 < 0  → DECREASED
equal                    → UNCHANGED

---

## DB RULES

### D1 — Schema is fixed
Tables: knowledge_nodes, documents, document_chunks, risk_scores, comparison_results
Schema defined in supabase/schema.sql. Do not alter column names without updating
all 4 layers and the Pydantic models in models/schemas.py simultaneously.

### D2 — In-memory store mirrors schema
db.py mem_* functions must always mirror the same table/field names as schema.sql.
They are the dev/test substitute. Drift between them = silent bugs.

---

## TEST DATA RULES

### T1 — NDAs are vector-drawn PDFs
test-data/ndav1.pdf and ndav2.pdf have text as SVG vector paths.
pymupdf/pypdf return empty strings. This is expected. OCR is correct path.

### T2 — Known differences to verify
After comparator is built, it must find ALL of these between ndav1 and ndav2:
  - Term duration: v1=2 years post-discussion, v2=1 year from date
  - Survival: v1=none explicit, v2=3 years post-termination (ADDED)
  - Return of materials: v1=strict destroy+certify, v2=archival copy exception (MODIFIED)
  - Antitrust Compliance: v1=absent, v2=Section 11.0 (ADDED)
  - Attorney-Client Privilege: v2=Section 12.0 (ADDED)
  - Standstill: v1=Section 3, v2=Section 9.0 — different numbers, same content (semantic match test)
  - Warranties: v1=brief Section 5, v2=extensive AS-IS disclaimer in 7.3 (MODIFIED, risk increase)

### T3 — Surprise contract readiness
Chunker and comparator must produce valid output on any contract type.
Test with a non-NDA doc before demo. Fail here = fail the surprise test.

---

## FILE STRUCTURE (locked)
ClauseIQ/
├── backend/
│   ├── requirements.txt
│   └── src/
│       ├── api/main.py
│       ├── extraction/
│       ├── chunker/
│       ├── comparator/
│       ├── scorer/
│       ├── models/schemas.py
│       └── db.py
├── frontend/          ← last
├── supabase/
│   ├── schema.sql
│   └── seed.sql
├── test-data/
│   ├── ndav1.pdf
│   └── ndav2.pdf
├── docs/architecture.md
├── .env.example
└── CLAUDE_MEMORY.md   ← this file

---

## KNOWN CONFLICTS WITH ASSESSMENT TEXT (resolved)

### X1 — Assessment says "don't worry about OCR / text-based DOCX"
Assessment assumes test docs are clean text-embedded DOCX.
Our actual test files are vector-drawn PDFs — OCR is required (verified, rule A5).
Resolution: follow A5. If DOCX files are provided later, add python-docx fast path.

### X2 — Assessment data flow diagram shows PyMuPDF
"Text extraction (python-docx / PyMuPDF)" in assessment.
PyMuPDF returned 0 bytes on our actual NDAs (verified).
Resolution: PyMuPDF is not in extraction path. OCR is primary. Rule A5 holds.

### X3 — Assessment data flow merges extraction + chunking
Diagram implies one combined step. Rule A2 requires strict separation.
Resolution: two separate modules, clean interface. Chunker accepts plain text only.

---
Last updated: Layer 1 (extraction) in progress — extractor.py + tests written, pending test run.
Next: run tests, fix failures, commit "Layer 1 — Extraction complete", then Layer 2 — Chunker.

---

## MODE RULES (assessment deliverables)

### M1 — Mode A must work standalone
Single document upload → chunk → score → return heatmap data.
This is a complete, usable flow independent of Mode B.
API endpoint: POST /api/analyse  →  { clauses: [...], risk_summary: { high, medium, low } }

### M2 — Mode B must reuse Mode A output
Two-document comparison builds on top of Mode A results for both docs.
Never re-extract or re-chunk when comparing — reuse clause lists.
API endpoint: POST /api/compare  →  { comparison: [...], net_delta: "INCREASED"|"DECREASED"|"UNCHANGED" }

### M3 — Net delta is mandatory in Mode B response
After comparison, compute overall net delta across all clause deltas.
More INCREASED than DECREASED → "INCREASED". Opposite → "DECREASED". Tie → "UNCHANGED".
Must appear in both the API response and the UI.

---

## FRONTEND RULES (Layer 5 — built last)

### F1 — Risk heatmap is colour-coded by score level
HIGH (7-10) → red. MEDIUM (4-6) → orange. LOW (1-3) → green.
Every clause card shows: clause number, title, score, risk_level colour, triggered CONSTRAINT IDs.

### F2 — Comparison view is side-by-side
v1 clause left, v2 clause right. Status badge (UNCHANGED/MODIFIED/ADDED/REMOVED) visible.
MODIFIED clauses show word-level diff inline: removed text red strikethrough, added text green.

### F3 — CONSTRAINT violations must be visible in UI
Any triggered CONSTRAINT node (e.g. C-011) must appear by ID + short reason on the clause card.
Not buried in a tooltip — visible without interaction.

### F4 — Risk delta shown per clause and in summary
Per clause: arrow indicator (↑ risk increased, ↓ decreased, = unchanged).
Summary panel: "Net risk INCREASED / DECREASED / UNCHANGED" prominently displayed.

### F5 — No UI decision may change backend API shape
Frontend adapts to API. If a UI requirement seems to need a new field,
add it to the API response schema first, update models/schemas.py, then build UI.

---

## SUBMISSION RULES

### SB1 — 10 knowledge nodes loadable from seed.sql
supabase/seed.sql contains all 10 nodes (C-010 through D-012).
Scorer must load them at startup into in-memory store when DB not available.

### SB2 — docs/architecture.md must explain chunking + matching strategy
Required content: (1) how clause boundaries are detected, (2) how L1+L2 matching works,
(3) how CONSTRAINT nodes feed into scoring. Min 3 sections, written before demo.

### SB3 — README.md must contain setup instructions
Required: env vars needed, how to run backend, how to run frontend, how to load seed data.
Written before demo day.

### SB4 — Clean git history
Commit after each layer is complete and tested. Commit messages: "Layer N — [name] complete".
Never commit .env. Never commit with broken tests.

### SB5 — Surprise contract test before demo
At least one non-NDA contract must be run through the full pipeline before demo day.
Result logged in evaluation/ folder. Chunker must produce >3 clauses. Comparator must find changes.
