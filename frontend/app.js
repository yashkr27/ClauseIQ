/* ═══════════════════════════════════════════════════════════════════════════
   ClauseIQ — Frontend Application Logic
   ═══════════════════════════════════════════════════════════════════════════ */

const API_BASE = 'http://127.0.0.1:8000';
const MAX_FILE_BYTES = 20 * 1024 * 1024;
const REQUEST_TIMEOUT_MS = 90000;
const SLOW_MESSAGE_MS = 15000;

// ── State ────────────────────────────────────────────────────────────────

let analyseFile = null;
let v1File = null;
let v2File = null;

// ── DOM Ready ────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  initUploadZone('upload-analyse', 'analyse-file-input', 'analyse-filename', 'analyse-reset', f => {
    analyseFile = f;
    updateSubmitState();
  }, () => {
    analyseFile = null;
    updateSubmitState();
  });
  initUploadZone('upload-v1', 'v1-file-input', 'v1-filename', 'v1-reset', f => {
    v1File = f;
    updateSubmitState();
  }, () => {
    v1File = null;
    updateSubmitState();
  });
  initUploadZone('upload-v2', 'v2-file-input', 'v2-filename', 'v2-reset', f => {
    v2File = f;
    updateSubmitState();
  }, () => {
    v2File = null;
    updateSubmitState();
  });

  document.getElementById('analyse-submit').addEventListener('click', handleAnalyse);
  document.getElementById('compare-submit').addEventListener('click', handleCompare);
});


// ── Tab Switching ────────────────────────────────────────────────────────

function initTabs() {
  const tabs = document.querySelectorAll('.tab-btn');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => { t.classList.remove('active'); t.setAttribute('aria-selected', 'false'); });
      tab.classList.add('active');
      tab.setAttribute('aria-selected', 'true');

      document.querySelectorAll('.mode-panel').forEach(p => p.classList.remove('active'));
      document.getElementById(`panel-${tab.dataset.tab}`).classList.add('active');
    });
  });
}


// ── Upload Zone ──────────────────────────────────────────────────────────

function initUploadZone(zoneId, inputId, filenameId, resetId, onFile, onClear) {
  const zone = document.getElementById(zoneId);
  const input = document.getElementById(inputId);
  const filenameEl = document.getElementById(filenameId);
  const resetBtn = document.getElementById(resetId);

  zone.addEventListener('click', () => input.click());
  zone.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') input.click(); });

  // Drag events
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file) setFile(file);
  });

  input.addEventListener('change', () => {
    if (input.files[0]) setFile(input.files[0]);
  });

  function setFile(file) {
    const ext = file.name.split('.').pop().toLowerCase();
    if (!['pdf', 'docx', 'doc'].includes(ext)) {
      alert('Please upload a PDF or DOCX file.');
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      alert('File exceeds 20 MB limit. Please upload a smaller document.');
      return;
    }
    zone.classList.add('has-file');
    filenameEl.textContent = `✓ ${file.name}`;
    resetBtn.hidden = false;
    onFile(file);
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

function updateSubmitState() {
  document.getElementById('analyse-submit').disabled = !analyseFile;
  document.getElementById('compare-submit').disabled = !(v1File && v2File);
}

function startRequestTimers(loadingEl, controller) {
  const slowTimer = setTimeout(() => {
    loadingEl.innerHTML += `
      <p class="loading-note">
        Still working. AI scoring large documents can take up to 60 seconds.
      </p>
    `;
  }, SLOW_MESSAGE_MS);

  const hardTimeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  return () => {
    clearTimeout(slowTimer);
    clearTimeout(hardTimeout);
  };
}


// ── Mode A: Analyse ──────────────────────────────────────────────────────

async function handleAnalyse() {
  const btn = document.getElementById('analyse-submit');
  const errorEl = document.getElementById('analyse-error');
  const loadingEl = document.getElementById('analyse-loading');
  const resultsEl = document.getElementById('analyse-results');

  errorEl.innerHTML = '';
  resultsEl.innerHTML = '';
  loadingEl.innerHTML = renderSkeletons(6);
  btn.classList.add('loading');
  btn.textContent = 'Analysing…';
  btn.disabled = true;
  const controller = new AbortController();
  const clearTimers = startRequestTimers(loadingEl, controller);

  try {
    const form = new FormData();
    form.append('file', analyseFile);
    const res = await fetch(`${API_BASE}/api/analyse`, {
      method: 'POST',
      body: form,
      signal: controller.signal,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `Server error ${res.status}`);
    }
    const data = await res.json();
    loadingEl.innerHTML = '';
    resultsEl.innerHTML = renderAnalyseResults(data);
    initClauseCards(resultsEl);
  } catch (e) {
    loadingEl.innerHTML = '';
    if (e.name === 'AbortError') {
      e.message = 'Request timed out after 90 seconds. Try a smaller document.';
    }
    errorEl.innerHTML = `<div class="error-box">⚠️ ${escapeHtml(e.message)}</div>`;
  } finally {
    clearTimers();
    btn.classList.remove('loading');
    btn.textContent = 'Analyse Contract';
    btn.disabled = false;
  }
}

function renderAnalyseResults(data) {
  const { filename, clauses, risk_scores, risk_summary } = data;
  const total = risk_summary.high + risk_summary.medium + risk_summary.low + (risk_summary.unscored || 0);

  // Merge clause text/type into risk scores by chunk_index
  const clauseMap = {};
  clauses.forEach(c => { clauseMap[c.chunk_index] = c; });
  const merged = risk_scores.map(s => {
    const clause = clauseMap[s.chunk_index] || {};
    return { ...s, text: clause.text || '', clause_type: clause.clause_type || s.clause_type || '' };
  });

  return `
    ${renderRiskSummary(risk_summary, total, filename)}
    <div class="clause-list">
      ${merged.map((s, i) => renderClauseCard(s, i)).join('')}
    </div>
  `;
}

function renderRiskSummary(summary, total, filename) {
  const circumference = 2 * Math.PI * 42;
  const highLen = total > 0 ? (summary.high / total) * circumference : 0;
  const medLen = total > 0 ? (summary.medium / total) * circumference : 0;
  const lowLen = total > 0 ? (summary.low / total) * circumference : 0;
  const unscoredLen = total > 0 ? ((summary.unscored || 0) / total) * circumference : 0;

  const highOff = 0;
  const medOff = highLen;
  const lowOff = highLen + medLen;
  const unscoredOff = highLen + medLen + lowLen;

  return `
    <div class="risk-summary">
      <div class="risk-donut">
        <svg viewBox="0 0 100 100">
          <circle cx="50" cy="50" r="42" stroke="var(--bg-surface)" stroke-dasharray="${circumference}" stroke-dashoffset="0"></circle>
          ${summary.high > 0 ? `<circle cx="50" cy="50" r="42" stroke="var(--risk-high)" stroke-dasharray="${highLen} ${circumference - highLen}" stroke-dashoffset="-${highOff}"></circle>` : ''}
          ${summary.medium > 0 ? `<circle cx="50" cy="50" r="42" stroke="var(--risk-medium)" stroke-dasharray="${medLen} ${circumference - medLen}" stroke-dashoffset="-${medOff}"></circle>` : ''}
          ${summary.low > 0 ? `<circle cx="50" cy="50" r="42" stroke="var(--risk-low)" stroke-dasharray="${lowLen} ${circumference - lowLen}" stroke-dashoffset="-${lowOff}"></circle>` : ''}
          ${(summary.unscored || 0) > 0 ? `<circle cx="50" cy="50" r="42" stroke="var(--text-muted)" stroke-dasharray="${unscoredLen} ${circumference - unscoredLen}" stroke-dashoffset="-${unscoredOff}"></circle>` : ''}
        </svg>
        <div class="risk-donut-label">
          <div class="risk-donut-count">${total}</div>
          <div class="risk-donut-text">Clauses</div>
        </div>
      </div>
      <div class="risk-badges">
        <div class="risk-badge high">
          <span class="risk-badge-dot"></span>
          <span class="risk-badge-count">${summary.high}</span> High Risk
        </div>
        <div class="risk-badge medium">
          <span class="risk-badge-dot"></span>
          <span class="risk-badge-count">${summary.medium}</span> Medium
        </div>
        <div class="risk-badge low">
          <span class="risk-badge-dot"></span>
          <span class="risk-badge-count">${summary.low}</span> Low Risk
        </div>
        ${(summary.unscored || 0) > 0 ? `
        <div class="risk-badge unscored">
          <span class="risk-badge-dot"></span>
          <span class="risk-badge-count">${summary.unscored}</span> Unscored
        </div>` : ''}
      </div>
      <div class="filename-tag">📎 ${escapeHtml(filename)}</div>
    </div>
  `;
}

function renderClauseCard(score, index) {
  const level = (score.risk_level || 'UNSCORED').toLowerCase();
  const scoreLabel = level === 'unscored' ? 'Unscored' : `${score.score}/10 ${score.risk_level}`;
  const scoreIcon = level === 'high' ? '🔴' : level === 'medium' ? '🟡' : '🟢';
  const factors = (score.risk_factors || []).map(f => `• ${escapeHtml(f)}`).join('\n');
  const constraints = (score.constraint_violations || [])
    .map(c => `<span class="constraint-tag">${escapeHtml(c)}</span>`)
    .join(' ');

  return `
    <div class="clause-card risk-${level}" style="animation-delay: ${index * 40}ms" data-index="${index}">
      <div class="clause-header">
        <span class="clause-number">${escapeHtml(score.clause_number || '—')}</span>
        <span class="clause-title">${escapeHtml(score.clause_title)}</span>
        <span class="clause-type-tag">${escapeHtml(score.clause_type || '')}</span>
        <span class="clause-score-pill ${level} score-reveal">
          <span class="score-icon">${level === 'unscored' ? '' : scoreIcon}</span>
          ${scoreLabel}
        </span>
        <span class="clause-expand-icon">▼</span>
      </div>
      <div class="clause-body">
        <div class="clause-body-inner">
          <div class="clause-text">${escapeHtml(score.text || '')}</div>
          <div class="clause-meta">
            ${factors ? `<div class="clause-meta-row"><span class="clause-meta-label">Risk Factors</span><span class="clause-meta-value">${escapeHtml(factors)}</span></div>` : ''}
            ${score.recommendation ? `<div class="clause-meta-row"><span class="clause-meta-label">Recommendation</span><span class="clause-meta-value">${escapeHtml(score.recommendation)}</span></div>` : ''}
            ${constraints ? `<div class="clause-meta-row"><span class="clause-meta-label">Constraints</span><span class="clause-meta-value">${constraints}</span></div>` : ''}
            <div class="clause-meta-row"><span class="clause-meta-label">Source</span><span class="clause-meta-value"><span class="source-tag">${escapeHtml(score.source || 'llm')}</span></span></div>
          </div>
        </div>
      </div>
    </div>
  `;
}

function initClauseCards(container) {
  container.querySelectorAll('.clause-card').forEach(card => {
    card.querySelector('.clause-header').addEventListener('click', () => {
      card.classList.toggle('expanded');
    });
  });
}


// ── Mode B: Compare ──────────────────────────────────────────────────────

async function handleCompare() {
  const btn = document.getElementById('compare-submit');
  const errorEl = document.getElementById('compare-error');
  const loadingEl = document.getElementById('compare-loading');
  const resultsEl = document.getElementById('compare-results');

  errorEl.innerHTML = '';
  resultsEl.innerHTML = '';
  loadingEl.innerHTML = renderSkeletons(8);
  btn.classList.add('loading');
  btn.textContent = 'Comparing…';
  btn.disabled = true;
  const controller = new AbortController();
  const clearTimers = startRequestTimers(loadingEl, controller);

  try {
    const form = new FormData();
    form.append('file_v1', v1File);
    form.append('file_v2', v2File);
    const res = await fetch(`${API_BASE}/api/compare`, {
      method: 'POST',
      body: form,
      signal: controller.signal,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `Server error ${res.status}`);
    }
    const data = await res.json();
    loadingEl.innerHTML = '';
    resultsEl.innerHTML = renderCompareResults(data);
    initComparisonRows(resultsEl);
  } catch (e) {
    loadingEl.innerHTML = '';
    if (e.name === 'AbortError') {
      e.message = 'Request timed out after 90 seconds. Try a smaller document pair.';
    }
    errorEl.innerHTML = `<div class="error-box">⚠️ ${escapeHtml(e.message)}</div>`;
  } finally {
    clearTimers();
    btn.classList.remove('loading');
    btn.textContent = 'Compare Versions';
    btn.disabled = false;
  }
}

function renderCompareResults(data) {
  const { comparison, net_delta, suggestions = [] } = data;
  const deltaClass = net_delta.toLowerCase();
  const deltaIcon = net_delta === 'INCREASED' ? '📈' : net_delta === 'DECREASED' ? '📉' : '➖';

  const stats = {
    unchanged: comparison.filter(c => c.match_type === 'UNCHANGED').length,
    modified: comparison.filter(c => c.match_type === 'MODIFIED').length,
    added: comparison.filter(c => c.match_type === 'ADDED').length,
    removed: comparison.filter(c => c.match_type === 'REMOVED').length,
  };

  const negotiationHtml = suggestions.length ? renderNegotiationPanel(suggestions) : '';

  return `
    <div class="compare-header">
      <div class="net-delta-badge ${deltaClass}">
        ${deltaIcon} Net Risk: ${net_delta}
      </div>
      <div class="risk-badges">
        <div class="risk-badge low"><span class="risk-badge-dot"></span><span class="risk-badge-count">${stats.unchanged}</span> Unchanged</div>
        <div class="risk-badge medium"><span class="risk-badge-dot"></span><span class="risk-badge-count">${stats.modified}</span> Modified</div>
        <div class="risk-badge high" style="background:var(--risk-low-bg);color:var(--risk-low);border-color:rgba(34,197,94,0.2)"><span class="risk-badge-dot" style="background:var(--risk-low)"></span><span class="risk-badge-count">${stats.added}</span> Added</div>
        <div class="risk-badge high"><span class="risk-badge-dot"></span><span class="risk-badge-count">${stats.removed}</span> Removed</div>
      </div>
    </div>
    ${negotiationHtml}
    <div class="comparison-list">
      ${comparison.map((c, i) => renderComparisonRow(c, i)).join('')}
    </div>
  `;
}

function renderNegotiationPanel(suggestions) {
  // Group by constraint_id so we don't repeat the same action for multiple clauses
  const byConstraint = {};
  for (const s of suggestions) {
    if (!byConstraint[s.constraint_id]) byConstraint[s.constraint_id] = [];
    byConstraint[s.constraint_id].push(s);
  }

  const rows = Object.entries(byConstraint).map(([cid, items]) => {
    const first = items[0];
    const clauseRefs = items
      .map(i => i.clause_number ? `<span class="neg-clause-ref">${escapeHtml(i.clause_number)}</span>` : '')
      .filter(Boolean).join(' ');
    const deltaIcon = first.risk_delta === 'INCREASED' ? '▲' :
      first.risk_delta === 'DECREASED' ? '▼' : '';
    return `
      <div class="neg-row">
        <div class="neg-header">
          <span class="neg-constraint-badge">${escapeHtml(cid)}</span>
          ${clauseRefs}
          ${deltaIcon ? `<span class="neg-delta ${first.risk_delta.toLowerCase()}">${deltaIcon}</span>` : ''}
        </div>
        <p class="neg-reason">${escapeHtml(first.reason)}</p>
        <p class="neg-action">${escapeHtml(first.action)}</p>
      </div>`;
  }).join('');

  return `
    <div class="negotiation-panel">
      <div class="negotiation-panel-header">
        <span class="neg-icon">⚖️</span>
        <strong>Negotiation Actions</strong>
        <span class="neg-count">${suggestions.length} item${suggestions.length !== 1 ? 's' : ''}</span>
      </div>
      <div class="neg-rows">${rows}</div>
    </div>`;
}

function renderComparisonRow(c, index) {
  const matchClass = c.match_type.toLowerCase();
  const clauseNums = [c.clause_number_v1, c.clause_number_v2].filter(Boolean);
  const numsText = clauseNums.length === 2 && clauseNums[0] !== clauseNums[1]
    ? `§${clauseNums[0]} → §${clauseNums[1]}`
    : clauseNums.length > 0 ? `§${clauseNums[0]}` : '';

  const simPct = Math.round((c.similarity_score || 0) * 100);

  let deltaHtml = '';
  if (c.risk_delta && c.risk_delta !== 'N/A') {
    const dClass = c.risk_delta.toLowerCase();
    const dIcon = c.risk_delta === 'INCREASED' ? '▲' : c.risk_delta === 'DECREASED' ? '▼' : '—';
    const scores = (c.score_v1 != null && c.score_v2 != null) ? ` ${c.score_v1}→${c.score_v2}` : '';
    deltaHtml = `<span class="delta-arrow ${dClass}">${dIcon}${scores}</span>`;
  }

  const hasDiff = c.diff_text && c.diff_text.trim().length > 0;

  return `
    <div class="comparison-row ${hasDiff ? '' : 'no-diff'}" style="animation-delay: ${index * 40}ms" data-index="${index}">
      <span class="match-badge ${matchClass}">${c.match_type}</span>
      <div class="comparison-clause-info">
        <div class="comparison-clause-nums">${escapeHtml(numsText)}</div>
        <div class="comparison-clause-title">${escapeHtml(c.clause_title)}</div>
      </div>
      <div class="similarity-bar"><div class="similarity-fill" style="width:${simPct}%"></div></div>
      <span class="similarity-text">${simPct}%</span>
      ${deltaHtml}
      ${hasDiff ? '<span class="comparison-expand-icon">▼</span>' : ''}
    </div>
    ${hasDiff ? `<div class="comparison-diff"><div class="comparison-diff-inner">${renderDiffText(c.diff_text)}</div></div>` : ''}
  `;
}

function renderDiffText(raw) {
  if (!raw) return '';
  let ops;
  try { ops = JSON.parse(raw); } catch { return escapeHtml(raw); }
  return ops.map(op => {
    const t = escapeHtml(op.text || '');
    if (op.type === 'add') return `<span class="diff-added">${t} </span>`;
    if (op.type === 'remove') return `<span class="diff-removed">${t} </span>`;
    return t + ' ';
  }).join('');
}

function initComparisonRows(container) {
  container.querySelectorAll('.comparison-row').forEach(row => {
    if (row.classList.contains('no-diff')) return;
    row.addEventListener('click', () => {
      row.classList.toggle('expanded');
    });
  });
}


// ── Skeletons ────────────────────────────────────────────────────────────

function renderSkeletons(count) {
  let html = '<div class="skeleton skeleton-summary"></div>';
  for (let i = 0; i < count; i++) {
    html += '<div class="skeleton skeleton-card"></div>';
  }
  return html;
}


// ── Utilities ────────────────────────────────────────────────────────────

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = String(str);
  return div.innerHTML;
}