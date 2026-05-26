from pydantic import BaseModel
from typing import Optional
from enum import Enum


class ClauseType(str, Enum):
    definition     = "definition"
    obligation     = "obligation"
    limitation     = "limitation"
    termination    = "termination"
    indemnity      = "indemnity"
    ip             = "ip"
    confidentiality = "confidentiality"
    general        = "general"


class MatchType(str, Enum):
    UNCHANGED = "UNCHANGED"
    MODIFIED  = "MODIFIED"
    ADDED     = "ADDED"
    REMOVED   = "REMOVED"


class Clause(BaseModel):
    chunk_index:   int
    clause_number: str
    clause_title:  str
    clause_type:   ClauseType
    text:          str
    page_number:   Optional[int] = None   # ← NEW: from LlamaParse page index


class RiskScore(BaseModel):
    chunk_index:          int
    clause_number:        str
    clause_title:         str
    score:                int            # 1-10
    risk_level:           str            # LOW | MEDIUM | HIGH
    risk_factors:         list[str]
    constraint_violations: list[str]
    recommendation:       str
    source:               Optional[str] = "llm"   # deterministic | llm | hybrid | cache
    page_number:          Optional[int] = None     # ← NEW: carried from Clause


class ComparisonResult(BaseModel):
    match_type:       MatchType
    clause_number_v1: Optional[str]
    clause_number_v2: Optional[str]
    clause_title:     str
    similarity_score: float
    diff_text:        Optional[str]
    risk_delta:       Optional[str]    # INCREASED | DECREASED | UNCHANGED | N/A
    score_v1:         Optional[int]
    score_v2:         Optional[int]
    page_number_v1:   Optional[int] = None   # ← NEW
    page_number_v2:   Optional[int] = None   # ← NEW


class RiskSummary(BaseModel):
    high:     int
    medium:   int
    low:      int
    unscored: int = 0


class AnalyseResponse(BaseModel):
    filename:     str
    clauses:      list[Clause]
    risk_scores:  list[RiskScore]
    risk_summary: RiskSummary


class NegotiationSuggestion(BaseModel):
    clause_number: Optional[str]
    clause_title:  str
    action:        str
    reason:        str
    constraint_id: str
    risk_delta:    Optional[str]


class CompareResponse(BaseModel):
    comparison:  list[ComparisonResult]
    net_delta:   str                          # INCREASED | DECREASED | UNCHANGED (rule M3)
    suggestions: list[NegotiationSuggestion] = []


CompareResponse.model_rebuild()