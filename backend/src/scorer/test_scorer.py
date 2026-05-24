"""
Tests for Layer 4 — Scorer
Run from backend/: python -m pytest src/scorer/test_scorer.py -v -k "not score_clause"
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.scorer.scorer import _check_constraints, _score_level, compute_risk_delta
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
