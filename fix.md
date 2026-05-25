# ClauseIQ — Fix List (Priority Order)
> Generated from full BE + FE code review. Work top-to-bottom — each fix is independent unless noted.

---

## 🔴 CRITICAL — Will break the demo

### FIX-01 · Diff renderer reads wrong format (FE)
**File:** `frontend/app.js` → `renderDiffText()`

**Problem:** Backend emits `diff_text` as `str(list)` with single-quoted Python dicts:
```
[{'type': 'add', 'text': 'PURPOSE.'}, {'type': 'equal', 'text': 'Each'}, ...]
```
`renderDiffText()` splits on newlines and looks for `"+ "` / `"- "` prefixes — finds nothing — renders everything as flat grey text. The evaluator clicks a MODIFIED clause and sees no red/green highlighting.

**Fix option A — patch the backend (preferred, cleaner):**

In `backend/src/comparator/comparator.py`, change every `diff_text=str(diff)` to `diff_text=json.dumps(diff)`.
Add `import json` at the top if not present.

```python
# before
diff_text=str(diff) if diff else None,

# after
diff_text=json.dumps(diff) if diff else None,
```

**Fix option B — patch the frontend only:**

Replace `renderDiffText()` in `frontend/app.js`:

```js
function renderDiffText(raw) {
  if (!raw) return '';
  let ops;
  try {
    ops = JSON.parse(raw.replace(/'/g, '"'));
  } catch {
    return escapeHtml(raw);
  }
  return ops.map(op => {
    const t = escapeHtml(op.text || '');
    if (op.type === 'add')    return `<span class="diff-added">${t} </span>`;
    if (op.type === 'remove') return `<span class="diff-removed">${t} </span>`;
    return t + ' ';
  }).join('');
}
```

---

### FIX-02 · Bedrock failure silently scores everything LOW (BE)
**File:** `backend/src/scorer/scorer.py` → `_call_llm()`

**Problem:** The fallback on Bedrock error returns `{"score": 3, ...}` — so if AWS is unreachable during the demo, every clause shows LOW risk (green). Looks like confident wrong output, not a service error.

**Fix:** Return a sentinel that the caller can detect, then surface it as UNSCORED:

```python
# In _call_llm(), change the fallback_json to:
fallback_json = json.dumps({
    "score": None,
    "risk_factors": [f"Scoring unavailable (Bedrock error: {error_msg})"],
    "recommendation": "Manual review required — risk scoring service was unavailable."
})

# In score_clause(), after parsing LLM response, guard the score:
llm_score_raw = data.get('score')
if llm_score_raw is None:
    final_score = 0          # sentinel: 0 = unscored
    risk_level  = 'UNSCORED'
else:
    final_score = max(1, min(10, int(llm_score_raw)))
    risk_level  = _score_level(final_score)
```

Also add `UNSCORED` to `_score_level()`:
```python
def _score_level(score: int) -> str:
    if score == 0:   return 'UNSCORED'
    if score <= 3:   return 'LOW'
    if score <= 6:   return 'MEDIUM'
    return 'HIGH'
```

In the FE (`frontend/styles.css`), add a grey pill for unscored clauses:
```css
.clause-score-pill.unscored {
  background: var(--bg-surface);
  color: var(--text-muted);
}
.clause-card.risk-unscored { border-left-color: var(--text-muted); }
```

---

### FIX-03 · C-013 (arbitration) only checks clause title keywords (BE)
**File:** `backend/src/scorer/scorer.py` → `_check_constraints()`

**Problem:** The C-013 check requires `'dispute'`, `'governing'`, `'jurisdiction'`, `'resolution'`, or `'law'` in the clause *title*. A lease clause titled `"Section 18"` with arbitration text removed will never trigger this constraint — the surprise test will miss it.

**Fix:** Also scan the first 300 chars of the body regardless of title:

```python
# C-013: no arbitration in dispute/governing law clause
is_dispute_title = any(w in title for w in ['dispute', 'governing', 'jurisdiction', 'resolution', 'law'])
is_dispute_body  = any(w in text[:300] for w in ['governing law', 'jurisdiction', 'venue', 'courts of', 'applicable law'])

if is_dispute_title or is_dispute_body:
    if 'arbitration' not in text and 'arbitrate' not in text:
        violations.append('C-013')
        min_score = max(min_score, 6)
```

---

## 🟡 HIGH — Will hurt demo quality or surprise-test score

### FIX-04 · No-heading fallback returns one giant chunk (BE)
**File:** `backend/src/chunker/chunker.py` → `chunk()`

**Problem:** If `_find_boundaries()` returns zero results (letter-style agreement, bold-only headings), the entire document becomes a single chunk. Comparison and scoring both become useless.

**Fix:** Add a second-pass heuristic before the single-chunk fallback — detect bold/italic paragraph styles from python-docx, or fall back to paragraph-boundary splitting with a minimum 200-char threshold:

```python
if not boundaries:
    # Second pass: try paragraph-boundary chunking for unstructured docs
    paragraphs = [p.strip() for p in text.split('\n\n') if len(p.strip()) >= 200]
    if len(paragraphs) >= 2:
        clauses = []
        for idx, para in enumerate(paragraphs):
            first_line = para.split('\n')[0][:60]
            clauses.append(Clause(
                chunk_index=idx,
                clause_number=str(idx + 1),
                clause_title=_clean_title(str(idx + 1), first_line),
                clause_type=_detect_type(first_line, para),
                text=para,
            ))
        return clauses
    # Last resort: return entire text as one chunk
    return [Clause(
        chunk_index=0,
        clause_number='',
        clause_title='Full Document',
        clause_type=ClauseType.general,
        text=text.strip(),
    )]
```

---

### FIX-05 · No file reset / re-upload path (FE)
**File:** `frontend/index.html` + `frontend/app.js`

**Problem:** Once a file is set, there is no way to clear it short of a full page refresh. Mid-demo recovery from a wrong file upload is impossible.

**Fix in HTML** — add a reset button inside each upload zone (hidden by default):
```html
<!-- inside each .upload-zone, after .upload-filename -->
<button class="upload-reset" id="analyse-reset" hidden>✕ Clear</button>
```

**Fix in app.js** — extend `initUploadZone` and expose a reset path:
```js
function initUploadZone(zoneId, inputId, filenameId, resetId, onFile, onClear) {
  // ... existing setup ...
  const resetBtn = document.getElementById(resetId);

  function setFile(file) {
    // ... existing validation ...
    resetBtn.hidden = false;
  }

  resetBtn.addEventListener('click', e => {
    e.stopPropagation();
    zone.classList.remove('has-file');
    filenameEl.textContent = '';
    input.value = '';
    resetBtn.hidden = true;
    onClear();
  });
}
```

Add minimal CSS:
```css
.upload-reset {
  margin-top: var(--space-sm);
  font-size: 12px;
  color: var(--text-muted);
  background: transparent;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-full);
  padding: 3px 10px;
  cursor: pointer;
  position: relative;
}
.upload-reset:hover { color: var(--risk-high); border-color: rgba(239,68,68,0.3); }
```

---

### FIX-06 · No request timeout or abort (FE)
**File:** `frontend/app.js` → `handleAnalyse()` and `handleCompare()`

**Problem:** Bedrock scoring of a 15-clause document can take 30–90 seconds. The spinner runs forever with no feedback if the call hangs or the server is unreachable.

**Fix:** Add an `AbortController` + a "taking longer than usual" message after 15 seconds:

```js
async function handleAnalyse() {
  const controller = new AbortController();
  const slowTimer = setTimeout(() => {
    loadingEl.innerHTML += `<p style="text-align:center;font-size:13px;color:var(--text-muted);margin-top:8px">
      Still working — AI scoring large documents can take up to 60s…</p>`;
  }, 15000);
  const hardTimeout = setTimeout(() => controller.abort(), 90000);

  try {
    const res = await fetch(`${API_BASE}/api/analyse`, {
      method: 'POST',
      body: form,
      signal: controller.signal,
    });
    // ...rest of handler
  } catch (e) {
    const msg = e.name === 'AbortError'
      ? 'Request timed out after 90 seconds. Try a smaller document.'
      : e.message;
    errorEl.innerHTML = `<div class="error-box">⚠️ ${escapeHtml(msg)}</div>`;
  } finally {
    clearTimeout(slowTimer);
    clearTimeout(hardTimeout);
    // ...re-enable button
  }
}
```
Apply same pattern to `handleCompare()`.

---

## 🟢 POLISH — Nice to have before demo

### FIX-07 · Greedy comparator can misalign heavily restructured docs (BE)
**File:** `backend/src/comparator/comparator.py` → `_l2_match()`

**Problem:** The greedy highest-similarity-first assignment can produce suboptimal pairings when many clauses are restructured simultaneously (e.g., SPA scenario where clause 8 splits into 8 and 8A).

**Fix:** Replace the greedy loop with scipy's linear sum assignment (Hungarian algorithm) — already available in the scipy dependency tree via scikit-learn:

```python
from scipy.optimize import linear_sum_assignment

# Replace the greedy loop with:
row_ind, col_ind = linear_sum_assignment(-sim_matrix)  # negate for maximisation
for i, j in zip(row_ind, col_ind):
    score = float(sim_matrix[i, j])
    if score < MODIFIED_THRESHOLD:
        continue
    pairs.append((um_v1[i], um_v2[j], score))
```

---

### FIX-08 · Emoji icons not hidden from screen readers (FE)
**File:** `frontend/index.html`

**Problem:** Inline emoji in tab buttons (`⚡`, `🔀`) and upload zones (`📄`) are read aloud by screen readers as "lightning bolt Analyse" and "shuffle compare".

**Fix:** Wrap all decorative emoji:
```html
<!-- Tab buttons -->
<button class="tab-btn active" ...><span aria-hidden="true">⚡</span> Analyse</button>
<button class="tab-btn" ...><span aria-hidden="true">🔀</span> Compare</button>

<!-- Upload zones -->
<div class="upload-icon" aria-hidden="true">📄</div>
```

---

### FIX-09 · No file size enforcement on upload (FE)
**File:** `frontend/app.js` → `setFile()` inside `initUploadZone()`

**Problem:** The HTML hint says "Max 20 MB" but nothing enforces it. A 50 MB PDF will silently hang.

**Fix:** Add a size check alongside the extension check:
```js
function setFile(file) {
  const ext = file.name.split('.').pop().toLowerCase();
  if (!['pdf', 'docx', 'doc'].includes(ext)) {
    alert('Please upload a PDF or DOCX file.');
    return;
  }
  if (file.size > 20 * 1024 * 1024) {
    alert('File exceeds 20 MB limit. Please upload a smaller document.');
    return;
  }
  // ...rest of setFile
}
```

---

### FIX-10 · No file size / mime guard on the API route (BE)
**File:** `backend/src/api/routes/analyse.py` and `compare.py`

**Problem:** Extension check only — a malformed PDF or huge file returns a raw 500 rather than a clear 400.

**Fix:** Add a size check after reading the file into the temp path:
```python
MAX_BYTES = 20 * 1024 * 1024  # 20 MB

# After writing tmp file, before extract():
file_size = os.path.getsize(tmp_path)
if file_size > MAX_BYTES:
    raise HTTPException(status_code=400, detail="File exceeds 20 MB limit.")
if file_size == 0:
    raise HTTPException(status_code=400, detail="Uploaded file is empty.")
```

---

## Summary table

| # | Area | Severity | Effort |
|---|------|----------|--------|
| FIX-01 | Diff renderer format mismatch | 🔴 Critical | ~10 min |
| FIX-02 | Bedrock fallback hides errors | 🔴 Critical | ~15 min |
| FIX-03 | C-013 misses body-text arbitration | 🔴 Critical | ~5 min |
| FIX-04 | No-heading chunker fallback | 🟡 High | ~20 min |
| FIX-05 | No file reset button | 🟡 High | ~15 min |
| FIX-06 | No request timeout/abort | 🟡 High | ~15 min |
| FIX-07 | Greedy comparator alignment | 🟢 Polish | ~15 min |
| FIX-08 | Emoji not aria-hidden | 🟢 Polish | ~5 min |
| FIX-09 | No client-side file size check | 🟢 Polish | ~5 min |
| FIX-10 | No server-side file size guard | 🟢 Polish | ~5 min |

**Total estimated time: ~110 minutes.** FIX-01 through FIX-03 take under 30 minutes combined and remove every demo-breaking risk.
