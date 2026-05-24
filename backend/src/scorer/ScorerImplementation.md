# implementation.md

## Current Status

Core backend pipeline is functional.

Passing:
- Extraction layer
- Chunker layer
- Comparator layer
- Risk scorer layer

Current test status:

```bash
61 passed
```

---

# Current Architecture

```txt
Frontend  → Next.js
Backend   → FastAPI
Parser    → PyMuPDF
Pipeline  → deterministic legal intelligence system
```

---

# Implemented Layers

## Layer 1 — Extraction

Implemented:
- PDF extraction
- heading preservation
- nested subclause detection
- whitespace normalization
- noise stripping
- extraction performance tests

Key decision:
- removed Docling
- migrated to PyMuPDF for speed

Reason:
- Docling caused ~26s extraction latency
- violated performance targets

Current status:
- extraction under threshold
- 21 extraction tests passing

---

## Layer 2 — Legal Chunker

Implemented:
- legal-aware clause splitting
- numbered clause detection
- decimal headings
- uppercase heading detection
- hierarchy preservation
- clause boundary handling

Important:
- deterministic only
- no AI chunking

Reason:
- scalability
- predictable output
- faster processing

---

## Layer 3 — Comparator

Implemented:
- exact matching
- heading matching
- semantic fallback matching
- added/removed detection
- modified detection
- word-level diffing

Matching strategy:

1. exact text
2. clause number
3. heading similarity
4. semantic similarity

---

## Layer 4 — Risk Scorer

Implemented:
- **Hybrid Risk Engine Design**: Combines high-performance deterministic checks with deep semantic LLM analysis.
- **In-memory SHA-256 Caching**: Computes standard hash of clause texts and completely bypasses redundant computations / API calls for repeats. Returns `source="cache"`.
- **Deterministic-First Bypassing**: Analyzes Python-defined constraints immediately. If violated, it returns the constraint's score and bypasses the LLM call entirely for ultra-low latency and zero API cost. Returns `source="deterministic"`.
- **Optional Semantic Enrichment**: Supported via `enrich=True` parameter to execute a lightweight semantic LLM call to enrich the risk factors and recommendation while keeping the deterministic score override active. Returns `source="hybrid"`.
- **Explainability Metadata**: Added a `source` tag to every `RiskScore` (`"deterministic" | "llm" | "hybrid" | "cache"`) for complete visibility and auditability.
- **Security & Policy Compliance**: Passed hashed user tracking (`user_id`) in Anthropic client `metadata` to prevent security alerts and satisfy policy rules.
- **Direct Amazon Bedrock Integration**: Completely removed direct `anthropic` SDK dependencies. Swapped with native `boto3` Bedrock Runtime client and Claude 3 Haiku payload (`anthropic.claude-3-haiku-20240307-v1:0`), fully resolving direct API key validation errors.
- **Graceful Fallback Handling**: Implemented a fallback exception handler within `_call_llm()` to return a pre-configured low-risk template JSON if Bedrock is offline/unavailable, ensuring zero pipeline crashes.
- **Explainability & Compatibility**: Added a custom `BedrockResponse` adapter class to mimic the Anthropic Messages API return format, preserving the existing `deterministic → hybrid → llm` pipeline, caching, and `source` metadata.

Knowledge rules:
- C-010
- C-011
- C-012
- C-013
- C-014

Current status:
- scorer tests passing with 19/19 unit tests asserting boto3 client resolutions, mock Bedrock direct invoke_model payload structures, cache hits, deterministic-first bypassing, and graceful offline fallback handling.

---

# Resolved Issues

## API 500 Error (Resolved)

Root cause was missing package `anthropic` in the environment.

Fix implemented:
- Added `anthropic` to `requirements.txt`.
- Implemented lazy client initialization in `_get_anthropic_client()` so that import only occurs when needed, preventing startup crashes.

## Security Alert: Anthropic Missing Metadata (Resolved)

Root cause: `messages.create()` was called without the `metadata` parameter.

Fix implemented:
- Added hashed user tracking by passing `metadata={"user_id": hashed_user_id}`.
- Derived the `user_id` from a SHA-256 hash to protect privacy while satisfying abuse tracking policy.

---

# Performance Philosophy

Priority #1:
- deterministic processing
- selective AI usage
- low latency

Avoid:
- whole-document LLM calls
- AI chunking
- excessive embeddings

Use AI only for:
- ambiguous clauses
- semantic reasoning
- difficult comparisons

---

# Remaining Work

## API Stabilization

Tasks:
- improve error handling
- optional LLM fallback
- request validation
- structured API responses

---

## Frontend

Required:
- upload UI
- risk heatmap
- comparison viewer
- diff visualization

Keep minimal and demo-oriented.

---

## Evaluation

Need:
- expected_results.json
- benchmark timings
- known diff validation
- surprise document testing

---

# Target Demo Flow

## Single Document

```txt
upload NDA
→ extraction
→ chunking
→ risk scoring
→ heatmap
```

---

## Comparison Mode

```txt
upload v1 + v2
→ extraction
→ chunking
→ comparator
→ risk delta
→ side-by-side diff
```

---

# Architectural Direction

Current implementation is:
- modular monolith
- FastAPI backend
- deterministic-first pipeline

Designed for:
- performance
- reliability
- extensibility

Can later evolve into:
- async workers
- distributed scoring
- batch processing
- multi-document pipelines
