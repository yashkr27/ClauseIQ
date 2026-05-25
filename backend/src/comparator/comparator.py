"""
Layer 3 — Clause Comparator
Rules satisfied: A2, CP1, CP2, CP3, CP4

Input:  list[Clause] v1,  list[Clause] v2
Output: list[ComparisonResult]
"""

import re
import json
import difflib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from ..models.schemas import Clause, ComparisonResult, MatchType


# ── thresholds (CP2) ──────────────────────────────────────────────────────────
UNCHANGED_THRESHOLD = 0.95
MODIFIED_THRESHOLD  = 0.40
SPLIT_MATCH_THRESHOLD = 0.28
HIGH_SEMANTIC_THRESHOLD = 0.55


# ── heading normalisation for L1 (CP1, CP4) ──────────────────────────────────
# NO hardcoded clause names. Pure structural normalisation.

def _normalise_heading(raw: str) -> str:
    """
    Strips: "clause ", "section ", "article ", dots, extra whitespace.
    Strips trailing .0 from decimal numbers.
    Lowercases.
    Result: bare number or bare word — comparable across documents.
    """
    s = raw.lower().strip()
    for prefix in ('clause ', 'section ', 'article ', 'part '):
        s = s.replace(prefix, '')
    s = s.rstrip('.')
    # "1.0" → "1"
    if re.match(r'^\d+\.0$', s):
        s = s.split('.')[0]
    return s.strip()


def _base_clause_number(raw: str | None) -> str:
    """Return the top-level number used for split detection: 8A -> 8, 8.1 -> 8."""
    if not raw:
        return ''
    s = _normalise_heading(raw)
    m = re.match(r'^(\d+)', s)
    return m.group(1) if m else s


def _text_similarity(text_v1: str, text_v2: str) -> float:
    """Small robust similarity helper shared by L1 and split matching."""
    if text_v1.strip() == text_v2.strip():
        return 1.0
    if not text_v1.strip() or not text_v2.strip():
        return 0.0
    try:
        matrix = TfidfVectorizer(stop_words='english').fit_transform([text_v1, text_v2])
        return float(cosine_similarity(matrix)[0][1])
    except Exception:
        return difflib.SequenceMatcher(None, text_v1, text_v2).ratio()


# ── word-level diff (CP3) ─────────────────────────────────────────────────────

def _word_diff(text_v1: str, text_v2: str) -> list[dict]:
    """
    Returns word-level diff as list of {type, text}.
    Types: "equal" | "add" | "remove"
    Rule CP3: never return "changed" without this diff.
    """
    words_v1 = text_v1.split()
    words_v2 = text_v2.split()
    matcher  = difflib.SequenceMatcher(None, words_v1, words_v2)
    result   = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == 'equal':
            result.append({'type': 'equal',  'text': ' '.join(words_v1[i1:i2])})
        elif op == 'replace':
            result.append({'type': 'remove', 'text': ' '.join(words_v1[i1:i2])})
            result.append({'type': 'add',    'text': ' '.join(words_v2[j1:j2])})
        elif op == 'delete':
            result.append({'type': 'remove', 'text': ' '.join(words_v1[i1:i2])})
        elif op == 'insert':
            result.append({'type': 'add',    'text': ' '.join(words_v2[j1:j2])})
    return result


# ── L1: heading match (CP1) ───────────────────────────────────────────────────

def _l1_match(clauses_v1: list[Clause], clauses_v2: list[Clause]
              ) -> tuple[list[tuple], set, set]:
    """
    Returns: (matched_pairs, unmatched_v1_indices, unmatched_v2_indices)
    matched_pairs: [(clause_v1, clause_v2), ...]
    """
    norm_v2 = {_normalise_heading(c.clause_number): i for i, c in enumerate(clauses_v2)
               if c.clause_number}
    matched_pairs    = []
    matched_v1_idx   = set()
    matched_v2_idx   = set()

    for i, c1 in enumerate(clauses_v1):
        key = _normalise_heading(c1.clause_number)
        if key and key in norm_v2:
            j = norm_v2[key]
            if j not in matched_v2_idx:
                matched_pairs.append((c1, clauses_v2[j]))
                matched_v1_idx.add(i)
                matched_v2_idx.add(j)

    unmatched_v1 = set(range(len(clauses_v1))) - matched_v1_idx
    unmatched_v2 = set(range(len(clauses_v2))) - matched_v2_idx
    return matched_pairs, unmatched_v1, unmatched_v2


# ── L2: TF-IDF semantic match (CP1) ──────────────────────────────────────────

def _l2_match(clauses_v1: list[Clause], clauses_v2: list[Clause],
              unmatched_v1: set, unmatched_v2: set
              ) -> list[tuple[Clause, Clause, float]]:
    """
    TF-IDF cosine similarity on clause text bodies.
    Returns list of (clause_v1, clause_v2, similarity_score) for pairs above MODIFIED_THRESHOLD.
    Rule CP1: this runs on ALL unmatched clauses, every time.
    Rule CP4: no hardcoded titles — purely content-based.
    """
    if not unmatched_v1 or not unmatched_v2:
        return []

    um_v1 = [clauses_v1[i] for i in sorted(unmatched_v1)]
    um_v2 = [clauses_v2[j] for j in sorted(unmatched_v2)]

    # Robust TF-IDF implementation with SequenceMatcher fallback for safety
    try:
        all_texts = [c.text for c in um_v1] + [c.text for c in um_v2]
        vectorizer = TfidfVectorizer(stop_words='english', ngram_range=(1, 2))
        tfidf = vectorizer.fit_transform(all_texts)

        v1_vecs = tfidf[:len(um_v1)]
        v2_vecs = tfidf[len(um_v1):]
        sim_matrix = cosine_similarity(v1_vecs, v2_vecs)
    except Exception:
        # Fallback to character-level SequenceMatcher matrix if vectorization fails
        sim_matrix = np.zeros((len(um_v1), len(um_v2)))
        for i, c1 in enumerate(um_v1):
            for j, c2 in enumerate(um_v2):
                sim_matrix[i, j] = difflib.SequenceMatcher(None, c1.text, c2.text).ratio()

    # Greedy assignment — highest similarity first
    pairs = []
    used_v2 = set()
    indices = np.argsort(-sim_matrix, axis=None)
    for flat_idx in indices:
        i, j = divmod(int(flat_idx), len(um_v2))
        if j in used_v2:
            continue
        score = float(sim_matrix[i, j])
        if score < MODIFIED_THRESHOLD:
            break
        pairs.append((um_v1[i], um_v2[j], score))
        used_v2.add(j)

    return pairs


# ── public interface ──────────────────────────────────────────────────────────

def compare(clauses_v1: list[Clause], clauses_v2: list[Clause]) -> list[ComparisonResult]:
    """
    Layer 3 public interface.
    Rules: CP1 (L1+L2 always), CP2 (thresholds), CP3 (word diff), CP4 (no hardcoding).
    """
    results = []

    # L1: heading match
    matched_l1, unmatched_v1, unmatched_v2 = _l1_match(clauses_v1, clauses_v2)

    for c1, c2 in matched_l1:
        sim = _text_similarity(c1.text, c2.text)

        if sim > UNCHANGED_THRESHOLD:
            match_type = MatchType.UNCHANGED
            diff       = None
        else:
            match_type = MatchType.MODIFIED
            diff       = _word_diff(c1.text, c2.text)

        results.append(ComparisonResult(
            match_type=match_type,
            clause_number_v1=c1.clause_number,
            clause_number_v2=c2.clause_number,
            clause_title=c1.clause_title or c2.clause_title,
            similarity_score=round(sim, 3),
            diff_text=json.dumps(diff) if diff else None,
            risk_delta=None, score_v1=None, score_v2=None,
        ))

    # L2: semantic match on remaining unmatched (CP1 — always run)
    semantic_pairs = _l2_match(clauses_v1, clauses_v2, unmatched_v1, unmatched_v2)
    semantic_v1_matched = set()
    semantic_v2_matched = set()

    for c1, c2, sim in semantic_pairs:
        diff = _word_diff(c1.text, c2.text)
        results.append(ComparisonResult(
            match_type=MatchType.MODIFIED,
            clause_number_v1=c1.clause_number,
            clause_number_v2=c2.clause_number,
            clause_title=c1.clause_title or c2.clause_title,
            similarity_score=round(sim, 3),
            diff_text=json.dumps(diff),
            risk_delta=None, score_v1=None, score_v2=None,
        ))
        semantic_v1_matched.add(c1.clause_number)
        semantic_v2_matched.add(c2.clause_number)

    # Split detection: if a v2 clause like "8A" is a semantic continuation of
    # an already matched v1 clause "8", classify it as MODIFIED instead of ADDED.
    matched_sources = [c1 for c1, _ in matched_l1] + [c1 for c1, _, _ in semantic_pairs]
    for j in sorted(unmatched_v2):
        c2 = clauses_v2[j]
        if c2.clause_number in semantic_v2_matched:
            continue

        best = None
        for c1 in matched_sources:
            score = _text_similarity(c1.text, c2.text)
            same_base = (
                _base_clause_number(c1.clause_number)
                and _base_clause_number(c1.clause_number) == _base_clause_number(c2.clause_number)
            )
            if not same_base and score < HIGH_SEMANTIC_THRESHOLD:
                continue
            if score < SPLIT_MATCH_THRESHOLD:
                continue
            if best is None or score > best[2]:
                best = (c1, c2, score)

        if best is None:
            continue

        c1, c2, sim = best
        results.append(ComparisonResult(
            match_type=MatchType.MODIFIED,
            clause_number_v1=c1.clause_number,
            clause_number_v2=c2.clause_number,
            clause_title=c2.clause_title or c1.clause_title,
            similarity_score=round(sim, 3),
            diff_text=json.dumps(_word_diff(c1.text, c2.text)),
            risk_delta=None, score_v1=None, score_v2=None,
        ))
        semantic_v2_matched.add(c2.clause_number)

    # Remaining unmatched v1 = REMOVED
    for i in unmatched_v1:
        c1 = clauses_v1[i]
        if c1.clause_number not in semantic_v1_matched:
            results.append(ComparisonResult(
                match_type=MatchType.REMOVED,
                clause_number_v1=c1.clause_number,
                clause_number_v2=None,
                clause_title=c1.clause_title,
                similarity_score=0.0,
                diff_text=None, risk_delta=None, score_v1=None, score_v2=None,
            ))

    # Remaining unmatched v2 = ADDED
    for j in unmatched_v2:
        c2 = clauses_v2[j]
        if c2.clause_number not in semantic_v2_matched:
            results.append(ComparisonResult(
                match_type=MatchType.ADDED,
                clause_number_v1=None,
                clause_number_v2=c2.clause_number,
                clause_title=c2.clause_title,
                similarity_score=0.0,
                diff_text=None, risk_delta=None, score_v1=None, score_v2=None,
            ))

    return results
