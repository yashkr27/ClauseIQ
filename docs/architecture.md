# ClauseIQ — Architecture

## Pipeline Overview

```
Document (PDF / DOCX)
        ↓
LlamaParse → structured markdown + page indexes
        ↓
Gemini semantic chunker  (regex fallback)
        ↓
Chunk normalisation + oversized split (2–3 pieces)
        ↓
Risk scoring via knowledge-node retrieval (Supabase → seed.sql fallback)
        ↓
Semantic comparator  (heading match → TF-IDF → word-level diff)
        ↓
UI output  (heatmap / side-by-side comparison + net risk delta)
```

---

## Layer 1 — Extraction (`src/extraction/`)

The document enters the pipeline as a raw PDF or DOCX file. The extractor tries two backends in order, caching the result in memory by SHA-256 file digest so repeated uploads of the same file are instant.

**Primary: LlamaParse**

LlamaParse is called with `result_type="markdown"` and `split_by_page=True`. This returns one Document object per page, which gives the pipeline two things simultaneously:

- Structured markdown — headings, bold text, and tables are preserved as markdown syntax, which makes clause boundaries far more legible to the downstream LLM chunker than plain concatenated text.
- Per-page index — each page's text is recorded with its character start and end offsets in the full document string. Page markers are embedded inline as `<!-- PAGE N -->` comments so Gemini can read them directly.

The output is an `ExtractionResult` with a `page_texts` list of the form:

```python
[{"page": 1, "text": "...", "char_start": 0, "char_end": 1842}, ...]
```

A `page_for_offset(char_offset, page_texts)` utility lets the chunker attach a page number to any clause later.

**Fallback: PyMuPDF / python-docx**

If LlamaParse is unavailable (no API key) or returns empty content (scanned PDF, corrupt file), the fallback backend runs PyMuPDF for PDFs and python-docx for DOCX files. It produces the same `<!-- PAGE N -->` markers and the same `page_texts` structure, so all downstream code is backend-agnostic.

If both backends fail, the server returns a 500 with a combined error message.

---

## Layer 2 — Chunking (`src/chunker/`)

The chunker turns the flat markdown string into a list of typed `Clause` objects. It has two paths that share the same helpers and produce identical output shapes.

### Primary: Gemini semantic chunker

The full document markdown (including page markers) is sent to Gemini 1.5 Flash in a single call with `temperature=0.1`. The system prompt instructs Gemini to return a JSON array of clause objects, each with:

```
clause_number, clause_title, clause_type, text, page_number
```

Gemini reads the `<!-- PAGE N -->` markers and populates `page_number` on each clause. This is the only place page attribution is done — everything downstream just carries the field forward.

After the API response is parsed, the pipeline runs two post-processing passes:

**Boilerplate filter** — clauses whose title or text matches known patterns (watermarks, preamble phrases, signature tables) are dropped before indexing.

**Oversized split** — any clause body exceeding 2 000 characters is split into 2–3 pieces on paragraph boundaries. Splitting caps at 3 pieces to keep each chunk coherent for the risk scorer. Sub-chunks inherit the parent clause number with a decimal suffix (`8` → `8.1`, `8.2`).

### Fallback: regex boundary detector

If Gemini is unavailable or returns malformed JSON, the regex chunker takes over. It scans the markdown for boundary patterns in priority order:

1. Nested numeric headings with parenthetical sub-numbers (`1(a)`, `3(ii)`)
2. Alphanumeric clause numbers (`8A`, `11B`)
3. Decimal sub-clauses (`3.1`, `4.2`)
4. Top-level numbered clauses (`1.`, `2.`, `3.`)
5. Roman numeral articles (`Article IV`)
6. Schedule / annexure markers (`SCHEDULE A`, `ANNEXURE 1`)
7. Short all-caps section titles (≤ 4 words, not in the boilerplate blacklist)

Clause type is inferred from keyword matching against the title and the first 200 characters of clause text. Page attribution is resolved by looking up each boundary's character offset in the `page_texts` list.

The same oversized-split and boilerplate-filter helpers run on regex output as on Gemini output.

---

## Layer 3 — Risk Scoring (`src/scorer/`)

### Knowledge node retrieval

Before any clause is scored, the knowledge store is loaded. The loader follows a strict priority chain:

1. **In-process cache** — nodes loaded earlier in the same server process are returned immediately, so the Supabase round-trip only happens once per startup.
2. **Supabase `knowledge_nodes` table** — the live source of truth. Any nodes added at runtime (e.g. by an evaluator through the Supabase UI) are picked up on the next `force_refresh` call.
3. **`supabase/seed.sql` parse** — if the database is unreachable, the seed file is parsed with regex to extract the same 10 INSERT rows as plain Python dicts. Scoring never breaks without a DB connection.
4. **In-memory store** — last resort if the seed file is also missing.

The 10 pre-loaded nodes cover the firm's most common risk triggers: liability caps (C-010), non-compete duration (C-011), IP carve-outs (C-012), arbitration preference (C-013), termination notice (C-014), one-sided indemnification (AP-010), auto-renewal opt-out windows (AP-011), return of materials (D-010), proportionate liquidated damages (D-011), and clear dispute resolution (D-012).

### Scoring

Each clause is hashed (SHA-256 of its text) and checked against an in-memory score cache first, so identical clauses in two documents are only scored once per server process.

The scorer sends the clause text to Claude via AWS Bedrock, injecting all matching knowledge nodes as additional context. The LLM returns a score (1–10), a risk level, a list of risk factors, and a recommendation. If a firm constraint node is violated, that constraint's threshold overrides the LLM score — for example, C-010 forces any uncapped liability clause to HIGH regardless of the model's raw number.

**Score ranges:**

| Score | Level | Display |
|---|---|---|
| 1–3 | LOW | Green |
| 4–6 | MEDIUM | Orange |
| 7–10 | HIGH | Red |

---

## Layer 4 — Comparator (`src/comparator/`)

The comparator takes the two scored clause lists and matches them across three passes.

### L1 — Heading match

Clause numbers from v1 and v2 are normalised (prefixes like `clause`, `section`, `article` stripped; `1.0` collapsed to `1`; lowercased) and matched as dictionary keys. Exact heading matches are resolved first. This handles the common case where the document structure is stable between versions.

### L2 — TF-IDF semantic match

Unmatched clauses from both sides go into a TF-IDF cosine similarity matrix. Each unmatched v1 clause is paired with its best-scoring v2 candidate. A match is accepted only if the similarity score exceeds the modified threshold (0.40). This handles renumbered or restructured clauses that would be invisible to heading matching alone.

### Split detection

When a single v1 clause number shares a base number with multiple v2 clause numbers (e.g. `8` in v1 vs `8` and `8A` in v2), the comparator checks whether the combined text of the v2 clauses is semantically close to the v1 clause (threshold 0.28). If so, the v1 clause is marked as SPLIT rather than REMOVED, and each v2 sub-clause is linked back to it. Without this pass, a restructured indemnification clause would appear as one deletion and two unrelated additions.

### Classification thresholds

| Similarity | Classification |
|---|---|
| ≥ 0.95 | UNCHANGED |
| 0.40 – 0.94 | MODIFIED |
| < 0.40 (unmatched v1) | REMOVED |
| < 0.40 (unmatched v2) | ADDED |

### Word-level diff

Every MODIFIED pair gets a `difflib.SequenceMatcher` word-level diff. The output is a list of `{type, text}` tokens where type is `equal`, `add`, or `remove`. The frontend renders `add` tokens green and `remove` tokens red.

### Risk delta

After matching, each MODIFIED clause has a `risk_delta` computed from its two risk scores (`INCREASED`, `DECREASED`, `UNCHANGED`). ADDED and REMOVED clauses carry `N/A`. The overall `net_delta` for the comparison is derived from the balance of all clause-level deltas and returned in the `CompareResponse`.

---

## Data Flow (Mode B — Compare)

```
file_v1 ─────┐
              ├→ extract() → clean() → chunk() → score_document()
file_v2 ─────┘                                        ↓
                                             compare(clauses_v1, clauses_v2)
                                                       ↓
                                          compute_risk_delta()
                                                       ↓
                                          suggest_negotiation()
                                                       ↓
                                             CompareResponse
                                    {comparison, net_delta, suggestions}
```

For Mode A (single document), the pipeline stops after `score_document()` and returns an `AnalyseResponse` with a risk summary and heatmap data.

---

## Database Schema (Supabase)

```
knowledge_nodes   id (text PK), node_type, title, content, practice_area, tags (JSONB)
documents         id (uuid PK), filename, uploaded_at, content_text
document_chunks   id (uuid PK), document_id → documents, chunk_index, clause_number,
                  clause_title, clause_type, text
risk_scores       id (uuid PK), chunk_id → document_chunks, score, risk_factors (JSONB),
                  constraint_violations (JSONB), recommendation
comparison_results id (uuid PK), doc_v1_id → documents, doc_v2_id → documents,
                  chunk_v1_id → document_chunks, chunk_v2_id → document_chunks,
                  match_type, similarity_score, diff_text
```

All persistence is best-effort — the API routes catch and suppress DB errors so a missing or slow Supabase connection never fails a request.