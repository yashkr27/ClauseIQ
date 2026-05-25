create table if not exists knowledge_nodes (
  id text primary key,
  node_type text not null,
  title text not null,
  content text not null,
  practice_area text,
  tags jsonb default '[]'
);

create table if not exists documents (
  id uuid primary key default gen_random_uuid(),
  filename text not null,
  uploaded_at timestamptz default now(),
  content_text text
);

create table if not exists document_chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid references documents(id) on delete cascade,
  chunk_index integer not null,
  clause_number text,
  clause_title text,
  clause_type text,
  text text
);

create table if not exists risk_scores (
  id uuid primary key default gen_random_uuid(),
  chunk_id uuid references document_chunks(id) on delete cascade,
  score integer,
  risk_factors jsonb default '[]',
  constraint_violations jsonb default '[]',
  recommendation text
);

create table if not exists comparison_results (
  id uuid primary key default gen_random_uuid(),
  doc_v1_id uuid references documents(id) on delete cascade,
  doc_v2_id uuid references documents(id) on delete cascade,
  chunk_v1_id uuid references document_chunks(id),
  chunk_v2_id uuid references document_chunks(id),
  match_type text check (match_type in ('UNCHANGED','MODIFIED','ADDED','REMOVED')),
  similarity_score float,
  diff_text text
);