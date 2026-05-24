"""
Layer 4 — Risk Scorer
Rules satisfied: A2, S1, S2, S3, S4, SB1

Input:  list[Clause], list[knowledge_nodes]
Output: list[RiskScore]
"""

import os
import re
import json
from ..models.schemas import Clause, RiskScore
from .knowledge import load_knowledge_nodes

# Lazy Anthropic client initialization to prevent import-time crashes if API key is missing
_client = None

def _get_anthropic_client():
    global _client
    if _client is None:
        key = os.getenv("ANTHROPIC_API_KEY", "")
        if not key:
            key = "dummy-api-key"
        from anthropic import Anthropic
        _client = Anthropic(api_key=key)
    return _client


# ── CONSTRAINT override rules (S2) ────────────────────────────────────────────
# Logic lives in Python, NOT in the LLM prompt.
# Each entry: (constraint_id, check_function, minimum_score)

def _check_constraints(clause: Clause, nodes: list[dict]) -> tuple[int, list[str]]:
    """
    Returns (minimum_score_from_constraints, [triggered_constraint_ids])
    Rule S2: this result overrides whatever the LLM returned if it's higher.
    """
    text  = clause.text.lower()
    title = clause.clause_title.lower()
    violations = []
    min_score  = 0

    # C-010: uncapped liability
    if ('liability' in text or 'liable' in text):
        if any(w in text for w in ['unlimited', 'uncapped', 'no limit', 'no cap']):
            violations.append('C-010')
            min_score = max(min_score, 8)

    # C-011: non-compete / non-solicitation > 12 months
    if any(w in text for w in ['non-compete', 'non-solicitation', 'noncompete', 'nonsolicitation']):
        months = re.findall(r'(\d+)\s*month', text)
        years  = re.findall(r'(\d+)\s*year', text)
        duration_months = max([int(m) for m in months], default=0)
        duration_months = max(duration_months, max([int(y)*12 for y in years], default=0))
        if duration_months > 12:
            violations.append('C-011')
            min_score = max(min_score, 7)

    # C-012: broad IP assignment without carve-out
    if any(w in text for w in ['all intellectual property', 'all ip', 'all inventions']):
        if 'carve' not in text and 'pre-existing' not in text and 'prior ip' not in text:
            violations.append('C-012')
            min_score = max(min_score, 7)

    # C-013: no arbitration in dispute/governing law clause
    if any(w in title for w in ['dispute', 'governing', 'jurisdiction', 'resolution', 'law']):
        if 'arbitration' not in text and 'arbitrate' not in text:
            violations.append('C-013')
            min_score = max(min_score, 6)

    # C-014: termination notice < 90 days
    if 'terminat' in text and 'notice' in text:
        days  = re.findall(r'(\d+)\s*day', text)
        if days:
            min_days = min(int(d) for d in days)
            if min_days < 90:
                violations.append('C-014')
                min_score = max(min_score, 6)

    return min_score, violations


def _build_prompt(clause: Clause, nodes: list[dict]) -> str:
    """
    Rule S1: inject ALL knowledge nodes into prompt.
    The LLM sees firm policy alongside the clause text.
    """
    node_text = '\n'.join(
        f"[{n['id']} — {n['node_type']}] {n['title']}: {n['content']}"
        for n in nodes
    )
    return f"""You are a legal risk analyst. Score the following contract clause for risk.

FIRM KNOWLEDGE BASE (these rules override general legal norms):
{node_text}

CLAUSE TO SCORE:
Number: {clause.clause_number}
Title: {clause.clause_title}
Type: {clause.clause_type}
Text:
{clause.text}

Respond with ONLY a JSON object, no other text:
{{
  "score": <integer 1-10>,
  "risk_factors": ["factor 1", "factor 2"],
  "recommendation": "<one sentence action>"
}}

Score guide: 1-3=LOW risk, 4-6=MEDIUM risk, 7-10=HIGH risk.
Reference specific firm knowledge node IDs (e.g. C-010) when they apply."""


def _score_level(score: int) -> str:
    if score <= 3:  return 'LOW'
    if score <= 6:  return 'MEDIUM'
    return 'HIGH'


def score_clause(clause: Clause, nodes: list[dict]) -> RiskScore:
    """
    Scores a single clause. Applies CONSTRAINT override after LLM call (rule S2).
    """
    prompt = _build_prompt(clause, nodes)
    
    client = _get_anthropic_client()
    response = client.messages.create(
        model='claude-sonnet-4-20250514',
        max_tokens=500,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = response.content[0].text.strip()
    # Strip any accidental markdown fences
    raw = re.sub(r'^```json\s*|```$', '', raw, flags=re.MULTILINE).strip()
    data = json.loads(raw)

    llm_score   = max(1, min(10, int(data.get('score', 5))))
    risk_factors = data.get('risk_factors', [])
    recommendation = data.get('recommendation', '')

    # Apply CONSTRAINT overrides (S2) — Python logic, not prompt
    constraint_min, violations = _check_constraints(clause, nodes)
    final_score = max(llm_score, constraint_min)

    return RiskScore(
        chunk_index=clause.chunk_index,
        clause_number=clause.clause_number,
        clause_title=clause.clause_title,
        score=final_score,
        risk_level=_score_level(final_score),
        risk_factors=risk_factors,
        constraint_violations=violations,
        recommendation=recommendation,
    )


def score_document(clauses: list[Clause]) -> list[RiskScore]:
    """Score all clauses in a document. Rule SB1: loads nodes automatically."""
    nodes = load_knowledge_nodes()
    return [score_clause(c, nodes) for c in clauses]


def compute_risk_delta(scores_v1: list[RiskScore],
                       scores_v2: list[RiskScore],
                       comparison_results: list) -> list:
    """
    Rule S4: attach risk delta to each ComparisonResult.
    delta = score_v2 - score_v1
    > 0 → INCREASED, < 0 → DECREASED, = 0 → UNCHANGED
    """
    v1_map = {s.clause_number: s.score for s in scores_v1}
    v2_map = {s.clause_number: s.score for s in scores_v2}

    updated = []
    for r in comparison_results:
        s1 = v1_map.get(r.clause_number_v1)
        s2 = v2_map.get(r.clause_number_v2)
        if s1 is not None and s2 is not None:
            delta = s2 - s1
            r = r.model_copy(update={
                'risk_delta': 'INCREASED' if delta > 0 else ('DECREASED' if delta < 0 else 'UNCHANGED'),
                'score_v1': s1,
                'score_v2': s2,
            })
        elif s2 is not None:
            r = r.model_copy(update={'risk_delta': 'N/A', 'score_v2': s2})
        elif s1 is not None:
            r = r.model_copy(update={'risk_delta': 'N/A', 'score_v1': s1})
        updated.append(r)
    return updated
