-- knowledge_nodes: firm CONSTRAINT / ANTI_PATTERN / DECISION nodes
CREATE TABLE knowledge_nodes (
  id          TEXT PRIMARY KEY,          -- e.g. C-010
  node_type   TEXT NOT NULL,             -- CONSTRAINT | ANTI_PATTERN | DECISION
  title       TEXT NOT NULL,
  content     TEXT NOT NULL,
  practice_area TEXT,
  tags        JSONB DEFAULT '[]'
);

-- documents: uploaded files
CREATE TABLE documents (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  filename     TEXT NOT NULL,
  uploaded_at  TIMESTAMPTZ DEFAULT now(),
  content_text TEXT
);

-- document_chunks: clauses extracted from a document
CREATE TABLE document_chunks (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id  UUID REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index  INT NOT NULL,
  clause_number TEXT,
  clause_title  TEXT,
  clause_type   TEXT,   -- definition|obligation|limitation|termination|indemnity|ip|confidentiality|general
  text          TEXT NOT NULL
);

-- risk_scores: per-clause risk scoring results
CREATE TABLE risk_scores (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  chunk_id              UUID REFERENCES document_chunks(id) ON DELETE CASCADE,
  score                 INT NOT NULL CHECK (score BETWEEN 1 AND 10),
  risk_factors          JSONB DEFAULT '[]',
  constraint_violations JSONB DEFAULT '[]',
  recommendation        TEXT
);

-- comparison_results: clause-level diff between two document versions
CREATE TABLE comparison_results (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  doc_v1_id        UUID REFERENCES documents(id),
  doc_v2_id        UUID REFERENCES documents(id),
  chunk_v1_id      UUID REFERENCES document_chunks(id),
  chunk_v2_id      UUID REFERENCES document_chunks(id),
  match_type       TEXT NOT NULL,   -- UNCHANGED|MODIFIED|ADDED|REMOVED
  similarity_score FLOAT,
  diff_text        TEXT
);
