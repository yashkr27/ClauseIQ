"""
Gemini prompt for the legal contract chunker.

This prompt serves BOTH operational modes of ClauseIQ:

  Mode A (Risk Assessment) — single document uploaded, chunked into clauses,
      each clause scored for risk independently.  Clause boundaries must be
      precise so the scorer sees complete, self-contained legal provisions.

  Mode B (Comparison) — two contract versions uploaded, both chunked with
      the SAME logic, then clauses matched 1-to-1.  If the chunker groups
      two clauses into one chunk, the comparator can't detect which one
      changed.  If it splits a clause mid-sentence, the diff is garbage.

Design constraints:
  • Legal documents have CLEAR structural markers: numbered headings,
    section titles, schedule/annexure markers.  The prompt teaches Gemini
    to find these — never fall back to "split every N tokens".
  • Sub-clauses (1.1, 1.2) are grouped under their parent ONLY when the
    parent has no body text of its own.
  • Preamble, recitals, signature blocks, and party definitions are
    excluded — they are not actionable clauses.
"""

# ── System-level instruction (behavioural framing) ────────────────────────────

SYSTEM_INSTRUCTION = (
    "You are a legal document analyst specializing in contract clause extraction. "
    "You have deep expertise in identifying clause boundaries in legal contracts. "
    "Return only valid JSON. Do not include any explanatory text, markdown fences, "
    "or commentary outside the JSON array."
)


# ── Main chunker prompt (user-turn content) ───────────────────────────────────

CHUNKER_PROMPT_TEMPLATE = """\
You are analysing a legal contract in markdown format.
Page boundaries are marked with <!-- PAGE N --> comments.

Your task: identify every distinct clause and return a JSON array.

─── BOUNDARY RULES (critical for downstream comparison & risk scoring) ───

1. Every NUMBERED clause is its own item (1, 2, 3… or 1.1, 1.2… or 8A, 8B…).
   Do NOT merge two numbered clauses into one item.
2. Sub-clauses (1.1, 1.2) may be grouped under their parent clause ONLY IF
   the parent heading has no body text of its own — it is just a title.
3. If a clause has no visible number, assign one as "AUTO-N" (N = sequential).
4. NEVER split a clause mid-sentence.  Each item must be a complete,
   self-contained legal provision — this is essential for accurate risk
   scoring and version-to-version comparison.
5. Schedules, Annexures, and Appendices: each schedule is ONE item unless
   it contains independently numbered sub-sections.

─── PAGE NUMBER RULE ───

page_number = the integer N from the nearest <!-- PAGE N --> marker ABOVE
the clause start.  Use 1 if no marker is found.

─── CLAUSE TYPE (exactly one of) ───

definition | obligation | limitation | termination | indemnity | ip | confidentiality | general

─── EXCLUSIONS ───

Do NOT include any of these as clauses:
  • Preamble / recitals ("WHEREAS…")
  • Party definitions ("between X and Y")
  • Signature blocks
  • Watermarks or template notices

─── OUTPUT FORMAT ───

Return ONLY the JSON array, no explanation, no markdown fences.

JSON schema (array of):
{{
  "clause_number": string,
  "clause_title":  string,
  "clause_type":   string,
  "page_number":   integer,
  "text":          string    // FULL clause body verbatim, including all sub-items
}}

─── CONTRACT ───

{markdown}
"""


def build_chunker_prompt(markdown: str) -> str:
    """Build the final prompt by injecting the contract markdown."""
    return CHUNKER_PROMPT_TEMPLATE.replace("{markdown}", markdown)
