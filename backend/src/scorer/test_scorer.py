"""
Tests for Layer 4 — Scorer
Run from backend/: python -m pytest src/scorer/test_scorer.py -v -k "not score_clause"
"""

import os
import json
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.scorer.scorer import _check_constraints, _score_level, compute_risk_delta, _normalise_numeric_text
from src.scorer.knowledge import load_knowledge_nodes
from src.models.schemas import Clause, ClauseType, RiskScore, ComparisonResult, MatchType

def _clause(num, title, text):
    return Clause(
        chunk_index=0,
        clause_number=num,
        clause_title=title,
        clause_type=ClauseType.general,
        text=text
    )

def _score(num, s):
    return RiskScore(
        chunk_index=0,
        clause_number=num,
        clause_title='T',
        score=s,
        risk_level='LOW',
        risk_factors=[],
        constraint_violations=[],
        recommendation=''
    )


# ── S3 — score level mapping ──────────────────────────────────────────────────

def test_score_level_low():    assert _score_level(3) == 'LOW'
def test_score_level_medium(): assert _score_level(5) == 'MEDIUM'
def test_score_level_high():   assert _score_level(8) == 'HIGH'


# ── S2 — CONSTRAINT overrides (Python logic, not prompt) ─────────────────────

def test_c010_uncapped_liability():
    c = _clause('5', 'Liability', 'The liability of each party shall be unlimited for any breach.')
    min_score, violations = _check_constraints(c, [])
    assert 'C-010' in violations, "C-010 must fire on uncapped liability"
    assert min_score >= 8

def test_c011_noncompete_too_long():
    c = _clause('6', 'Non-Compete', 'Employee agrees to a non-compete for 18 months after termination.')
    min_score, violations = _check_constraints(c, [])
    assert 'C-011' in violations, "C-011 must fire when non-compete > 12 months"
    assert min_score >= 7

def test_c011_noncompete_ok():
    c = _clause('6', 'Non-Compete', 'Employee agrees to a non-compete for 12 months.')
    _, violations = _check_constraints(c, [])
    assert 'C-011' not in violations, "C-011 must NOT fire at exactly 12 months"

def test_c013_no_arbitration():
    c = _clause('12', 'Governing Law', 'This agreement is governed by laws of Delaware. Courts of Delaware have jurisdiction.')
    _, violations = _check_constraints(c, [])
    assert 'C-013' in violations, "C-013 must fire when no arbitration in dispute clause"

def test_c014_short_notice():
    c = _clause('9', 'Termination', 'Either party may terminate with 30 days written notice.')
    _, violations = _check_constraints(c, [])
    assert 'C-014' in violations, "C-014 must fire when termination notice < 90 days"


# ── Fix 3 — word-number normalisation for C-011 ──────────────────────────────

def test_normalise_numeric_text():
    assert '2' in _normalise_numeric_text('two years')
    assert '1' in _normalise_numeric_text('one year')
    assert '24' in _normalise_numeric_text('twenty-four months')

def test_c011_word_numbers_two_years():
    c = _clause('3', 'Standstill', 'The employee agrees to a standstill period of two years.')
    min_score, violations = _check_constraints(c, [])
    assert 'C-011' in violations, "C-011 must fire on 'two years' (word numbers)"
    assert min_score >= 7

def test_c011_standstill_keyword():
    c = _clause('3', 'Standstill', 'The parties agree to a standstill for 18 months from the effective date.')
    _, violations = _check_constraints(c, [])
    assert 'C-011' in violations, "C-011 must fire on 'standstill' keyword"


# ── SB1 — knowledge nodes load ────────────────────────────────────────────────

def test_loads_10_nodes():
    nodes = load_knowledge_nodes()
    assert len(nodes) == 10, f"Expected 10 knowledge nodes, got {len(nodes)}"

def test_nodes_have_required_ids():
    nodes = load_knowledge_nodes()
    ids = [n['id'] for n in nodes]
    for required in ['C-010', 'C-011', 'C-012', 'C-013', 'C-014',
                     'AP-010', 'AP-011', 'D-010', 'D-011', 'D-012']:
        assert required in ids, f"Missing knowledge node: {required}"


# ── S4 — risk delta computation ───────────────────────────────────────────────

def test_risk_delta_increased():
    r = ComparisonResult(
        match_type=MatchType.MODIFIED,
        clause_number_v1='5',
        clause_number_v2='5',
        clause_title='Liability',
        similarity_score=0.6,
        diff_text=None,
        risk_delta=None,
        score_v1=None,
        score_v2=None
    )
    updated = compute_risk_delta([_score('5', 3)], [_score('5', 8)], [r])
    assert updated[0].risk_delta == 'INCREASED'
    assert updated[0].score_v1 == 3
    assert updated[0].score_v2 == 8

def test_risk_delta_decreased():
    r = ComparisonResult(
        match_type=MatchType.MODIFIED,
        clause_number_v1='5',
        clause_number_v2='5',
        clause_title='Liability',
        similarity_score=0.6,
        diff_text=None,
        risk_delta=None,
        score_v1=None,
        score_v2=None
    )
    updated = compute_risk_delta([_score('5', 8)], [_score('5', 3)], [r])
    assert updated[0].risk_delta == 'DECREASED'


# ── Hybrid Risk Engine Path Tests ─────────────────────────────────────────────
from unittest.mock import patch, MagicMock
from src.scorer.scorer import score_clause, _risk_score_cache

def test_deterministic_bypass_without_enrichment():
    # Clear cache to guarantee isolated test state
    _risk_score_cache.clear()
    
    # Clause that triggers C-010: uncapped liability
    c = _clause('5', 'Liability', 'The liability of each party shall be unlimited for any breach.')
    nodes = load_knowledge_nodes()
    
    # Mock Anthropic client to ensure it is NEVER called in deterministic mode
    with patch('src.scorer.scorer._get_anthropic_client') as mock_client:
        result = score_clause(c, nodes, enrich=False)
        
        # Verify LLM was bypassed
        mock_client.assert_not_called()
        
        # Verify score attributes
        assert result.score >= 8
        assert result.risk_level == 'HIGH'
        assert 'C-010' in result.constraint_violations
        assert result.source == 'deterministic'
        assert len(result.risk_factors) > 0
        assert "Liability Cap" in result.risk_factors[0]

def test_hybrid_path_with_enrichment():
    _risk_score_cache.clear()
    
    # Clause that triggers C-010: uncapped liability
    c = _clause('5', 'Liability', 'The liability of each party shall be unlimited for any breach.')
    nodes = load_knowledge_nodes()
    
    # Mock converse response body
    mock_response = {
        "output": {
            "message": {
                "content": [
                    {"text": '{"score": 5, "risk_factors": ["Enriched LLM factor"], "recommendation": "Negotiate cap"}'}
                ]
            }
        }
    }
    
    with patch('src.scorer.scorer._get_anthropic_client') as mock_client:
        mock_client.return_value.converse.return_value = mock_response
        
        result = score_clause(c, nodes, enrich=True)
        
        # Verify Bedrock converse was invoked
        mock_client.return_value.converse.assert_called_once()
        
        assert result.score >= 8
        assert result.risk_level == 'HIGH'
        assert 'C-010' in result.constraint_violations
        assert result.source == 'hybrid'
        assert result.risk_factors == ["Enriched LLM factor"]
        assert result.recommendation == "Negotiate cap"


def test_llm_path_without_constraints():
    _risk_score_cache.clear()
    
    # General clause with no triggers
    c = _clause('1', 'Introduction', 'This agreement is signed by both parties on the date written below.')
    nodes = load_knowledge_nodes()
    
    mock_response = {
        "output": {
            "message": {
                "content": [
                    {"text": '{"score": 2, "risk_factors": ["Standard intro"], "recommendation": "None"}'}
                ]
            }
        }
    }
    
    with patch('src.scorer.scorer._get_anthropic_client') as mock_client:
        mock_client.return_value.converse.return_value = mock_response
        
        result = score_clause(c, nodes, enrich=False)
        
        mock_client.return_value.converse.assert_called_once()
        assert result.score == 2
        assert result.risk_level == 'LOW'
        assert len(result.constraint_violations) == 0
        assert result.source == 'llm'


def test_clause_hash_cache_hit():
    _risk_score_cache.clear()
    
    c = _clause('1', 'Introduction', 'This agreement is signed by both parties on the date written below.')
    nodes = load_knowledge_nodes()
    
    mock_response = {
        "output": {
            "message": {
                "content": [
                    {"text": '{"score": 2, "risk_factors": ["Standard intro"], "recommendation": "None"}'}
                ]
            }
        }
    }
    
    with patch('src.scorer.scorer._get_anthropic_client') as mock_client:
        mock_client.return_value.converse.return_value = mock_response
        
        # First call — populates cache
        res1 = score_clause(c, nodes, enrich=False)
        assert res1.source == 'llm'
        mock_client.return_value.converse.assert_called_once()
        
        # Second call — must hit cache
        res2 = score_clause(c, nodes, enrich=False)
        assert res2.source == 'cache'
        # Total calls should still be 1 (bypassed on second call)
        mock_client.return_value.converse.assert_called_once()
        
        assert res2.score == res1.score
        assert res2.risk_level == res1.risk_level
        assert res2.risk_factors == res1.risk_factors


# ── AWS Bedrock Integration Tests ─────────────────────────────────────────────
from src.scorer.scorer import _get_anthropic_client, _get_model_name, _call_llm

def test_get_anthropic_client_bedrock_bearer_token():
    # Patch client to force re-initialization
    with patch('src.scorer.scorer._client', None):
        with patch('boto3.client') as mock_boto:
            with patch.dict(os.environ, {
                "AWS_BEARER_TOKEN_BEDROCK": "dummy-bearer-token",
                "AWS_REGION": "us-east-1"
            }):
                _get_anthropic_client()
                mock_boto.assert_called_once_with(
                    service_name="bedrock-runtime",
                    region_name="us-east-1"
                )

def test_get_model_name_mapping():
    mock_client = MagicMock()
    # Default is the Inference Profile ARN
    assert _get_model_name(mock_client) == "arn:aws:bedrock:ap-southeast-2:593106394881:inference-profile/global.anthropic.claude-haiku-4-5-20251001-v1:0"
    
    # Verify environment override via AWS_BEDROCK_MODEL_ID
    with patch.dict(os.environ, {"AWS_BEDROCK_MODEL_ID": "custom-model"}):
        assert _get_model_name(mock_client) == "custom-model"
        
    # Verify environment override via MODEL_NAME
    with patch.dict(os.environ, {"MODEL_NAME": "us.anthropic.claude-haiku-4-5-20251001-v1:0"}):
        with patch.dict(os.environ, {"AWS_BEDROCK_MODEL_ID": ""}):
            assert _get_model_name(mock_client) == "us.anthropic.claude-haiku-4-5-20251001-v1:0"

def test_call_llm_defensive_bedrock_retry():
    # Test that _call_llm falls back gracefully to a robust default response if Bedrock is offline/unavailable
    mock_bedrock = MagicMock()
    mock_bedrock.converse.side_effect = Exception("Bedrock runtime connection failure")
    
    result = _call_llm(mock_bedrock, "dummy-model", "hello", "hashed-user")
    
    # It must return a valid BedrockResponse with fallback JSON content
    assert result.content[0].text is not None
    data = json.loads(result.content[0].text)
    assert data["score"] == 3
    assert "fallback" in data["risk_factors"][0]


