"""
Loads 10 firm knowledge nodes.
Rule SB1: loads from Supabase if available, from seed.sql parse if not.
Rule S1: these nodes are injected into every scoring call.
"""
import os
import re
from ..db import db_available, mem_insert, mem_get

# Adjusted path to match exactly 3 levels up: backend/src/scorer/knowledge.py -> supabase/seed.sql
SEED_PATH = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'supabase', 'seed.sql')

def _parse_seed_sql(path: str) -> list[dict]:
    """Parse seed.sql INSERT statements into dicts."""
    nodes = []
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    # Matches individual tuples within the seed file regardless of VALUES formatting
    pattern = re.compile(
        r"\('([^']+)','([^']+)','([^']+)','([^']+)','([^']+)','([^']+)'\)"
    )
    for m in pattern.finditer(content):
        nodes.append({
            'id': m.group(1),
            'node_type': m.group(2),
            'title': m.group(3),
            'content': m.group(4),
            'practice_area': m.group(5),
            'tags': m.group(6),
        })
    return nodes

def load_knowledge_nodes() -> list[dict]:
    """Returns all 10 knowledge nodes from DB or in-memory store."""
    if db_available():
        from ..db import get_client
        res = get_client().table('knowledge_nodes').select('*').execute()
        return res.data
    existing = mem_get('knowledge_nodes')
    if not existing:
        for node in _parse_seed_sql(SEED_PATH):
            mem_insert('knowledge_nodes', node)
    return mem_get('knowledge_nodes')
