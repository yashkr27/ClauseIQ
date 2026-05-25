"""
Layer 4 — Risk Scorer
Rules satisfied: A2, S1, S2, S3, S4, SB1

Input:  list[Clause], list[knowledge_nodes]
Output: list[RiskScore]
"""

import os
import re
import json
import hashlib
from ..models.schemas import Clause, RiskScore
from .knowledge import load_knowledge_nodes

# Lazy Bedrock client initialization
_client = None

# Global in-memory cache: clause SHA-256 → scored result
_risk_score_cache = {}


def _get_anthropic_client():
    global _client
    if _client is None:
        import boto3
        aws_access_key    = os.getenv("AWS_ACCESS_KEY_ID")
        aws_secret_key    = os.getenv("AWS_SECRET_ACCESS_KEY")
        aws_session_token = os.getenv("AWS_SESSION_TOKEN")
        aws_region        = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"

        kwargs = {
            "service_name": "bedrock-runtime",
            "region_name": aws_region.strip() if aws_region else "us-east-1"
        }
        if aws_access_key and aws_secret_key:
            kwargs["aws_access_key_id"]     = aws_access_key.strip()
            kwargs["aws_secret_access_key"] = aws_secret_key.strip()
            if aws_session_token:
                kwargs["aws_session_token"] = aws_session_token.strip()

        _client = boto3.client(**kwargs)
    return _client


def _get_model_name(client) -> str:
    val = (
        os.getenv("AWS_BEDROCK_MODEL_ID")
        or os.getenv("MODEL_NAME")
        or "arn:aws:bedrock:ap-southeast-2:593106394881:inference-profile/global.anthropic.claude-haiku-4-5-20251001-v1:0"
    )
    return val.strip()


class BedrockResponseContent:
    def __init__(self, text: str):
        self.text = text


class BedrockResponse:
    def __init__(self, text: str):
        self.content = [BedrockResponseContent(text)]


def _call_llm(client, model_name: str, prompt: str, hashed_user: str) -> BedrockResponse:
    """
    Invokes Amazon Bedrock via boto3 converse() API.
    Graceful fallback to UNSCORED sentinel on any failure.
    """
    try:
        if not prompt.strip():
            raise ValueError("Prompt cannot be empty")

        messages = [
            {
                "role": "user",
                "content": [{"text": prompt.strip()}]
            }
        ]

        response = client.converse(
            modelId=model_name,
            messages=messages,
            inferenceConfig={"maxTokens": 1024, "temperature": 0.2}
        )
        generated_text = response["output"]["message"]["content"][0]["text"]
        return BedrockResponse(generated_text)

    except Exception as e:
        error_msg = str(e)
        if hasattr(e, "response") and isinstance(e.response, dict) and "Error" in e.response:
            error_msg = e.response["Error"].get("Message", error_msg)
        fallback_json = json.dumps({
            "score": None,
            "risk_factors": [f"Scoring unavailable (Bedrock error: {error_msg})"],
            "recommendation": "Manual review required — risk scoring service was unavailable."
        })
        return BedrockResponse(fallback_json)


# ── Word-number normalisation ─────────────────────────────────────────────────

_WORD_NUMS = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
    'eleven': 11, 'twelve': 12, 'eighteen': 18, 'twenty': 20,
    'twenty-four': 24, 'twenty four': 24,
}


def _normalise_numeric_text(text: str) -> str:
    """Replace written numbers with digits so regex duration checks work."""
    result = text
    for word, val in sorted(_WORD_NUMS.items(), key=lambda x: -len(x[0])):
        result = re.sub(rf'\b{re.escape(word)}\b', str(val), result, flags=re.IGNORECASE)
    return result


# ── Deterministic constraint checks (Rule S2) ─────────────────────────────────

def _check_constraints(clause: Clause, nodes: list[dict]) -> tuple[int, list[str]]:
    """
    Returns (minimum_score_from_constraints, [triggered_constraint_ids]).
    Rule S2: overrides LLM score if higher.
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

    # C-011: non-compete / non-solicitation / standstill > 12 months
    if any(w in text for w in ['non-compete', 'non-solicitation', 'noncompete',
                                'nonsolicitation', 'standstill', 'stand-still',
                                'non-solicit', 'non compete', 'non solicitation',
                                'non solicit']):
        norm = _normalise_numeric_text(text)
        months = re.findall(r'(\d+)\s*month', norm)
        years  = re.findall(r'(\d+)\s*year',  norm)
        duration_months = max([int(m) for m in months], default=0)
        duration_months = max(duration_months, max([int(y) * 12 for y in years], default=0))
        if duration_months > 12:
            violations.append('C-011')
            min_score = max(min_score, 7)

    # C-012: broad IP assignment without carve-out
    if any(w in text for w in ['all intellectual property', 'all ip', 'all inventions']):
        if 'carve' not in text and 'pre-existing' not in text and 'prior ip' not in text:
            violations.append('C-012')
            min_score = max(min_score, 7)

    # C-013: no arbitration in dispute/governing law clause (title OR body scan)
    if (any(w in title for w in ['dispute', 'governing', 'jurisdiction', 'resolution', 'law'])
            or any(w in text[:300] for w in ['governing law', 'jurisdiction', 'venue',
                                              'courts of', 'applicable law'])):
        if 'arbitration' not in text and 'arbitrate' not in text:
            violations.append('C-013')
            min_score = max(min_score, 6)

    # C-014: termination notice < 90 days
    if 'terminat' in text and 'notice' in text:
        days = re.findall(r'(\d+)\s*day', text)
        if days:
            min_days = min(int(d) for d in days)
            if min_days < 90:
                violations.append('C-014')
                min_score = max(min_score, 6)

    # AP-010: one-sided indemnification
    if 'indemnif' in text and 'mutual' not in text and 'both parties' not in text:
        violations.append('AP-010')
        min_score = max(min_score, 6)

    # AP-011: auto-renewal with short opt-out window
    if 'auto-renew' in text or 'automatic renewal' in text:
        days = [int(d) for d in re.findall(r'(\d+)\s*day', text)]
        if days and min(days) < 90:
            violations.append('AP-011')
            min_score = max(min_score, 6)

    # D-010: NDA/confidentiality clause missing return-of-materials obligation
    if any(w in text for w in ['confidential', 'non-disclosure', 'nda']):
        if 'return' not in text and 'destroy' not in text and 'destruction' not in text:
            violations.append('D-010')
            min_score = max(min_score, 5)

    # D-011: disproportionate liquidated damages / penalty clause
    if 'liquidated damages' in text or ('penalty' in text and 'breach' in text):
        violations.append('D-011')
        min_score = max(min_score, 5)

    return min_score, violations


# ── LLM prompt builder (Rule S1) ─────────────────────────────────────────────

def _build_prompt(clause: Clause, nodes: list[dict]) -> str:
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _score_level(score: int) -> str:
    if score == 0:  return 'UNSCORED'
    if score <= 3:  return 'LOW'
    if score <= 6:  return 'MEDIUM'
    return 'HIGH'


def _baseline_score(clause: Clause) -> tuple[int, list[str], str]:
    """Fast non-LLM baseline when no constraints fire and enrich=False."""
    text  = clause.text.lower()
    score = 2
    factors = ["No firm constraint triggered."]

    if 'indemnif' in text and 'mutual' not in text:
        score = max(score, 4)
        factors.append("Indemnity language should be reviewed for one-sided allocation.")

    if 'auto-renew' in text or 'automatic renewal' in text:
        days = [int(d) for d in re.findall(r'(\d+)\s*day', text)]
        if days and min(days) < 90:
            score = max(score, 5)
            factors.append("Auto-renewal opt-out window is shorter than 90 days.")

    if 'liquidated damages' in text or 'penalty' in text:
        score = max(score, 5)
        factors.append("Liquidated damages or penalty language requires proportionality review.")

    if 'personal guarantee' in text or 'guarantor' in text:
        score = max(score, 7)
        factors.append("Personal guarantee language can create high individual exposure.")

    if score <= 3:
        recommendation = "No immediate firm-policy issue detected; review in ordinary course."
    elif score <= 6:
        recommendation = "Review commercially and confirm the allocation is acceptable."
    else:
        recommendation = "Escalate for legal review before accepting this clause."

    return score, factors, recommendation


# ── Core scoring functions ────────────────────────────────────────────────────

def score_clause(clause: Clause, nodes: list[dict], enrich: bool = False) -> RiskScore:
    """
    Scores a single clause.
    Priority: cache → deterministic constraints → LLM (if enrich=True).
    Rule S2: constraint score overrides LLM score.
    """
    # 1. In-memory cache check
    clause_hash = hashlib.sha256(clause.text.strip().encode('utf-8')).hexdigest()
    if clause_hash in _risk_score_cache:
        cached = _risk_score_cache[clause_hash]
        return RiskScore(
            chunk_index=clause.chunk_index,
            clause_number=clause.clause_number,
            clause_title=clause.clause_title,
            score=cached['score'],
            risk_level=cached['risk_level'],
            risk_factors=cached['risk_factors'],
            constraint_violations=cached['constraint_violations'],
            recommendation=cached['recommendation'],
            source="cache"
        )

    # 2. Deterministic constraint checks (Rule S2)
    constraint_min, violations = _check_constraints(clause, nodes)

    # 3. Decision path
    if violations:
        final_score = constraint_min
        risk_level  = _score_level(final_score)
        triggered_nodes = [n for n in nodes if n['id'] in violations]

        if not enrich:
            risk_factors   = [f"Constraint triggered: {n['title']}" for n in triggered_nodes]
            recommendation = "; ".join(n['content'] for n in triggered_nodes)
            source         = "deterministic"
        else:
            prompt      = _build_prompt(clause, nodes)
            hashed_user = hashlib.sha256(b"clauseiq-anonymous-user").hexdigest()
            client      = _get_anthropic_client()
            model_name  = _get_model_name(client)
            response    = _call_llm(client, model_name, prompt, hashed_user)
            raw         = re.sub(r'^```json\s*|```$', '', response.content[0].text.strip(), flags=re.MULTILINE).strip()
            data        = json.loads(raw)
            risk_factors   = data.get('risk_factors', [])
            recommendation = data.get('recommendation', '')
            source         = "hybrid"

    else:
        if not enrich:
            final_score, risk_factors, recommendation = _baseline_score(clause)
            risk_level = _score_level(final_score)
            source     = "deterministic"
        else:
            prompt      = _build_prompt(clause, nodes)
            hashed_user = hashlib.sha256(b"clauseiq-anonymous-user").hexdigest()
            client      = _get_anthropic_client()
            model_name  = _get_model_name(client)
            response    = _call_llm(client, model_name, prompt, hashed_user)
            raw         = re.sub(r'^```json\s*|```$', '', response.content[0].text.strip(), flags=re.MULTILINE).strip()
            data        = json.loads(raw)

            llm_score_raw = data.get('score')
            if llm_score_raw is None:
                final_score = 0
                risk_level  = 'UNSCORED'
            else:
                final_score = max(1, min(10, int(llm_score_raw)))
                risk_level  = _score_level(final_score)

            risk_factors   = data.get('risk_factors', [])
            recommendation = data.get('recommendation', '')
            source         = "llm"

    # 4. Cache and return
    _risk_score_cache[clause_hash] = {
        'score':                final_score,
        'risk_level':           risk_level,
        'risk_factors':         risk_factors,
        'constraint_violations': violations,
        'recommendation':       recommendation,
    }

    return RiskScore(
        chunk_index=clause.chunk_index,
        clause_number=clause.clause_number,
        clause_title=clause.clause_title,
        score=final_score,
        risk_level=risk_level,
        risk_factors=risk_factors,
        constraint_violations=violations,
        recommendation=recommendation,
        source=source
    )


def score_document(clauses: list[Clause], enrich: bool = True) -> list[RiskScore]:
    """Score all clauses. Rule SB1: loads knowledge nodes automatically."""
    nodes = load_knowledge_nodes()
    return [score_clause(c, nodes, enrich=enrich) for c in clauses]


def compute_risk_delta(scores_v1: list[RiskScore],
                       scores_v2: list[RiskScore],
                       comparison_results: list) -> list:
    """
    Rule S4: attach risk delta to each ComparisonResult.
    delta = score_v2 - score_v1
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
            r = r.model_copy(update={
                'risk_delta': 'INCREASED' if s2 >= 7 else 'UNCHANGED',
                'score_v2': s2,
            })
        elif s1 is not None:
            r = r.model_copy(update={
                'risk_delta': 'DECREASED' if s1 >= 7 else 'UNCHANGED',
                'score_v1': s1,
            })
        updated.append(r)
    return updated


# ── Negotiation suggestions (Innovation) ──────────────────────────────────────

_NEGOTIATION_ACTIONS: dict[str, str] = {
    'C-010': "Counter: insist on liability cap at 2× annual contract value.",
    'C-011': "Counter: reduce non-compete / non-solicitation duration to 12 months maximum.",
    'C-012': "Counter: add explicit carve-out for pre-existing IP before signing.",
    'C-013': "Restore: re-insert arbitration clause (SIAC or LCIA rules preferred).",
    'C-014': "Counter: extend termination-for-convenience notice to minimum 90 days.",
    'AP-010': "Counter: replace one-sided indemnity with mutual indemnification.",
    'AP-011': "Counter: extend auto-renewal opt-out window to minimum 90 days.",
    'D-010': "Add: include clause requiring return or certified destruction of confidential materials on termination.",
    'D-011': "Revise: ensure liquidated damages amount is proportionate to estimated actual loss.",
}


def suggest_negotiation(comparison_results: list,
                        scores_v1: list[RiskScore],
                        scores_v2: list[RiskScore]) -> list[dict]:
    """
    Combines comparison results + constraint violations into plain-English
    negotiation actions. Only surfaces clauses that changed and have at least
    one triggered CONSTRAINT or ANTI_PATTERN node.

    Returns list[dict] matching NegotiationSuggestion schema.
    """
    nodes = load_knowledge_nodes()
    node_map = {n['id']: n for n in nodes}

    v2_score_map = {s.clause_number: s for s in scores_v2}
    v1_score_map = {s.clause_number: s for s in scores_v1}

    suggestions: list[dict] = []
    seen: set[tuple[str, str]] = set()  # (clause_ref, constraint_id) dedup

    for r in comparison_results:
        if r.match_type == 'UNCHANGED':
            continue

        # Prefer v2 score; fall back to v1 for REMOVED clauses
        score = v2_score_map.get(r.clause_number_v2) or v1_score_map.get(r.clause_number_v1)
        if not score or not score.constraint_violations:
            continue

        clause_ref = r.clause_number_v2 or r.clause_number_v1 or ''

        for cid in score.constraint_violations:
            key = (clause_ref, cid)
            if key in seen:
                continue
            seen.add(key)

            node = node_map.get(cid, {})
            action = _NEGOTIATION_ACTIONS.get(cid, node.get('content', 'Review required.'))

            suggestions.append({
                'clause_number': clause_ref,
                'clause_title':  r.clause_title,
                'action':        action,
                'reason':        node.get('title', cid),
                'constraint_id': cid,
                'risk_delta':    r.risk_delta,
            })

    return suggestions