# ClauseIQ

ClauseIQ is a demo-ready legal document intelligence app for the BRAHMO assessment. It extracts contract text from PDF/DOCX files, chunks it into legal clauses, scores clause risk against firm knowledge nodes, and compares two document versions with word-level diffs and risk deltas.

## Features

- Single-document risk heatmap with LOW, MEDIUM, HIGH, and UNSCORED states.
- Clause-aware chunking using legal headings, alphanumeric clauses, schedules, annexures, and a paragraph fallback for unstructured contracts.
- Version comparison with heading matching, TF-IDF semantic matching, split-clause detection, and added/removed classification.
- Deterministic firm-constraint scoring for liability caps, non-competes/non-solicits, IP carve-outs, arbitration, and termination notice.
- Optional Bedrock Claude enrichment for clauses that do not trigger deterministic constraints.
- Static frontend served by FastAPI at `/`.

## Setup

```powershell
cd C:\Users\USER\Desktop\ClauseIQ
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
Copy-Item .env.example .env
```

Fill `.env` with Bedrock or Supabase values if available. The app still runs without Supabase because it falls back to `supabase/seed.sql` for the 10 firm knowledge nodes.

## Run

```powershell
cd C:\Users\USER\Desktop\ClauseIQ\backend
python -m uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

## Test

```powershell
cd C:\Users\USER\Desktop\ClauseIQ\backend
python -m pytest src -q
```

## Demo Flow

1. Analyse `test-data/ndav1.pdf` to show the risk heatmap and firm constraints.
2. Compare `test-data/ndav1.pdf` with `test-data/ndav2.pdf` to show modified, added, and removed clauses plus word-level diffs.
3. Use the comparator split-clause test as the SPA restructure proof point.
4. Try a new text-based PDF/DOCX to show the generalized chunker and risk rules are not hardcoded to NDAs.
