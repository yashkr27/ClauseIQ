"""
DB layer — Supabase client when env vars are set, in-memory fallback otherwise.
Lets all layers run and be tested before Supabase is configured.
"""
import os
from typing import Optional
import uuid

_client = None

def get_client():
    global _client
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_ANON_KEY", "")
    if url and key and _client is None:
        from supabase import create_client
        _client = create_client(url, key)
    return _client

def db_available() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_ANON_KEY"))


# ── in-memory store (used when DB not configured) ──────────────────────────
_store: dict = {
    "knowledge_nodes": [],
    "documents": [],
    "document_chunks": [],
    "risk_scores": [],
    "comparison_results": [],
}

def mem_insert(table: str, row: dict) -> dict:
    _store[table].append(row)
    return row

def mem_get(table: str, filters: Optional[dict] = None) -> list:
    rows = _store[table]
    if filters:
        for k, v in filters.items():
            rows = [r for r in rows if r.get(k) == v]
    return rows

def mem_clear(table: str):
    _store[table].clear()

def insert_row(table: str, row: dict) -> dict:
    """Insert into Supabase if available, else in-memory store."""
    row.setdefault("id", str(uuid.uuid4()))
    client = get_client()
    if client:
        result = client.table(table).insert(row).execute()
        return result.data[0]
    return mem_insert(table, row)

def fetch_rows(table: str, filters: Optional[dict] = None) -> list:
    """Fetch from Supabase if available, else in-memory store."""
    client = get_client()
    if client:
        query = client.table(table).select("*")
        if filters:
            for k, v in filters.items():
                query = query.eq(k, v)
        return query.execute().data
    return mem_get(table, filters)