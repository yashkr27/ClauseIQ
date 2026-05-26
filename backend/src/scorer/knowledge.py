"""
Loads firm knowledge nodes.
Rule SB1: always tries Supabase first, falls back to seed.sql parse.
Rule S1:  nodes are injected into every scoring call.

Priority:
  1. Supabase  — live source of truth, evaluator can add nodes at runtime
  2. seed.sql  — offline fallback so scoring never breaks without DB
"""

import os
import re

from ..db import db_available, mem_insert, mem_get

SEED_PATH = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'supabase', 'seed.sql'
)

# In-process cache so we don't hit Supabase on every single clause
_NODE_CACHE: list[dict] | None = None


def _parse_seed_sql(path: str) -> list[dict]:
    """Parse seed.sql INSERT statements into dicts."""
    nodes = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        return []

    pattern = re.compile(
        r"\('([^']+)','([^']+)','([^']+)','([^']+)','([^']+)','([^']+)'\)"
    )
    for m in pattern.finditer(content):
        nodes.append({
            'id':            m.group(1),
            'node_type':     m.group(2),
            'title':         m.group(3),
            'content':       m.group(4),
            'practice_area': m.group(5),
            'tags':          m.group(6),
        })
    return nodes


def _load_from_supabase() -> list[dict]:
    from ..db import get_client
    res = get_client().table('knowledge_nodes').select('*').execute()
    return res.data or []


def load_knowledge_nodes(force_refresh: bool = False) -> list[dict]:
    """
    Returns all knowledge nodes.

    Call order:
      1. In-process cache (skipped if force_refresh=True)
      2. Supabase  — full table, any nodes added via UI are included
      3. seed.sql  — offline fallback
      4. mem_get   — last-resort in-memory store

    Pass force_refresh=True after the evaluator adds a new node at runtime.
    """
    global _NODE_CACHE

    if _NODE_CACHE and not force_refresh:
        return _NODE_CACHE

    # 1. Supabase
    if db_available():
        try:
            nodes = _load_from_supabase()
            if nodes:
                _NODE_CACHE = nodes
                return _NODE_CACHE
        except Exception:
            pass   # fall through to seed

    # 2. seed.sql parse
    nodes = _parse_seed_sql(SEED_PATH)
    if nodes:
        # Populate in-memory store so comparator / scorer stay consistent
        for node in nodes:
            mem_insert('knowledge_nodes', node)
        _NODE_CACHE = nodes
        return _NODE_CACHE

    # 3. mem_get last resort
    existing = mem_get('knowledge_nodes')
    if existing:
        _NODE_CACHE = existing
        return _NODE_CACHE

    return []


def invalidate_cache() -> None:
    """Call this if knowledge_nodes table is updated at runtime."""
    global _NODE_CACHE
    _NODE_CACHE = None