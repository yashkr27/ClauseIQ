#Brahmo Document Intelligence Project → ClauseIQ

ClauseIQ is a legal document intelligence system that extracts, scores, and compares contract clauses. Upload a single contract to get a clause-by-clause risk heatmap, or upload two versions of the same contract to get a side-by-side comparison with word-level diffs and a net risk delta.

---

## Features

- **Mode A — Analyse:** Upload one contract (PDF or DOCX). ClauseIQ extracts every clause, classifies its type, scores it 1–10 for risk, and renders a red/orange/green heatmap with recommendations.
- **Mode B — Compare:** Upload two versions of a contract. ClauseIQ matches clauses (by heading and semantic similarity), shows word-level diffs for every changed clause, and outputs a net `INCREASED / DECREASED / UNCHANGED` risk delta.
- **Firm Knowledge Engine:** 10 pre-loaded firm constraint nodes (liability caps, non-compete limits, IP carve-outs, arbitration preferences, etc.) override generic LLM scoring. Any clause violating a firm rule is flagged regardless of LLM output.
- **Negotiation Suggestions:** After comparison, the system surfaces actionable negotiation moves tied to specific constraint IDs.
- **Supabase persistence:** All documents, chunks, risk scores, and comparison results are written to Supabase when a database connection is available. The app degrades gracefully without one.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Vanilla HTML / CSS / JS (single-page, no build step) |
| Backend | Python 3.11+, FastAPI, Uvicorn |
| Document extraction | PyMuPDF (PDF), python-docx (DOCX), LlamaParse (fallback OCR) |
| Chunking | Gemini semantic chunking (primary) → regex boundary detection (fallback) |
| Comparison | TF-IDF cosine similarity + difflib word-level diffs |
| Risk scoring | Claude via AWS Bedrock (configurable model) |
| Database | Supabase (PostgreSQL) |

---

## Project Structure

```
ClauseIQ/
├── backend/
│   ├── requirements.txt
│   ├── .env                        ← secrets (do NOT commit)
│   └── src/
│       ├── api/
│       │   ├── main.py             ← FastAPI app, CORS, startup hooks
│       │   └── routes/
│       │       ├── analyse.py      ← POST /api/analyse
│       │       └── compare.py      ← POST /api/compare
│       ├── extraction/
│       │   ├── extractor.py        ← PDF / DOCX text extraction
│       │   ├── cleaner.py          ← strip watermarks / boilerplate
│       │   ├── llamaparse_backend.py
│       │   └── fallback_backend.py
│       ├── chunker/
│       │   ├── chunker.py          ← Gemini → regex dispatch
│       │   ├── gemini.py           ← Gemini semantic chunker
│       │   ├── regex.py            ← regex boundary fallback
│       │   └── helpers.py
│       ├── comparator/
│       │   └── comparator.py       ← L1 heading + L2 semantic match + diffs
│       ├── scorer/
│       │   ├── scorer.py           ← risk scoring + delta + negotiation
│       │   └── knowledge.py        ← firm knowledge node loader
│       ├── models/
│       │   └── schemas.py          ← Pydantic models
│       ├── prompts/                ← LLM prompt templates
│       └── db.py                   ← Supabase client + availability check
├── frontend/
│   ├── index.html
│   ├── styles.css
│   └── app.js
└── supabase/
    ├── schema.sql
    └── seed.sql                    ← 10 firm knowledge nodes
```

---

## Prerequisites

- Python 3.11+
- Node.js is **not** required — the frontend is plain HTML/JS served by FastAPI
- A Supabase project (free tier is fine) — optional but recommended
- AWS credentials with Bedrock access, or a compatible LLM API key

---

## Setup

### 1. Clone and enter the project

```bash
git clone <your-repo-url>
cd ClauseIQ
```

### 2. Install backend dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 3. Configure environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```env
# AWS Bedrock (used for Claude risk scoring)
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_REGION=ap-southeast-2
AWS_BEDROCK_MODEL_ID=amazon.nova-pro-v1:0

# Supabase (optional — app works without it)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your_anon_key

# Chunking (optional — falls back to regex if absent)
GEMINI_API_KEY=your_gemini_key

# Document parsing (optional — enhances scanned PDF support)
LLAMA_CLOUD_API_KEY=your_llama_key
```

### 4. Set up Supabase (optional)

In your Supabase project's SQL editor, run the schema and seed files in order:

```sql
-- 1. Create tables
\i supabase/schema.sql

-- 2. Load the 10 firm knowledge nodes
\i supabase/seed.sql
```

Or paste the contents of each file directly into the SQL editor.

### 5. Start the server

```bash
cd backend
uvicorn src.api.main:app --reload --port 8000
```

Open `http://localhost:8000` in your browser. The frontend is served automatically by FastAPI.

---

## API Reference

### `POST /api/analyse`

Single document risk analysis.

**Request:** `multipart/form-data`

| Field | Type | Description |
|---|---|---|
| `file` | File | Contract to analyse (.pdf or .docx, max 20 MB) |

**Response:** `AnalyseResponse`

```json
{
  "filename": "contract.pdf",
  "clauses": [
    {
      "chunk_index": 0,
      "clause_number": "5.2",
      "clause_title": "Liability",
      "clause_type": "limitation",
      "text": "...",
      "page_number": 3
    }
  ],
  "risk_scores": [
    {
      "chunk_index": 0,
      "clause_number": "5.2",
      "clause_title": "Liability",
      "score": 8,
      "risk_level": "HIGH",
      "risk_factors": ["Uncapped liability"],
      "constraint_violations": ["C-010"],
      "recommendation": "Cap liability at 2x annual contract value.",
      "source": "llm"
    }
  ],
  "risk_summary": {
    "high": 1,
    "medium": 3,
    "low": 5,
    "unscored": 0
  }
}
```

---

### `POST /api/compare`

Two-document comparison with risk delta.

**Request:** `multipart/form-data`

| Field | Type | Description |
|---|---|---|
| `file_v1` | File | Original contract version (.pdf or .docx) |
| `file_v2` | File | Revised contract version (.pdf or .docx) |

**Response:** `CompareResponse`

```json
{
  "comparison": [
    {
      "match_type": "MODIFIED",
      "clause_number_v1": "12",
      "clause_number_v2": "12",
      "clause_title": "Governing Law",
      "similarity_score": 0.61,
      "diff_text": "...",
      "risk_delta": "INCREASED",
      "score_v1": 4,
      "score_v2": 7
    }
  ],
  "net_delta": "INCREASED",
  "suggestions": [
    {
      "clause_number": "12",
      "clause_title": "Governing Law",
      "action": "Reinstate SIAC arbitration clause",
      "reason": "Arbitration removed; violates firm constraint C-013",
      "constraint_id": "C-013",
      "risk_delta": "INCREASED"
    }
  ]
}
```

---

### `GET /health`

Returns `{"status": "ok"}`. Use to verify the server is up.

---

## Firm Knowledge Nodes

The system ships with 10 pre-loaded nodes that override LLM scoring when triggered:

| ID | Type | Rule |
|---|---|---|
| C-010 | CONSTRAINT | Liability must be capped at ≤ 2× annual contract value |
| C-011 | CONSTRAINT | Non-compete / non-solicitation duration must not exceed 12 months |
| C-012 | CONSTRAINT | IP assignment clauses must include a pre-existing IP carve-out |
| C-013 | CONSTRAINT | Arbitration (SIAC / LCIA) preferred for cross-border contracts |
| C-014 | CONSTRAINT | Termination for convenience requires ≥ 90 days notice |
| AP-010 | ANTI_PATTERN | One-sided indemnification must be flagged and made mutual |
| AP-011 | ANTI_PATTERN | Auto-renewal opt-out windows under 90 days must be flagged |
| D-010 | DECISION | Every NDA must include return/destruction of confidential materials clause |
| D-011 | DECISION | Liquidated damages clauses must be proportionate to actual estimated loss |
| D-012 | DECISION | Clear dispute resolution clause (jurisdiction / arbitration seat) is mandatory |

---

## Risk Score Reference

| Score | Level | Colour |
|---|---|---|
| 1–3 | LOW | Green |
| 4–6 | MEDIUM | Orange |
| 7–10 | HIGH | Red |

Firm constraint violations override the LLM score and force a level (e.g., uncapped liability is always HIGH regardless of clause wording).

---

## Running Tests

```bash
cd backend
pytest src/chunker/test_chunker.py
pytest src/comparator/test_comparator.py
pytest src/scorer/test_scorer.py
```

---

## Architecture Notes

**Chunking strategy:** The chunker uses Gemini as its primary backend. It sends the full extracted document text to Gemini with a structured prompt asking for clause boundaries, numbers, titles, and types. If Gemini is unavailable or returns malformed JSON, the system falls back to a regex-based boundary detector that identifies clause starts from numbered headings (`1.`, `1.1`, `CLAUSE 3`), uppercase section titles (`CONFIDENTIALITY`, `INDEMNIFICATION`), and schedule markers (`SCHEDULE A`).

**Matching strategy:** The comparator runs two levels. Level 1 matches by normalised heading (stripping `clause`, `section`, `article` prefixes, normalising `1.0` → `1`). Level 2 uses TF-IDF cosine similarity for clauses that don't match on heading — this handles renumbered or restructured contracts. Clauses with >95% text similarity are marked `UNCHANGED`; those below the semantic threshold are marked `ADDED` or `REMOVED`; everything in between is `MODIFIED` and gets a word-level diff via `difflib`.

**Split detection:** When a single clause in v1 corresponds to multiple clauses in v2 (e.g., clause 8 split into 8 and 8A), the comparator detects shared base numbers and uses content similarity to recognise the split rather than treating it as a deletion plus two additions.

For a detailed breakdown, see `docs/architecture.md`.

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | Yes | AWS credentials for Bedrock |
| `AWS_SECRET_ACCESS_KEY` | Yes | AWS credentials for Bedrock |
| `AWS_REGION` | Yes | AWS region (e.g. `ap-southeast-2`) |
| `AWS_BEDROCK_MODEL_ID` | Yes | Bedrock model ID or ARN |
| `AWS_SESSION_TOKEN` | No | Required for temporary credentials |
| `SUPABASE_URL` | No | Supabase project URL |
| `SUPABASE_ANON_KEY` | No | Supabase service role key |
| `GEMINI_API_KEY` | No | Enables semantic chunking (falls back to regex without it) |
| `LLAMA_CLOUD_API_KEY` | No | Enables LlamaParse OCR for scanned PDFs |

---

## Supported File Types

| Format | Notes |
|---|---|
| `.pdf` | Text-based PDFs via PyMuPDF; scanned PDFs via LlamaParse (requires API key) |
| `.docx` | Via python-docx; heading structure is preserved |
| `.doc` | Not supported — convert to `.docx` first |

Maximum file size: **20 MB** per upload.
