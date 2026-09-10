/**
 * GluLess — app.js
 *
 * Two modes:
 *
 *   REPLAY  Default hosted experience. Loads demo/data/proven-canary.json
 *           and plays it through handleEvent() with realistic inter-event
 *           timing. No agent required. Shows REPLAY badge.
 *
 *   LIVE    Connects to a GluLess agent running locally at localhost:8080.
 *           Shows LIVE badge. Falls back to replay if agent is unreachable.
 *
 * The replay fixture is a real captured PROVEN execution — not fabricated.
 */

'use strict';

const AGENT_URL   = 'http://localhost:8080/agent';
const CANARY_URL  = 'data/proven-canary.json';

// Max inter-event delay during replay (keeps full playback under ~3s)
const REPLAY_MAX_DELAY_MS = 180;

const DEMO_CONTRACT = `id: glu-demo-contract
goals:
  - id: goal-list-services
    expression: "services.listed == true"
    description: "List all services and verify they are reachable"
limits:
  - id: limit-deny-all
    action_pattern: "deny *"
    description: "Deny any action not explicitly permitted"
  - id: limit-allow-list
    action_pattern: "allow Monitoring.services.list"
    description: "Permit listing services — read-only, no side effects"
utilities:
  - Monitoring.services.list
evidence_requirements:
  - id: ev-http-ok
    assertion: "response.status == 200"
    description: "Service API responded with HTTP 200"`.trim();

const STAGE_PHASES = {
  resolve:   ['resolving'],
  filter:    ['filtering'],
  authorize: ['authorizing'],
  execute:   ['executing'],
  verify:    ['verifying'],
};

const TERMINAL_PHASES = new Set(['proven', 'unresolved']);

// ── State ─────────────────────────────────────────────────────
let mode         = 'replay';  // 'replay' | 'live'
let isRunning    = false;
let abortCtrl    = null;
let eventCount   = 0;
let currentPhase = null;
let agentOnline  = false;
let canaryData   = null;

// ── DOM refs ──────────────────────────────────────────────────
const $run       = document.getElementById('btn-run');
const $runIcon   = document.getElementById('run-icon');
const $runLabel  = document.getElementById('run-label');
const $statusDot = document.getElementById('status-dot');
const $statusLbl = document.getElementById('status-label');
const $modeBadge = document.getElementById('mode-badge');

const $goalDesc  = document.getElementById('goal-description');
const $goalPred  = document.getElementById('goal-predicate');
const $verdict   = document.getElementById('verdict');

const $limitsList   = document.getElementById('limits-list');
const $fRegistry    = document.getElementById('f-registry');
const $fCompatible  = document.getElementById('f-compatible');
const $fPermitted   = document.getElementById('f-permitted');
const $utilCards    = document.getElementById('util-cards');

const $psc = {
  resolve:   document.getElementById('psc-resolve'),
  filter:    document.getElementById('psc-filter'),
  authorize: document.getElementById('psc-authorize'),
  execute:   document.getElementById('psc-execute'),
  verify:    document.getElementById('psc-verify'),
};

const $ps = {
  resolve:   document.getElementById('ps-resolve'),
  filter:    document.getElementById('ps-filter'),
  authorize: document.getElementById('ps-authorize'),
  execute:   document.getElementById('ps-execute'),
  verify:    document.getElementById('ps-verify'),
};

const $decPaths    = document.getElementById('decision-paths');
const $evEntries   = document.getElementById('evidence-entries');

const $cardResult    = document.getElementById('card-result');
const $resultBlock   = document.getElementById('result-block');
const $resultStatus  = document.getElementById('result-status');
const $resultPred    = document.getElementById('result-predicate');
const $resultVerdict = document.getElementById('result-verdict');

const $contractDrawer = document.getElementById('contract-drawer');
const $contractPre    = document.getElementById('contract-pre');
const $btnContract    = document.getElementById('btn-contract');
const $btnCloseContr  = document.getElementById('btn-close-contract');

const $eventsToggle = document.getElementById('events-toggle');
const $eventsBody   = document.getElementById('events-body');
const $eventsLog    = document.getElementById('events-log');
const $evCount      = document.getElementById('ev-count');
const $toggleCaret  = document.getElementById('toggle-caret');

// ── Bootstrap ─────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  $contractPre.textContent = DEMO_CONTRACT;

  $run.addEventListener('click', onRunClick);

  $btnContract.addEventListener('click', () => {
    const hidden = $contractDrawer.hidden;
    $contractDrawer.hidden = !hidden;
    $btnContract.textContent = hidden ? 'Hide' : 'Contract';
  });

  $btnCloseContr.addEventListener('click', () => {
    $contractDrawer.hidden = true;
    $btnContract.textContent = 'Contract';
  });

  $eventsToggle.addEventListener('click', toggleEvents);

  document.addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && !$run.disabled) {
      e.preventDefault();
      onRunClick();
    }
  });

  // Load canary fixture in parallel with agent probe
  setStatus('connecting', 'Loading…');

  const [canary] = await Promise.all([
    loadCanary(),
    probeAgent(),
  ]);

  canaryData = canary;

  if (agentOnline) {
    setMode('live');
    setStatus('online', 'Agent ready');
  } else {
    setMode('replay');
    setStatus('offline', 'Replay mode');
    if (canaryData) {
      // Auto-play on load when hosted without a local agent
      await sleep(400);
      await runReplay();
    }
  }
});

// ── Mode ──────────────────────────────────────────────────────
function setMode(m) {
  mode = m;
  if (m === 'live') {
    $modeBadge.textContent  = 'LIVE';
    $modeBadge.className    = 'mode-badge live';
    $modeBadge.hidden       = false;
    $runLabel.textContent   = 'Run live';
  } else {
    $modeBadge.textContent  = 'REPLAY';
    $modeBadge.className    = 'mode-badge';
    $modeBadge.hidden       = false;
    $runLabel.textContent   = 'Replay';
  }
}

// ── Agent probe ───────────────────────────────────────────────
async function probeAgent() {
  try {
    const res  = await fetch(AGENT_URL.replace('/agent', '/health'),
      { signal: AbortSignal.timeout(2000) });
    const data = res.ok ? await res.json() : null;
    agentOnline = res.ok;
    if (agentOnline && data) {
      // Update run button label after probe
      $runLabel.textContent = 'Run live';
    }
  } catch {
    agentOnline = false;
  }
}

// ── Load canary fixture ───────────────────────────────────────
async function loadCanary() {
  try {
    const res = await fetch(CANARY_URL);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

function setStatus(state, label) {
  $statusDot.className   = `status-dot ${state}`;
  $statusLbl.textContent = label;
}

// ── Run dispatcher ────────────────────────────────────────────
async function onRunClick() {
  if (isRunning) { abortCtrl?.abort(); return; }

  if (mode === 'live' && agentOnline) {
    await runLive();
  } else if (canaryData) {
    // If live was requested but agent is now gone, fall back silently
    if (mode === 'live') {
      setMode('replay');
      setStatus('offline', 'Agent unreachable — replay');
    }
    await runReplay();
  } else {
    logErr('No canary fixture and no agent. Cannot run.');
  }
}

// ── Replay execution ──────────────────────────────────────────
async function runReplay() {
  if (!canaryData?.events?.length) return;

  startRun();
  setStatus('running', 'Replaying…');

  const events = canaryData.events;
  let prevOffset = 0;

  for (const event of events) {
    if (abortCtrl?.signal.aborted) break;

    const offset  = event.offsetMs ?? 0;
    const rawGap  = offset - prevOffset;
    const delay   = Math.min(rawGap, REPLAY_MAX_DELAY_MS);
    prevOffset    = offset;

    if (delay > 10) await sleep(delay);

    handleEvent(event);
  }

  endRun();
  if (agentOnline) {
    setStatus('online', 'Agent ready');
  } else {
    setStatus('offline', 'Replay complete');
  }
}

// ── Live execution ────────────────────────────────────────────
async function runLive() {
  startRun();
  setStatus('running', 'Running…');

  const threadId = crypto.randomUUID();
  const runId    = crypto.randomUUID();
  abortCtrl      = new AbortController();

  try {
    const res = await fetch(AGENT_URL, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
      body:    JSON.stringify({
        threadId, runId,
        messages: [{ role: 'user', content: DEMO_CONTRACT }],
        context: [], tools: [], state: null,
      }),
      signal: abortCtrl.signal,
    });

    if (!res.ok) {
      logErr(`HTTP ${res.status}: ${await res.text()}`);
      endRun(); return;
    }

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try { handleEvent(JSON.parse(line.slice(6))); }
          catch { /* malformed frame */ }
        }
      }
    }
  } catch (err) {
    if (err.name !== 'AbortError') {
      agentOnline = false;
      setMode('replay');
      logErr(`Agent unreachable: ${err.message}`);
    }
  } finally {
    endRun();
    if (agentOnline) setStatus('online', 'Agent ready');
  }
}

function startRun() {
  isRunning    = true;
  eventCount   = 0;
  currentPhase = null;

  $run.classList.add('running');
  $runIcon.textContent = '◼';
  $run.disabled        = false;

  resetVerdict();
  resetPipeline();

  $decPaths.innerHTML  = '<div class="empty-note">Awaiting authorization…</div>';
  $evEntries.innerHTML = '<div class="empty-note">Awaiting verification…</div>';
  $cardResult.hidden   = true;
  $resultBlock.className = 'result-block';
  $eventsLog.innerHTML = '';
  $evCount.textContent = '0';
}

function endRun() {
  isRunning = false;
  $run.classList.remove('running');
  $runIcon.textContent  = '▶';
  $runLabel.textContent = mode === 'live' ? 'Run live' : 'Replay';
}

// ── Event dispatcher ──────────────────────────────────────────
function handleEvent(event) {
  const { type } = event;

  eventCount++;
  $evCount.textContent = eventCount;

  switch (type) {

    case 'RUN_STARTED':
      logEvt('RUN_STARTED', `thread=${short(event.threadId)}  run=${short(event.runId)}`);
      break;

    case 'TEXT_MESSAGE_START':
    case 'TEXT_MESSAGE_END':
      break;

    case 'TEXT_MESSAGE_CHUNK': {
      const text = (event.delta || '').replace(/\n$/, '');
      if (!text.trim()) break;
      for (const line of text.split('\n')) {
        if (!line.trim()) continue;
        const cls = line.startsWith('✅') ? 'ok'
          : (line.startsWith('⚠') || line.startsWith('🎯')) ? 'warn'
          : line.startsWith('❌') ? 'err'
          : '';
        logEvt('', line, 'chunk' + (cls ? ' ' + cls : ''));
      }
      break;
    }

    case 'STATE_SNAPSHOT':
      applyState(event.snapshot || {});
      logEvt('STATE_SNAPSHOT', `phase=${event.snapshot?.phase}`);
      break;

    case 'STATE_DELTA': {
      const ops = event.delta || [];

      const phaseOp = ops.find(o => o.path === '/phase');
      if (phaseOp?.value) applyPhase(phaseOp.value);

      for (const op of ops.filter(o => o.path?.startsWith('/context_projection'))) {
        if (op.path === '/context_projection/goal_compatible') $fCompatible.textContent = op.value ?? '';
        if (op.path === '/context_projection/limit_permitted') $fPermitted.textContent  = op.value ?? '';
      }

      const dpOp = ops.find(o => o.path === '/decision_paths');
      if (dpOp?.value) renderDecisionPaths(dpOp.value);

      const obsOp = ops.find(o => o.path === '/observations');
      if (obsOp?.value) $psc.execute.textContent = obsOp.value.length;

      const planOp = ops.find(o => o.path === '/plan');
      if (planOp?.value) $psc.authorize.textContent = planOp.value.length;

      const evOp = ops.find(o => o.path === '/evidence');
      if (evOp?.value) renderEvidence(evOp.value);

      logEvt('STATE_DELTA', ops.map(o => {
        const v = Array.isArray(o.value) ? `[${o.value.length}]`
          : typeof o.value === 'object' && o.value !== null ? '[obj]'
          : String(o.value);
        return `${(o.path || '').replace(/^\//, '')}=${v}`;
      }).join('  '));
      break;
    }

    case 'RUN_FINISHED':
      logEvt('RUN_FINISHED', event.warning ? `⚠ ${event.warning}` : 'ok');
      break;

    case 'RUN_ERROR':
      logErr(`${event.code || 'ERROR'}: ${event.message}`);
      applyPhase('error');
      break;

    default:
      logEvt(type, JSON.stringify(event).slice(0, 120));
  }
}

// ── Full state apply ──────────────────────────────────────────
function applyState(s) {
  if (s.goals?.length) {
    const g = s.goals[0];
    $goalDesc.textContent = g.description || 'List all services and verify they are reachable';
    $goalPred.textContent = g.expression  || 'services.listed == true';
  }

  if (s.limits?.length)    renderLimits(s.limits);
  if (s.utilities?.length) renderUtilities(s.utilities);

  if (s.context_projection) {
    const cp = s.context_projection;
    if (cp.registry_total  != null) $fRegistry.textContent   = cp.registry_total;
    if (cp.goal_compatible != null) $fCompatible.textContent = cp.goal_compatible;
    if (cp.limit_permitted != null) $fPermitted.textContent  = cp.limit_permitted;
  }

  if (s.decision_paths?.length) renderDecisionPaths(s.decision_paths);
  if (s.evidence?.length)       renderEvidence(s.evidence);

  if (s.context_projection?.registry_total  != null) $psc.resolve.textContent   = s.context_projection.registry_total;
  if (s.context_projection?.goal_compatible != null) $psc.filter.textContent    = s.context_projection.goal_compatible;
  if (s.context_projection?.limit_permitted != null) $psc.authorize.textContent = s.context_projection.limit_permitted;
  if (s.observations != null) $psc.execute.textContent = s.observations.length;
  if (s.evidence     != null) $psc.verify.textContent  = s.evidence.length;

  if (s.phase) applyPhase(s.phase);
}

// ── Phase → pipeline ──────────────────────────────────────────
function applyPhase(phase) {
  if (phase === currentPhase) return;
  currentPhase = phase;

  const STAGES = ['resolve', 'filter', 'authorize', 'execute', 'verify'];

  let activeIdx = -1;
  for (const [stage, phases] of Object.entries(STAGE_PHASES)) {
    if (phases.includes(phase)) { activeIdx = STAGES.indexOf(stage); break; }
  }

  const isTerminal = TERMINAL_PHASES.has(phase);
  const isError    = phase === 'error';

  STAGES.forEach((stage, idx) => {
    const el = $ps[stage];
    el.className = 'p-stage';
    if      (isTerminal || isError) el.classList.add(isError ? 'error' : 'done');
    else if (idx < activeIdx)       el.classList.add('done');
    else if (idx === activeIdx)     el.classList.add('active');
  });

  if (phase === 'proven') {
    $verdict.className   = 'verdict satisfied';
    $verdict.textContent = 'SATISFIED';
    showResult('proven');
  } else if (phase === 'unresolved') {
    $verdict.className   = 'verdict unresolved';
    $verdict.textContent = 'UNRESOLVED';
    showResult('unresolved');
  }
}

function showResult(verdict) {
  $cardResult.hidden     = false;
  $resultBlock.className = `result-block ${verdict}`;
  $resultStatus.textContent  = verdict === 'proven' ? 'Goal satisfied' : 'Goal unresolved';
  $resultPred.textContent    = $goalPred.textContent;
  $resultVerdict.textContent = verdict === 'proven' ? 'PROVEN' : 'UNRESOLVED';
  $cardResult.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// ── Renderers ─────────────────────────────────────────────────
function renderLimits(limits) {
  $limitsList.innerHTML = limits.map(l => {
    const pat    = l.pattern || '';
    const isDeny = pat.startsWith('deny');
    const verb   = isDeny ? 'deny' : 'allow';
    const rest   = pat.replace(/^(deny|allow)\s*/, '');
    const note   = l.description || (isDeny ? 'default' : '');
    return `<div class="limit-row ${isDeny ? 'deny' : 'allow'}">
      <span class="limit-verb">${verb}</span>
      <span class="limit-pattern">${esc(rest || '*')}</span>
      <span class="limit-note">${esc(note)}</span>
    </div>`;
  }).join('');
}

function renderUtilities(utilities) {
  $utilCards.innerHTML = utilities.map(u => {
    const isMut = (u.type || '').includes('mutation');
    const tr    = u.transport ? `${u.transport.method} ${u.transport.path}` : '';
    return `<div class="util-card" id="uc-${csscl(u.id)}">
      <div class="uc-id">${esc(u.id)}</div>
      <div class="uc-tags">
        <span class="tag ${isMut ? 'mutation' : 'read'}">${isMut ? 'MUTATION' : 'READ'}</span>
        <span style="font-size:11px;color:var(--quiet)">${esc(u.sideEffects || 'no side effects')}</span>
      </div>
      ${tr ? `<div class="uc-transport">${esc(tr)}</div>` : ''}
    </div>`;
  }).join('');
}

function renderDecisionPaths(paths) {
  if (!paths?.length) return;
  $decPaths.innerHTML = paths.map(d => {
    const isAuth  = d.decision === 'authorized' || d.decision === 'allow';
    const glyph   = isAuth ? '✅' : '✕';
    const verdict = isAuth ? 'AUTHORIZED' : 'DENIED';
    const effect  = d.sideEffects === 'none' ? 'read · no side effects'
      : d.sideEffects ? d.sideEffects.replace(/-/g, ' ')
      : d.type || '';
    return `<div class="dp-row ${isAuth ? 'authorized' : 'denied'}">
      <span class="dp-glyph">${glyph}</span>
      <div class="dp-body">
        <div class="dp-id">${esc(d.utilityId)}</div>
        <div class="dp-meta">${esc(effect)}</div>
        <div class="dp-reason">${esc(d.reason || '')}</div>
      </div>
      <span class="dp-verdict">${verdict}</span>
    </div>`;
  }).join('');
}

function renderEvidence(items) {
  if (!items?.length) return;
  $evEntries.innerHTML = items.map(ev => {
    const pass   = ev.passed;
    const glyph  = pass ? '✅' : '❌';
    const detail = ev.httpStatus != null ? `HTTP ${ev.httpStatus}` : (pass ? 'passed' : 'failed');
    return `<div class="ev-row ${pass ? 'pass' : 'fail'}">
      <span class="ev-glyph">${glyph}</span>
      <div class="ev-body">
        <div class="ev-req">${esc(ev.requirementId)}</div>
        <div class="ev-assert">${esc(ev.assertion)}</div>
        <div class="ev-detail">${esc(detail)}</div>
      </div>
    </div>`;
  }).join('');
  $psc.verify.textContent = items.length;
}

// ── Events drawer ─────────────────────────────────────────────
function toggleEvents() {
  const isOpen = !$eventsBody.hidden;
  $eventsBody.hidden = isOpen;
  $eventsToggle.setAttribute('aria-expanded', String(!isOpen));
  $toggleCaret.className = `toggle-caret${isOpen ? '' : ' open'}`;
}

function logEvt(type, body, extra = '') {
  const row = document.createElement('div');
  row.className = `log-row${extra ? ' ' + extra : ''}`;
  row.innerHTML =
    `<span class="log-ts">${mode === 'replay' ? '[replay]' : now()}</span>` +
    `<span class="log-type">${esc(type)}</span>` +
    `<span class="log-body">${esc(body)}</span>`;
  $eventsLog.appendChild(row);
  $eventsLog.scrollTop = $eventsLog.scrollHeight;
}

function logErr(msg) {
  logEvt('ERROR', msg, 'err');
  if ($eventsBody.hidden) toggleEvents();
}

// ── Resets ────────────────────────────────────────────────────
function resetVerdict() {
  $verdict.className   = 'verdict';
  $verdict.textContent = 'UNSATISFIED';
}

function resetPipeline() {
  Object.values($ps).forEach(el  => { el.className = 'p-stage'; });
  Object.values($psc).forEach(el => { el.textContent = ''; });
}

// ── Helpers ───────────────────────────────────────────────────
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function csscl(s) { return String(s).replace(/[^a-zA-Z0-9-]/g, '-'); }
function short(u) { return u ? `${u.slice(0, 8)}…` : '?'; }
function now() {
  return new Date().toLocaleTimeString('en-US', {
    hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}
