'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  storyboard: null,
  director: null,
  directorShot: 1,
  directorOpenGroup: null,
  directorCustomField: null,
  previewJob: null,
  previewDisplayed: null,
  previewJobTimer: null,
  job: null,
  jobTimer: null,
  outputs: [],
  deletedOutputs: new Set(),
  previewIndex: 0,
  previewZoom: Number(sessionStorage.getItem('valhalla-preview-zoom')) || 100,
  previewFit: sessionStorage.getItem('valhalla-preview-fit') === 'true',
  deleteResolver: null,
  promptShot: null,
  promptTab: 'positive',
  seedResolveTimer: null,
  resolveVersion: 0,
  initialAutoResolved: false,
  theme: sessionStorage.getItem('valhalla-theme') || 'system',
};

const form = $('#run-form');
const emptyState = $('#empty-state');
const loadingState = $('#loading-state');
const shotGrid = $('#shot-grid');
const storyboardActions = $('#storyboard-actions');
const storyboardMeta = $('#storyboard-meta');
const imageDialog = $('#image-dialog');
const deleteDialog = $('#delete-dialog');
const promptDialog = $("#prompt-dialog");
const directorCustomDialog = $("#director-custom-dialog");

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  let body;
  try { body = await response.json(); } catch { body = {}; }
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}

function toast(title, message = '', type = '') {
  const item = document.createElement('div');
  const compactMessage = String(message).length > 180 ? `${String(message).slice(0, 177)}…` : message;
  item.className = `toast ${type}`;
  item.title = 'Click to dismiss';
  item.innerHTML = `<span class="toast-copy"><strong>${escapeHtml(title)}</strong>${escapeHtml(compactMessage)}</span><i class="toast-clock" aria-hidden="true"></i>`;
  $('#toast-region').append(item);
  const timer = setTimeout(() => item.remove(), 3600);
  item.addEventListener('click', () => {
    clearTimeout(timer);
    item.remove();
  });
}

function setBusy(button, busy, label) {
  if (!button) return;
  if (busy) {
    button.dataset.label = button.innerHTML;
    button.disabled = true;
    if (label) button.textContent = label;
  } else {
    button.disabled = false;
    if (button.dataset.label) button.innerHTML = button.dataset.label;
  }
}

function applyTheme() {
  if (state.theme === 'system') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.dataset.theme = state.theme;
  const icon = { system: '◐', light: '☀', dark: '☾' }[state.theme];
  $('#theme-icon').textContent = icon;
  $('#theme-label').textContent = `${state.theme[0].toUpperCase()}${state.theme.slice(1)}`;
  $('#theme-button').title = `Theme: ${state.theme}`;
}

function cycleTheme() {
  state.theme = { system: 'light', light: 'dark', dark: 'system' }[state.theme];
  sessionStorage.setItem('valhalla-theme', state.theme);
  applyTheme();
  toast('Theme updated', `${state.theme[0].toUpperCase()}${state.theme.slice(1)} appearance`);
}

async function refreshStatus(showToast = false) {
  const button = $('#refresh-status');
  button.textContent = '…';
  try {
    const status = await api('/api/status');
    $('#comfy-status').textContent = status.comfy.online ? 'Online' : 'Offline';
    $('#comfy-dot').className = `status-dot ${status.comfy.online ? 'online' : 'error'}`;
    $('#workflow-status').textContent = status.workflow.ready ? 'Ready' : 'Missing';
    $('#workflow-dot').className = `status-dot ${status.workflow.ready ? 'online' : 'error'}`;
    $('#catalog-status').textContent = status.catalog_records.toLocaleString();
    if (showToast) toast('Status refreshed', status.comfy.online ? 'ComfyUI is connected.' : 'ComfyUI is currently offline.', status.comfy.online ? 'success' : 'error');
  } catch (error) {
    $('#comfy-status').textContent = 'Error';
    $('#comfy-dot').className = 'status-dot error';
    if (showToast) toast('Status failed', error.message, 'error');
  } finally {
    button.textContent = '↻';
  }
}

function syncForm() {
  const mode = form.elements.mode.value;
  const content = form.elements.content.value;
  const photoshoots = Math.max(1, Number(form.elements.photoshoots.value) || 1);
  const count = Math.max(1, Number(form.elements.count.value) || 1);
  const total = (mode === 'photoshoot' ? photoshoots : 1) * count;
  $('#photoshoots-field').classList.toggle('hidden', mode === 'random');
  $('#progression-fields').classList.toggle('hidden', mode === 'random' || content === 'xxx');
  $('#mode-help').textContent = mode === 'photoshoot'
    ? 'One consistent subject, wardrobe and set per photoshoot.'
    : 'Every image receives an independently assembled production context.';
  $('#nsfw-output').textContent = `${form.elements.nsfw_percent.value}%`;
  $('#plateau-output').textContent = `${form.elements.plateau_percent.value}%`;
  $('#planned-total').textContent = `${total} image${total === 1 ? '' : 's'}`;
}

function restoreConfig(config, job) {
  const mode = form.querySelector(`[name="mode"][value="${config.mode}"]`);
  const content = form.querySelector(`[name="content"][value="${config.xxx_only ? 'xxx' : 'progressive'}"]`);
  if (mode) mode.checked = true;
  if (content) content.checked = true;
  form.elements.count.value = config.count;
  form.elements.photoshoots.value = config.photoshoots;
  form.elements.prompt_seed.value = config.prompt_seed ?? '';
  form.elements.inference_seed.value = config.inference_seed ?? '';
  form.elements.inference_strategy.value = config.inference_strategy || 'sequence';
  form.elements.retry_count.value = config.retry_count ?? 2;
  if (config.nsfw_percent != null) form.elements.nsfw_percent.value = config.nsfw_percent;
  if (config.plateau_percent != null) form.elements.plateau_percent.value = config.plateau_percent;
  form.elements.fast.checked = Boolean(job.fast);
  syncForm();
}

function configPayload() {
  const value = (name) => form.elements[name].value;
  return {
    mode: value('mode'),
    count: Number(value('count')),
    photoshoots: Number(value('photoshoots')),
    xxx_only: value('content') === 'xxx',
    nsfw_percent: Number(value('nsfw_percent')),
    plateau_percent: Number(value('plateau_percent')),
    prompt_seed: value('prompt_seed') === '' ? null : value('prompt_seed'),
    inference_seed: value('inference_seed') === '' ? null : value('inference_seed'),
    inference_strategy: value('inference_strategy'),
    retry_count: Number(value('retry_count')),
    fast: form.elements.fast.checked,
  };
}

async function resolveStoryboard(event, options = {}) {
  if (event?.preventDefault) event.preventDefault();
  clearTimeout(state.seedResolveTimer);
  const version = ++state.resolveVersion;
  const button = $('#resolve-button');
  setBusy(button, true, 'Resolving…');
  emptyState.classList.add('hidden');
  shotGrid.classList.add('hidden');
  storyboardActions.classList.add('hidden');
  storyboardMeta.classList.add('hidden');
  loadingState.classList.remove('hidden');
  try {
    const storyboard = await api('/api/storyboards', { method: 'POST', body: JSON.stringify(configPayload()) });
    if (version !== state.resolveVersion) return;
    state.storyboard = storyboard;
    form.elements.prompt_seed.value = storyboard.config.prompt_seed ?? '';
    form.elements.inference_seed.value = storyboard.config.inference_seed ?? '';
    renderStoryboard();
    toast(
      options.automatic ? 'Seeds applied' : 'Storyboard ready',
      `${state.storyboard.total} compatible shots resolved${options.automatic ? ' and Director updated' : ''}.`,
      'success',
    );
  } catch (error) {
    if (version !== state.resolveVersion) return;
    emptyState.classList.remove('hidden');
    toast('Could not resolve storyboard', error.message, 'error');
  } finally {
    if (version !== state.resolveVersion) return;
    loadingState.classList.add('hidden');
    setBusy(button, false);
  }
}

function scheduleSeedResolve(event) {
  if (!state.storyboard || isRenderActive()) return;
  const name = event.target?.name;
  if (!['prompt_seed', 'inference_seed', 'inference_strategy'].includes(name)) return;
  clearTimeout(state.seedResolveTimer);
  state.seedResolveTimer = setTimeout(
    () => name === 'prompt_seed'
      ? resolveStoryboard(null, { automatic: true })
      : applyVariationSettings(),
    650,
  );
}

function generateUiSeed() {
  const words = new Uint32Array(2);
  crypto.getRandomValues(words);
  return (words[0] & 0x1fffff) * 0x100000000 + words[1];
}

function randomizeSeedField(name) {
  const input = form.elements[name];
  const previous = input.value;
  let next;
  do { next = String(generateUiSeed()); } while (next === previous);
  input.value = next;
  input.dispatchEvent(new Event('input', { bubbles: true }));
}

async function applyVariationSettings() {
  if (!state.storyboard || isRenderActive()) return;
  const version = ++state.resolveVersion;
  const seed = form.elements.inference_seed.value;
  try {
    const storyboard = await api(`/api/storyboards/${state.storyboard.id}/seeds`, {
      method: 'POST',
      body: JSON.stringify({
        inference_seed: seed === '' ? null : seed,
        inference_strategy: form.elements.inference_strategy.value,
      }),
    });
    if (version !== state.resolveVersion) return;
    state.storyboard = storyboard;
    state.director = null;
    form.elements.inference_seed.value = storyboard.config.inference_seed ?? '';
    renderStoryboard();
    toast('Image variations updated', 'Director custom values and shot directions were preserved.', 'success');
  } catch (error) {
    if (version !== state.resolveVersion) return;
    toast('Could not update image variations', error.message, 'error');
  }
}

async function exportStoryboard() {
  if (!state.storyboard) return;
  const button = $('#export-storyboard');
  setBusy(button, true, 'Exporting…');
  try {
    const payload = await api(`/api/storyboards/${state.storyboard.id}/export`);
    if (payload.format !== 'valhalla-storyboard') {
      throw new Error('Server returned a storyboard snapshot instead of an export. Restart the server and try again.');
    }
    const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
    const link = document.createElement('a');
    const stamp = new Date().toISOString().replaceAll(':', '-').replace(/\.\d{3}Z$/, 'Z');
    link.href = URL.createObjectURL(blob);
    link.download = `valhalla-storyboard-${stamp}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 0);
    toast('Storyboard exported', `${state.storyboard.total} shots saved in compact JSON.`, 'success');
  } catch (error) {
    toast('Export failed', error.message, 'error');
  } finally {
    setBusy(button, false);
  }
}

async function importStoryboard(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  const button = $('#import-storyboard');
  setBusy(button, true, 'Importing…');
  try {
    if (file.size > 32_000_000) throw new Error('Storyboard file is larger than 32 MB.');
    const payload = JSON.parse(await file.text());
    state.storyboard = await api('/api/storyboards/import', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    restoreConfig(state.storyboard.config, { fast: state.storyboard.config.fast });
    renderStoryboard();
    switchView('studio');
    toast('Storyboard imported', `${state.storyboard.total} shots are ready to render.`, 'success');
  } catch (error) {
    const message = error instanceof SyntaxError ? 'The selected file is not valid JSON.' : error.message;
    toast('Import failed', message, 'error');
  } finally {
    setBusy(button, false);
  }
}

function shotCard(shot) {
  const explicit = shot.stage.level === 'explicit' ? 'explicit' : '';
  const stage = shot.stage.plateau_kind || shot.stage.level;
  return `
    <article class="shot-card" data-shot="${shot.number}">
      <div class="shot-top">
        <div class="shot-number"><i>${String(shot.number).padStart(2, '0')}</i> Shot ${shot.shot_index + 1}</div>
        <span class="stage-badge ${explicit} ${shot.stage.manual ? 'manual' : ''}">${shot.stage.manual ? '<i>Manual</i>' : ''}${escapeHtml(stage.replaceAll('_', ' '))}</span>
      </div>
      <div class="shot-body">
        <div class="shot-set">Set ${shot.photoshoot_index + 1} · ${escapeHtml(shot.wardrobe)}</div>
        <div class="shot-detail"><span>Pose</span><strong title="${escapeHtml(shot.pose.prompt)}">${escapeHtml(shot.pose.prompt)}</strong></div>
        <div class="shot-detail"><span>Action</span><strong title="${escapeHtml(shot.action.prompt)}">${escapeHtml(shot.action.prompt)}</strong></div>
        <div class="shot-detail"><span>Role</span><strong title="${escapeHtml(shot.editorial_role.prompt)}">${escapeHtml(shot.editorial_role.prompt)}</strong></div>
        <div class="shot-detail"><span>Camera</span><strong title="${escapeHtml(shot.camera)}">${escapeHtml(shot.camera)}</strong></div>
        <div class="shot-detail"><span>Variation</span><strong title="Inference seed ${shot.inference_seed}">${shot.seed_manual ? 'Custom · ' : ''}${escapeHtml(shot.inference_seed)}</strong></div>
      </div>
      <div class="shot-footer">
        <button class="direct" data-action="director">⌘ Director</button>
        <button class="reroll" data-action="reroll">↻ Reroll</button>
        <button data-action="inspect">≡ Prompt</button>
        <button class="variation" data-action="variation">⤨ Variation</button>
        <button class="preview" data-action="preview">◉ Preview</button>
        <button class="render-one" data-action="render">▶ Render</button>
      </div>
    </article>`;
}

function renderStoryboard() {
  const board = state.storyboard;
  if (!board) return;
  if (state.director?.storyboard_id !== board.id) {
    state.director = null;
    state.directorOpenGroup = null;
  }
  shotGrid.innerHTML = board.shots.map(shotCard).join('');
  $('#seed-pill').textContent = `Seed ${board.config.prompt_seed}`;
  const sets = board.config.mode === 'photoshoot' ? board.config.photoshoots : 'Independent';
  storyboardMeta.innerHTML = `<span>Mode <strong>${escapeHtml(board.config.mode)}</strong></span><span>Sets <strong>${sets}</strong></span><span>Shots <strong>${board.total}</strong></span><span>Diversity <strong>${board.diversity}%</strong></span><span>Content <strong>${board.config.xxx_only ? 'Full XXX' : 'Progressive'}</strong></span>`;
  emptyState.classList.add('hidden');
  storyboardActions.classList.remove('hidden');
  storyboardMeta.classList.remove('hidden');
  shotGrid.classList.remove('hidden');
}

function renderOneShot(shot) {
  const index = state.storyboard.shots.findIndex((item) => item.number === shot.number);
  state.storyboard.shots[index] = shot;
  const current = $(`.shot-card[data-shot="${shot.number}"]`);
  const wrapper = document.createElement('div');
  wrapper.innerHTML = shotCard(shot).trim();
  current.replaceWith(wrapper.firstElementChild);
}

async function rerollShot(number, button) {
  setBusy(button, true, '…');
  try {
    const shot = await api(`/api/storyboards/${state.storyboard.id}/shots/${number}/reroll`, { method: 'POST', body: '{}' });
    renderOneShot(shot);
    toast(`Shot ${number} redirected`, 'Composition and prompt were updated.', 'success');
  } catch (error) {
    setBusy(button, false);
    toast('Could not reroll shot', error.message, 'error');
  }
}

async function randomizeShotSeed(number, button) {
  if (!state.storyboard || isRenderActive()) return;
  setBusy(button, true, '…');
  try {
    const shot = await api(`/api/storyboards/${state.storyboard.id}/shots/${number}/seed`, {
      method: 'POST', body: '{}',
    });
    renderOneShot(shot);
    if (state.director && state.directorShot === number) await loadDirector(number);
    toast('New image variation', `Shot ${number} now uses seed ${shot.inference_seed}.`, 'success');
  } catch (error) {
    toast('Could not change variation', error.message, 'error');
  } finally {
    setBusy(button, false);
  }
}

function openPrompt(shot) {
  state.promptShot = shot;
  state.promptTab = 'positive';
  $('#dialog-eyebrow').textContent = `Set ${shot.photoshoot_index + 1} · Shot ${shot.shot_index + 1}`;
  $('#dialog-title').textContent = `${shot.stage.level[0].toUpperCase()}${shot.stage.level.slice(1)} composition`;
  $$('.prompt-tabs button').forEach((button) => button.classList.toggle('active', button.dataset.prompt === 'positive'));
  updatePromptContent();
  promptDialog.showModal();
}

function updatePromptContent() {
  if (!state.promptShot) return;
  const content = {
    positive: state.promptShot.positive_prompt,
    negative: state.promptShot.negative_prompt,
    ids: state.promptShot.selected_ids.join('\n'),
  }[state.promptTab];
  $('#prompt-content').textContent = content;
}

async function startGeneration() {
  if (!state.storyboard) return;
  if (isRenderActive()) {
    toast('Render already active', 'The current production is already in the render pipeline.');
    return;
  }
  const buttons = $$('[data-render-action]');
  buttons.forEach((button) => {
    if (!button.dataset.idleLabel) button.dataset.idleLabel = button.innerHTML;
    setBusy(button, true, 'Queueing…');
  });
  try {
    state.job = await api('/api/jobs', {
      method: 'POST',
      body: JSON.stringify({ storyboard_id: state.storyboard.id, fast: form.elements.fast.checked }),
    });
    showJob();
    pollJob();
    switchView('outputs');
    toast('Production queued', `${state.job.total} images sent to the render pipeline.`, 'success');
  } catch (error) {
    toast('Could not start generation', error.message, 'error');
  } finally {
    buttons.forEach((button) => setBusy(button, false));
    syncRenderControls();
  }
}

async function startShotRender(number, button) {
  if (!state.storyboard || isRenderActive()) return;
  setBusy(button, true, 'Queueing…');
  try {
    state.job = await api(`/api/storyboards/${state.storyboard.id}/shots/${number}/render`, {
      method: 'POST', body: JSON.stringify({ fast: form.elements.fast.checked }),
    });
    showJob();
    pollJob();
    switchView('outputs');
    toast('Shot queued', `Shot ${number} was sent to the render pipeline.`, 'success');
  } catch (error) {
    toast('Could not render shot', error.message, 'error');
  } finally {
    setBusy(button, false);
  }
}

function formatTime(seconds) {
  if (seconds == null) return 'Calculating ETA';
  if (seconds < 60) return `${Math.round(seconds)} sec remaining`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${Math.round(seconds % 60)} sec remaining`;
}

function formatDuration(seconds) {
  if (seconds == null) return '—';
  const value = Math.max(0, Math.round(seconds));
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const rest = value % 60;
  return hours ? `${hours}h ${minutes}m` : (minutes ? `${minutes}m ${rest}s` : `${rest}s`);
}

function formatLoggedPrompt(prompt) {
  return prompt ? String(prompt).replaceAll(', ', ',\n') : 'Waiting for a frame…';
}

function renderLogger() {
  const preview = state.previewJob;
  const usePreview = preview && (!state.job || new Date(preview.created_at) >= new Date(state.job.created_at));
  const job = usePreview ? null : state.job;
  const empty = $('#logger-empty');
  const workspace = $('#logger-workspace');
  if (!job && !preview) {
    empty.classList.remove('hidden');
    workspace.classList.add('hidden');
    $('#log-count').textContent = '0';
    $('#clear-logger').disabled = false;
    return;
  }
  empty.classList.add('hidden');
  workspace.classList.remove('hidden');
  if (usePreview) {
    $('#clear-logger').disabled = ['queued', 'running'].includes(preview.status);
    $('#log-count').textContent = '1';
    const status = $('#logger-status');
    status.textContent = `Preview · ${preview.status}`;
    status.className = `logger-status ${preview.status}`;
    $('#logger-progress').textContent = 'Preview';
    $('#logger-percent').textContent = preview.status === 'completed' ? 'Ready' : 'Rendering one shot';
    $('#logger-elapsed').textContent = formatDuration(preview.elapsed_seconds);
    $('#logger-eta').textContent = preview.status === 'completed' ? 'Complete' : 'Calculating';
    $('#logger-shot').textContent = `Shot ${preview.shot}`;
    $('#logger-seed').textContent = `Seed ${preview.seed}`;
    $('#logger-positive').textContent = formatLoggedPrompt(preview.positive);
    $('#logger-negative').textContent = formatLoggedPrompt(preview.negative);
    $('#logger-job-id').textContent = `Preview ${preview.id.slice(0, 10)}`;
    const time = new Date(preview.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    $('#logger-event-list').innerHTML = `<div class="logger-event ${escapeHtml(preview.status)}"><time>${escapeHtml(time)}</time><i>preview</i><span>${escapeHtml(`Shot ${preview.shot} preview ${preview.status}`)}</span><em>1/1</em></div>`;
    return;
  }
  const logs = job.logs || [];
  $('#clear-logger').disabled = ['queued', 'running'].includes(job.status);
  $('#log-count').textContent = logs.length;
  const status = $('#logger-status');
  status.textContent = job.cancel_requested ? 'Cancelling' : job.status;
  status.className = `logger-status ${job.status}`;
  const visiblePosition = job.current_prompt?.position || job.completed || 0;
  $('#logger-progress').textContent = `${visiblePosition} / ${job.total}`;
  $('#logger-percent').textContent = `${job.progress || 0}% complete`;
  $('#logger-elapsed').textContent = formatDuration(job.elapsed_seconds);
  $('#logger-eta').textContent = job.status === 'completed' ? 'Complete' : formatDuration(job.eta_seconds);
  $('#logger-shot').textContent = job.current_prompt ? `Shot ${job.current_prompt.shot}` : '—';
  $('#logger-seed').textContent = job.current_prompt ? `Seed ${job.current_prompt.seed}` : 'Seed —';
  $('#logger-positive').textContent = formatLoggedPrompt(job.current_prompt?.positive);
  $('#logger-negative').textContent = formatLoggedPrompt(job.current_prompt?.negative);
  $('#logger-job-id').textContent = `Job ${job.id.slice(0, 10)}`;
  $('#logger-event-list').innerHTML = [...logs].reverse().map((entry) => {
    const time = new Date(entry.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const count = entry.position ? `${entry.position}/${entry.total}` : `0/${entry.total}`;
    const detail = entry.duration_seconds != null ? `${entry.message} · ${formatDuration(entry.duration_seconds)}` : entry.message;
    return `<div class="logger-event ${escapeHtml(entry.type)}"><time>${escapeHtml(time)}</time><i>${escapeHtml(entry.type.replaceAll('_', ' '))}</i><span>${escapeHtml(detail)}</span><em>${escapeHtml(count)}</em></div>`;
  }).join('');
}

function showJob() {
  const job = state.job;
  if (!job) return;
  syncRenderControls();
  $('#job-dock').classList.remove('hidden');
  $('#job-percent').textContent = `${job.progress || 0}%`;
  $('#job-progress').style.width = `${job.progress || 0}%`;
  $('#job-detail').textContent = job.cancel_requested
    ? 'Cancelling… current image will finish'
    : (job.status === 'queued'
      ? 'Preparing workflow…'
      : `${job.retrying ? `Retry ${job.attempt} · ` : ''}Image ${job.completed} of ${job.total} · ${formatTime(job.eta_seconds)}`);
  $('#cancel-job').disabled = Boolean(job.cancel_requested);
  renderLogger();
}

async function pollJob() {
  clearTimeout(state.jobTimer);
  if (!state.job) return;
  try {
    state.job = await api(`/api/jobs/${state.job.id}`);
    addOutputs(state.job.outputs || []);
    showJob();
    if (['queued', 'running'].includes(state.job.status)) {
      state.jobTimer = setTimeout(pollJob, 1200);
      return;
    }
    finishJob();
  } catch (error) {
    toast('Lost render status', error.message, 'error');
    state.jobTimer = setTimeout(pollJob, 3000);
  }
}

function finishJob() {
  const job = state.job;
  syncRenderControls();
  $('#job-dock').classList.add('hidden');
  if (job.status === 'completed') {
    toast('Production complete', `${job.outputs.length} output${job.outputs.length === 1 ? '' : 's'} saved.`, 'success');
    switchView('outputs');
  } else if (job.status === 'cancelled') {
    toast('Production cancelled', `${job.completed} of ${job.total} images completed.`);
  } else {
    toast('Production failed', job.error || 'Unknown render error', 'error');
  }
}

function addOutputs(outputs) {
  const names = new Set(state.outputs.map((item) => item.name));
  outputs.forEach((item) => {
    if (!names.has(item.name) && !state.deletedOutputs.has(item.name)) {
      state.outputs.push(item);
    }
  });
  renderOutputs();
}

function isRenderActive() {
  return state.job && ['queued', 'running'].includes(state.job.status);
}

function syncRenderControls() {
  const active = Boolean(isRenderActive());
  $$('[data-render-action]').forEach((button) => {
    if (!button.dataset.idleLabel) {
      button.dataset.idleLabel = button.dataset.label || button.innerHTML;
    }
    button.disabled = active;
    button.innerHTML = active ? (state.job?.cancel_requested ? '◌ Cancelling…' : '◌ Rendering…') : button.dataset.idleLabel;
    button.title = active ? 'A render job is already active' : 'Render the current storyboard';
  });
}

function syncDeleteControls() {
  const disabled = Boolean(isRenderActive());
  $('#delete-all-outputs').classList.toggle('hidden', state.outputs.length === 0);
  $('#delete-all-outputs').disabled = disabled;
  $('#delete-all-outputs').title = disabled
    ? 'Bulk deletion is unavailable while rendering'
    : '';
  $$('.output-delete, #image-viewer-delete').forEach((button) => {
    button.disabled = false;
    button.title = 'Delete this completed image';
  });
}

function confirmDeletion(title, message, confirmLabel) {
  $('#delete-dialog-title').textContent = title;
  $('#delete-dialog-message').textContent = message;
  $('#delete-dialog-confirm').textContent = confirmLabel;
  return new Promise((resolve) => {
    state.deleteResolver = resolve;
    deleteDialog.showModal();
  });
}

function resolveDeletion(value) {
  const resolve = state.deleteResolver;
  state.deleteResolver = null;
  if (deleteDialog.open) deleteDialog.close();
  if (resolve) resolve(value);
}

async function deleteOutput(index) {
  const item = state.outputs[index];
  if (!item) return;
  const confirmed = await confirmDeletion(
    'Delete this image?',
    `${item.name} will be permanently removed from the output folder.`,
    'Delete image',
  );
  if (!confirmed) return;
  try {
    await api(`/api/outputs/${encodeURIComponent(item.name)}`, { method: 'DELETE' });
    state.deletedOutputs.add(item.name);
    state.outputs = state.outputs.filter((output) => output.name !== item.name);
    renderOutputs();
    if (imageDialog.open) {
      if (!state.outputs.length) imageDialog.close();
      else showPreview(Math.min(index, state.outputs.length - 1));
    }
    toast('Image deleted', item.name, 'success');
  } catch (error) {
    toast('Could not delete image', error.message, 'error');
  }
}

async function deleteAllOutputs() {
  if (!state.outputs.length) return;
  if (isRenderActive()) {
    toast('Deletion unavailable', 'Wait for the active render job to finish or cancel it first.', 'error');
    return;
  }
  const count = state.outputs.length;
  const confirmed = await confirmDeletion(
    `Delete all ${count} images?`,
    'Every generated image in the output folder will be permanently deleted. This cannot be undone.',
    'Delete everything',
  );
  if (!confirmed) return;
  try {
    const result = await api('/api/outputs', { method: 'DELETE' });
    state.outputs = [];
    if (imageDialog.open) imageDialog.close();
    renderOutputs();
    toast('Outputs deleted', `${result.deleted} image${result.deleted === 1 ? '' : 's'} permanently removed.`, 'success');
  } catch (error) {
    toast('Could not delete outputs', error.message, 'error');
  }
}

async function loadOutputs() {
  try {
    const result = await api('/api/outputs');
    state.outputs = result.outputs || [];
  } catch (error) {
    toast('Could not load outputs', error.message, 'error');
  }
  renderOutputs();
}

async function restoreApplication() {
  await loadOutputs();
  try {
    const session = await api('/api/jobs');
    state.previewJob = session.latest_preview || null;
    state.job = session.active_job || session.jobs?.[0] || null;
    renderLogger();
    if (state.job) {
      try {
        state.storyboard = await api(`/api/storyboards/${state.job.storyboard_id}`);
        restoreConfig(state.storyboard.config, state.job);
        renderStoryboard();
      } catch (error) {
        toast('Storyboard recovery limited', error.message, 'error');
      }
      showJob();
      if (session.active_job) pollJob();
      toast(
        session.active_job ? 'Active render restored' : 'Latest render restored',
        `${state.job.completed} of ${state.job.total} images completed.`,
        'success',
      );
    }
  } catch (error) {
    toast('Could not restore render state', error.message, 'error');
  }
  if (!state.storyboard && !state.initialAutoResolved) {
    state.initialAutoResolved = true;
    await resolveStoryboard(null, { initial: true });
  }
}

function renderOutputs() {
  const count = state.outputs.length;
  $('#output-count').textContent = count;
  $('#outputs-empty').classList.toggle('hidden', count > 0);
  $('#outputs-summary').textContent = count
    ? `${count} generated image${count === 1 ? '' : 's'}.`
    : 'No generated images.';
  $('#output-grid').innerHTML = state.outputs.map((item, index) => {
    const shotLabel = item.shot == null ? 'Output' : `Shot ${item.shot}`;
    return `
    <article class="output-card" data-output-index="${index}" tabindex="0" role="button" aria-label="Maximize ${escapeHtml(shotLabel)}">
      <img src="${encodeURI(item.url)}" alt="Generated ${escapeHtml(shotLabel)}" loading="lazy">
      <footer><span>${escapeHtml(shotLabel)}</span><span class="output-actions"><button class="output-delete" data-action="delete-output" aria-label="Delete ${escapeHtml(item.name)}">Delete</button><a href="${encodeURI(item.url)}" download="${escapeHtml(item.name)}">Download</a></span></footer>
    </article>`;
  }).join('');
  syncDeleteControls();
}

function persistPreviewScale() {
  sessionStorage.setItem('valhalla-preview-zoom', String(state.previewZoom));
  sessionStorage.setItem('valhalla-preview-fit', String(state.previewFit));
}

function syncPreviewScaleControls() {
  $('#image-fit').checked = state.previewFit;
  $('#image-zoom').value = String(state.previewZoom);
  $('#image-zoom-output').textContent = `${state.previewZoom}%`;
}

  state.previewZoom = Math.min(300, Math.max(25, Number(state.previewZoom) || 100));
function fitPreviewImage() {
  const image = $('#image-viewer-image');
  const stage = $('.image-stage');
  const stageWidth = stage.clientWidth;
  const stageHeight = stage.clientHeight;
  if (!image.naturalWidth || !image.naturalHeight || !stageWidth || !stageHeight) return;
  const scale = state.previewFit
    ? Math.min(stageWidth / image.naturalWidth, stageHeight / image.naturalHeight)
    : state.previewZoom / 100;
  image.style.width = `${Math.round(image.naturalWidth * scale)}px`;
  image.style.height = `${Math.round(image.naturalHeight * scale)}px`;
}

function setPreviewZoom(value) {
  state.previewZoom = Math.min(300, Math.max(25, Number(value) || 100));
  state.previewFit = false;
  persistPreviewScale();
  syncPreviewScaleControls();
  fitPreviewImage();
}

function setPreviewFit(value) {
  state.previewFit = Boolean(value);
  if (!state.previewFit) state.previewZoom = 100;
  persistPreviewScale();
  syncPreviewScaleControls();
  fitPreviewImage();
}

function showPreview(index) {
  if (!state.outputs.length) return;
  state.previewIndex = (index + state.outputs.length) % state.outputs.length;
  const item = state.outputs[state.previewIndex];
  const image = $('#image-viewer-image');
  image.src = item.url;
  image.alt = `Maximized generated output from shot ${item.shot}`;
  $('#image-viewer-title').textContent = item.name;
  $('#image-viewer-count').textContent = `${state.previewIndex + 1} of ${state.outputs.length}`;
  const download = $('#image-viewer-download');
  download.href = item.url;
  download.download = item.name;
  const single = state.outputs.length < 2;
  $('#image-previous').disabled = single;
  $('#image-next').disabled = single;
}

function openPreview(index) {
  showPreview(index);
  if (!imageDialog.open) imageDialog.showModal();
  requestAnimationFrame(fitPreviewImage);
}

function movePreview(direction) {
  showPreview(state.previewIndex + direction);
}

$('#output-grid').addEventListener('click', (event) => {
  const card = event.target.closest('.output-card');
  if (!card) return;
  if (event.target.closest('[data-action="delete-output"]')) {
    deleteOutput(Number(card.dataset.outputIndex));
    return;
  }
  if (event.target.closest('a, button')) return;
  openPreview(Number(card.dataset.outputIndex));
});
$('#image-fit').addEventListener('change', (event) => setPreviewFit(event.target.checked));
$('#image-zoom').addEventListener('input', (event) => setPreviewZoom(event.target.value));
$('#image-zoom').addEventListener('dblclick', () => setPreviewZoom(100));
$('#image-viewer-image').addEventListener('load', fitPreviewImage);
window.addEventListener('resize', () => { if (imageDialog.open) fitPreviewImage(); });

$('#output-grid').addEventListener('keydown', (event) => {
  if (event.target.closest('a, button')) return;
  if (!['Enter', ' '].includes(event.key)) return;
  event.preventDefault();
  const card = event.target.closest('.output-card');
  if (card) openPreview(Number(card.dataset.outputIndex));
});

$('#image-viewer-delete').addEventListener('click', () => deleteOutput(state.previewIndex));
$('#image-previous').addEventListener('click', () => movePreview(-1));
$('#image-next').addEventListener('click', () => movePreview(1));
$('.image-viewer-close').addEventListener('click', () => imageDialog.close());
$('.image-stage').addEventListener('click', (event) => {
  if (event.target.classList.contains('image-stage')) imageDialog.close();
});
imageDialog.addEventListener('keydown', (event) => {
  if (event.key === 'ArrowLeft') { event.preventDefault(); movePreview(-1); }
  if (event.key === 'ArrowRight') { event.preventDefault(); movePreview(1); }
  if (['Delete', 'Backspace'].includes(event.key) && !event.repeat) {
    event.preventDefault();
    deleteOutput(state.previewIndex);
  }
});

let previewPointerX = null;
$('.image-stage').addEventListener('pointerdown', (event) => { previewPointerX = event.clientX; });
$('.image-stage').addEventListener('pointerup', (event) => {
  if (previewPointerX === null) return;
  const distance = event.clientX - previewPointerX;
  previewPointerX = null;
  if (Math.abs(distance) > 55) movePreview(distance > 0 ? -1 : 1);
});

function directorShotButton(shot) {
  const active = shot.number === state.directorShot ? 'active' : '';
  const stage = shot.stage.plateau_kind || shot.stage.level;
  return `<button class="director-shot ${active}" data-director-shot="${shot.number}">
    <i>${String(shot.number).padStart(2, '0')}</i>
    <span><strong>Set ${shot.photoshoot_index + 1} · Shot ${shot.shot_index + 1}</strong><span>${escapeHtml(shot.action.prompt)}</span></span>
    <em class="${shot.stage.manual ? 'manual' : ''}" title="${shot.stage.manual ? 'Stage selected manually' : 'Automatic stage'}">${shot.stage.manual ? 'M · ' : ''}${escapeHtml(stage.replaceAll('_', ' '))}</em>
  </button>`;
}

function directorField(field) {
  const current = field.options.find((option) => option.id === field.value);
  const customOption = field.custom
    ? `<option value="__director_custom__" selected>${escapeHtml(field.custom)}</option>`
    : '';
  const optionHtml = customOption + field.options.map((option) => {
    const suffix = option.default ? ' · Default' : '';
    const label = option.label ? `${option.label[0].toUpperCase()}${option.label.slice(1)}` : '';
    return `<option value="${escapeHtml(option.id)}" ${!field.custom && option.id === field.value ? 'selected' : ''} title="${escapeHtml(option.prompt)}">${escapeHtml(label + suffix)}</option>`;
  }).join('');
  const fieldNote = field.key === 'shot.stage'
    ? `${field.compatibility?.poses ?? 0} poses · ${field.compatibility?.actions ?? 0} actions · ${field.compatibility?.expressions ?? 0} expressions`
    : (current?.default ? '<span class="default-mark">Database default</span>' : escapeHtml(current?.prompt || current?.label || ''));
  const search = [field.label, field.custom, ...field.options.map((option) => `${option.label} ${option.prompt}`)].join(" ").toLowerCase();
  return `<div class="director-field" data-director-search="${escapeHtml(search)}">
    <div class="director-field-head"><label for="director-${escapeHtml(field.key)}">${escapeHtml(field.label)}</label><span class="director-scope">${field.scope === 'set' ? 'Entire set' : 'This shot'}</span></div>
    <select id="director-${escapeHtml(field.key)}" data-director-field="${escapeHtml(field.key)}">${optionHtml}</select>
    <div class="director-field-footer"><p class="director-field-note">${field.custom ? '' : fieldNote}</p><button type="button" class="director-custom-button ${field.custom ? "active" : ""}" data-director-custom="${escapeHtml(field.key)}">${field.custom ? "Edit custom" : "+ Custom"}</button></div>
  </div>`;
}

function renderDirector() {
  const workspace = $('#director-workspace');
  const empty = $('#director-empty');
  if (!state.storyboard || !state.director) {
    workspace.classList.add('hidden');
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');
  workspace.classList.remove('hidden');
  $('#director-shot-list').innerHTML = state.storyboard.shots.map(directorShotButton).join('');
  const sets = new Set(state.storyboard.shots.map((shot) => shot.photoshoot_index)).size;
  $('#director-set-count').textContent = `${sets} set${sets === 1 ? '' : 's'}`;
  const data = state.director;
  const shot = data.summary;
  $('#director-title').textContent = `Set ${shot.photoshoot_index + 1} · Shot ${shot.shot_index + 1}`;
  $('#director-subtitle').textContent = 'SET changes propagate across the photoshoot; direction changes affect this shot only.';
  $('#director-summary').innerHTML = [
    ['Subject', shot.subject], ['Wardrobe', shot.wardrobe],
    ['Location', shot.location], ['Treatment', shot.photography],
    ['Variation', `${shot.seed_manual ? 'Custom · ' : ''}${shot.inference_seed}`],
  ].map(([label, value]) => `<div class="director-summary-${label.toLowerCase()}"><span>${label}</span><strong>${escapeHtml(value)}</strong></div>`).join('');
  const icons = { identity: 'ID', face: '◉', hair: '≈', body: '◇', styling: '✦', wardrobe: '◫', scene: '⌂', camera: '⌾', direction: '↗' };
  $('#director-groups').innerHTML = data.groups.map((group) => `
    <details class="director-group" data-director-group="${escapeHtml(group.id)}" ${state.directorOpenGroup === group.id ? 'open' : ''}>
      <summary><span class="director-group-title"><i>${icons[group.id] || '•'}</i>${escapeHtml(group.label)}</span><small>${group.fields.length} settings · ${['direction', 'camera'].includes(group.id) ? 'shot' : 'set'}</small></summary>
      <div class="director-fields">${group.fields.map(directorField).join('')}</div>
    </details>
  `).join('');
  filterDirector($('#director-search').value);
}

function filterDirector(query) {
  const normalized = String(query || '').trim().toLowerCase();
  let visible = 0;
  $$('.director-field').forEach((field) => {
    const show = !normalized || field.dataset.directorSearch.includes(normalized);
    field.classList.toggle('hidden', !show);
    if (show) visible += 1;
  });
  $$('[data-director-group]').forEach((group) => {
    const show = Boolean($('.director-field:not(.hidden)', group));
    group.classList.toggle('hidden', !show);
    if (normalized && show) group.open = true;
  });
  let none = $('.director-no-results');
  if (!visible && normalized) {
    if (!none) {
      none = document.createElement('div');
      none.className = 'director-no-results';
      $('#director-groups').append(none);
    }
    none.textContent = `No settings or presets match “${query}”.`;
  } else {
    none?.remove();
  }
}

async function loadDirector(number = state.directorShot) {
  if (!state.storyboard) {
    state.director = null;
    renderDirector();
    return;
  }
  state.directorShot = Math.min(Math.max(1, number), state.storyboard.total);
  $('#director-loading').classList.remove('hidden');
  $('#director-groups').classList.add('hidden');
  try {
    state.director = await api(`/api/storyboards/${state.storyboard.id}/director?shot=${state.directorShot}`);
    renderDirector();
  } catch (error) {
    state.director = null;
    renderDirector();
    toast('Director unavailable', error.message, 'error');
  } finally {
    $('#director-loading').classList.add('hidden');
    $('#director-groups').classList.remove('hidden');
  }
}

async function remixDirector(target, button) {
  if (!state.storyboard || !state.director) return;
  const buttons = $$('[data-director-remix]');
  buttons.forEach((item) => { item.disabled = true; });
  try {
    state.director = await api(`/api/storyboards/${state.storyboard.id}/director`, {
      method: 'POST',
      body: JSON.stringify({ shot: state.directorShot, field: `remix.${target}`, value: '' }),
    });
    state.storyboard = await api(`/api/storyboards/${state.storyboard.id}`);
    renderStoryboard();
    renderDirector();
    toast('Remix complete', target === 'shot' ? 'This shot was redirected.' : `The set’s ${target} was refreshed.`, 'success');
  } catch (error) {
    toast('Could not remix', error.message, 'error');
  } finally {
    buttons.forEach((item) => { item.disabled = false; });
  }
}

function directorFieldByKey(key) {
  return state.director?.groups.flatMap((group) => group.fields).find((field) => field.key === key);
}

function openDirectorCustom(key) {
  const field = directorFieldByKey(key);
  if (!field) return;
  state.directorCustomField = key;
  $("#director-custom-title").textContent = field.label;
  $("#director-custom-scope").textContent = field.scope === "set"
    ? "Overrides this field across the entire set."
    : "Overrides this field only for this shot.";
  $("#director-custom-value").value = field.custom || "";
  $("#director-custom-clear").disabled = !field.custom;
  directorCustomDialog.showModal();
  $("#director-custom-value").focus();
}

async function saveDirectorCustom(clear = false) {
  const field = directorFieldByKey(state.directorCustomField);
  if (!field || !state.storyboard) return;
  const value = clear ? "" : $("#director-custom-value").value.trim();
  const button = clear ? $("#director-custom-clear") : $("#director-custom-apply");
  setBusy(button, true, clear ? "Clearing…" : "Applying…");
  try {
    state.director = await api(`/api/storyboards/${state.storyboard.id}/director`, {
      method: "POST",
      body: JSON.stringify({ shot: state.directorShot, field: field.key, custom_value: value }),
    });
    state.storyboard = await api(`/api/storyboards/${state.storyboard.id}`);
    directorCustomDialog.close();
    renderStoryboard();
    renderDirector();
    toast(value ? "Custom direction applied" : "Custom direction cleared", value ? (field.scope === "set" ? "The complete set was updated." : "This shot was updated.") : "The database preset is active again.", "success");
  } catch (error) {
    toast("Could not apply custom value", error.message, "error");
  } finally {
    setBusy(button, false);
  }
}

async function applyDirectorChange(select) {
  if (!state.storyboard || !state.director) return;
  const field = select.dataset.directorField;
  const card = select.closest('.director-field');
  const activeField = directorFieldByKey(field);
  const previous = activeField?.custom ? '__director_custom__' : activeField?.value;
  if (select.value === '__director_custom__') {
    openDirectorCustom(field);
    return;
  }
  select.disabled = true;
  card.classList.add('changed');
  try {
    state.director = await api(`/api/storyboards/${state.storyboard.id}/director`, {
      method: 'POST',
      body: JSON.stringify({
        shot: state.directorShot,
        field,
        value: select.value,
        clear_custom: Boolean(activeField?.custom),
      }),
    });
    state.storyboard = await api(`/api/storyboards/${state.storyboard.id}`);
    renderStoryboard();
    renderDirector();
    toast('Direction applied', field.startsWith('shot.') ? 'This shot was updated.' : 'The complete set was updated.', 'success');
  } catch (error) {
    select.value = previous ?? '';
    card.classList.remove('changed');
    select.disabled = false;
    toast('Choice is incompatible', error.message, 'error');
  }
}

async function closeShotPreview() {
  const preview = state.previewDisplayed;
  state.previewDisplayed = null;
  $('#shot-preview-window').classList.add('hidden');
  $('#shot-preview-image').removeAttribute('src');
  if (!preview?.id) return;
  try {
    await api(`/api/previews/${preview.id}`, { method: 'DELETE' });
  } catch (error) {
    toast('Could not discard preview', error.message, 'error');
  }
}

async function openShotPreview(preview) {
  const windowElement = $('#shot-preview-window');
  const previous = state.previewDisplayed;
  state.previewDisplayed = preview;
  $('#shot-preview-title').textContent = `Shot ${preview.shot} preview`;
  $('#shot-preview-image').src = `${preview.image_url}?v=${Date.now()}`;
  windowElement.classList.remove('hidden');
  const rect = windowElement.getBoundingClientRect();
  windowElement.style.left = `${rect.left}px`;
  windowElement.style.top = `${rect.top}px`;
  windowElement.style.right = 'auto';
  windowElement.style.bottom = 'auto';
  clampShotPreviewWindow();
  if (previous?.id && previous.id !== preview.id) {
    try { await api(`/api/previews/${previous.id}`, { method: 'DELETE' }); } catch { /* already expired */ }
  }
}

function setPreviewBusy(button, busy) {
  if (button?.id === 'shot-preview-refresh') {
    button.disabled = busy;
    button.classList.toggle('spinning', busy);
    return;
  }
  setBusy(button, busy, busy ? 'Rendering…' : undefined);
}

async function pollShotPreview(button) {
  if (!state.previewJob) return;
  try {
    state.previewJob = await api(`/api/previews/${state.previewJob.id}`);
    renderLogger();
    if (['queued', 'running'].includes(state.previewJob.status)) {
      state.previewJobTimer = setTimeout(() => pollShotPreview(button), 1000);
      return;
    }
    setPreviewBusy(button, false);
    if (state.previewJob.status === 'completed') {
      await openShotPreview(state.previewJob);
      toast('Shot preview ready', 'Temporary preview rendered without adding it to Outputs.', 'success');
    } else {
      const message = state.previewJob.error || 'Preview rendering failed';
      const failedId = state.previewJob.id;
      state.previewJob = null;
      await api(`/api/previews/${failedId}`, { method: 'DELETE' });
      toast('Preview failed', message, 'error');
    }
  } catch (error) {
    toast('Preview status lost', error.message, 'error');
    state.previewJobTimer = setTimeout(() => pollShotPreview(button), 3000);
  }
}

async function startShotPreview(number, button) {
  if (!state.storyboard) return;
  if (isRenderActive()) {
    toast('Preview unavailable', 'Wait for the active storyboard render to finish or cancel it first.', 'error');
    return;
  }
  if (state.previewJob && ['queued', 'running'].includes(state.previewJob.status)) {
    toast('Preview already active', 'Wait for the current shot preview to finish.');
    return;
  }
  setPreviewBusy(button, true);
  try {
    state.previewJob = await api('/api/previews', {
      method: 'POST',
      body: JSON.stringify({
        storyboard_id: state.storyboard.id,
        shot: number,
        fast: true,
      }),
    });
    renderLogger();
    toast('Preview queued', `Rendering shot ${number} with the preview workflow.`);
    pollShotPreview(button);
  } catch (error) {
    setPreviewBusy(button, false);
    toast('Could not start preview', error.message, 'error');
  }
}

function clampShotPreviewWindow() {
  const preview = $('#shot-preview-window');
  if (preview.classList.contains('hidden') || !preview.style.left) return;
  const rect = preview.getBoundingClientRect();
  preview.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - rect.width - 8))}px`;
  preview.style.top = `${Math.max(8, Math.min(rect.top, window.innerHeight - rect.height - 8))}px`;
}

function switchView(name) {
  $$('.view').forEach((view) => view.classList.toggle('active', view.id === `${name}-view`));
  $$('.nav-item').forEach((item) => item.classList.toggle('active', item.dataset.view === name));
  $('#view-title').textContent = {
    studio: 'Production Studio', director: 'Director’s Desk', outputs: 'Output Gallery', logger: 'Render Logger',
  }[name] || 'Project Valhalla';
  if (name === 'director') loadDirector();
  if (name === 'logger') renderLogger();
}

async function captureWorkflow() {
  const button = $('#capture-confirm');
  setBusy(button, true, 'Capturing…');
  try {
    const result = await api('/api/workflow/capture', {
      method: 'POST',
      body: JSON.stringify({ force: $('#capture-force').checked }),
    });
    $('#capture-dialog').close();
    toast('Workflow captured', result.message, 'success');
    refreshStatus();
  } catch (error) {
    toast('Capture failed', error.message, 'error');
  } finally {
    setBusy(button, false);
  }
}

form.addEventListener('submit', resolveStoryboard);
form.addEventListener('input', syncForm);
form.addEventListener('input', scheduleSeedResolve);
$('#theme-button').addEventListener('click', cycleTheme);
$('#refresh-status').addEventListener('click', () => refreshStatus(true));
$('#reset-config').addEventListener('click', () => { form.reset(); syncForm(); toast('Setup reset', 'Default production settings restored.'); });
$('#randomize-storyboard-seed').addEventListener('click', () => randomizeSeedField('prompt_seed'));
$('#randomize-variation-seed').addEventListener('click', () => randomizeSeedField('inference_seed'));
$('#reroll-all').addEventListener('click', resolveStoryboard);
$('#export-storyboard').addEventListener('click', exportStoryboard);
$('#import-storyboard').addEventListener('click', () => $('#storyboard-file').click());
$('#storyboard-file').addEventListener('change', importStoryboard);
$$('[data-render-action]').forEach((button) => button.addEventListener('click', startGeneration));
$('#director-open-studio').addEventListener('click', () => switchView('studio'));
$('#director-search').addEventListener('input', (event) => filterDirector(event.target.value));
$('.director-quick-actions').addEventListener('click', (event) => {
  const previewButton = event.target.closest('#director-preview-shot');
  if (previewButton) {
    startShotPreview(state.directorShot, previewButton);
    return;
  }
  const variationButton = event.target.closest('#director-randomize-seed');
  if (variationButton) {
    randomizeShotSeed(state.directorShot, variationButton);
    return;
  }
  const button = event.target.closest('[data-director-remix]');
  if (button) remixDirector(button.dataset.directorRemix, button);
});
$('#director-shot-list').addEventListener('click', (event) => {
  const button = event.target.closest('[data-director-shot]');
  if (button) loadDirector(Number(button.dataset.directorShot));
});
$("#director-groups").addEventListener("click", (event) => {
  const customButton = event.target.closest("[data-director-custom]");
  if (customButton) {
    openDirectorCustom(customButton.dataset.directorCustom);
    return;
  }
  const summary = event.target.closest('.director-group > summary');
  if (!summary) return;
  const selected = summary.parentElement;
  if (selected.open) {
    state.directorOpenGroup = null;
    return;
  }
  state.directorOpenGroup = selected.dataset.directorGroup;
  $$('.director-group', $('#director-groups')).forEach((group) => {
    if (group !== selected) group.open = false;
  });
});
$('#director-groups').addEventListener('change', (event) => {
  const select = event.target.closest('[data-director-field]');
  if (select) applyDirectorChange(select);
});
$('#cancel-job').addEventListener('click', async () => {
  if (!state.job) return;
  try {
    state.job = await api(`/api/jobs/${state.job.id}/cancel`, { method: 'POST', body: '{}' });
    showJob();
  } catch (error) { toast('Could not cancel', error.message, 'error'); }
});

shotGrid.addEventListener('click', (event) => {
  const button = event.target.closest('button');
  if (!button) return;
  const number = Number(button.closest('.shot-card').dataset.shot);
  const shot = state.storyboard.shots.find((item) => item.number === number);
  if (button.dataset.action === 'inspect') openPrompt(shot);
  if (button.dataset.action === 'director') {
    state.directorShot = number;
    switchView('director');
  }
  if (button.dataset.action === 'preview') startShotPreview(number, button);
  if (button.dataset.action === 'render') startShotRender(number, button);
  if (button.dataset.action === 'variation') randomizeShotSeed(number, button);
  if (button.dataset.action === 'reroll') rerollShot(number, button);
});

$('#shot-preview-close').addEventListener('click', closeShotPreview);
$('#shot-preview-refresh').addEventListener('click', (event) => {
  const directorActive = $('#director-view').classList.contains('active');
  const shot = directorActive
    ? state.directorShot
    : (state.previewDisplayed?.shot || state.previewJob?.shot);
  if (shot) startShotPreview(shot, event.currentTarget);
});
$('#shot-preview-image').addEventListener('error', () => {
  toast('Could not display preview', 'The temporary preview image is no longer available.', 'error');
});
let previewDrag = null;
$('#shot-preview-drag-handle').addEventListener('pointerdown', (event) => {
  if (event.target.closest('button')) return;
  const preview = $('#shot-preview-window');
  const rect = preview.getBoundingClientRect();
  preview.style.left = `${rect.left}px`;
  preview.style.top = `${rect.top}px`;
  preview.style.right = 'auto';
  preview.style.bottom = 'auto';
  previewDrag = { x: event.clientX, y: event.clientY, left: rect.left, top: rect.top };
  event.currentTarget.setPointerCapture(event.pointerId);
});
$('#shot-preview-drag-handle').addEventListener('pointermove', (event) => {
  if (!previewDrag) return;
  const preview = $('#shot-preview-window');
  const maxLeft = Math.max(8, window.innerWidth - preview.offsetWidth - 8);
  const maxTop = Math.max(8, window.innerHeight - preview.offsetHeight - 8);
  preview.style.left = `${Math.max(8, Math.min(maxLeft, previewDrag.left + event.clientX - previewDrag.x))}px`;
  preview.style.top = `${Math.max(8, Math.min(maxTop, previewDrag.top + event.clientY - previewDrag.y))}px`;
});
$('#shot-preview-drag-handle').addEventListener('pointerup', () => { previewDrag = null; });
$('#shot-preview-drag-handle').addEventListener('pointercancel', () => { previewDrag = null; });
window.addEventListener('resize', clampShotPreviewWindow);
if ('ResizeObserver' in window) {
  new ResizeObserver(clampShotPreviewWindow).observe($('#shot-preview-window'));
}
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && !$('#shot-preview-window').classList.contains('hidden')) {
    closeShotPreview();
  }
});

$$('.prompt-tabs button').forEach((button) => button.addEventListener('click', () => {
  state.promptTab = button.dataset.prompt;
  $$('.prompt-tabs button').forEach((item) => item.classList.toggle('active', item === button));
  updatePromptContent();
}));
$('#delete-all-outputs').addEventListener('click', deleteAllOutputs);
$("#director-custom-apply").addEventListener("click", () => saveDirectorCustom(false));
$("#director-custom-clear").addEventListener("click", () => saveDirectorCustom(true));
$$(".director-custom-close").forEach((button) => button.addEventListener("click", () => directorCustomDialog.close()));
directorCustomDialog.addEventListener("cancel", () => { state.directorCustomField = null; });
directorCustomDialog.addEventListener("close", () => { state.directorCustomField = null; });
$("#delete-dialog-confirm").addEventListener('click', () => resolveDeletion(true));
$$('.delete-dialog-cancel').forEach((button) => button.addEventListener('click', () => resolveDeletion(false)));
deleteDialog.addEventListener('cancel', (event) => {
  event.preventDefault();
  resolveDeletion(false);
});
$$('.dialog-close').forEach((button) => button.addEventListener('click', () => promptDialog.close()));
$('#copy-prompt').addEventListener('click', async () => {
  await navigator.clipboard.writeText($('#prompt-content').textContent);
  toast('Copied', 'Prompt copied to clipboard.', 'success');
});

$('#capture-button').addEventListener('click', () => $('#capture-dialog').showModal());
$$('.capture-close').forEach((button) => button.addEventListener('click', () => $('#capture-dialog').close()));
$('#capture-confirm').addEventListener('click', captureWorkflow);
$$('.nav-item').forEach((button) => button.addEventListener('click', () => switchView(button.dataset.view)));
$('#logger-view').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-copy-log]');
  if (!button || !state.job?.current_prompt) return;
  const key = button.dataset.copyLog;
  try {
    await navigator.clipboard.writeText(state.job.current_prompt[key] || '');
    toast('Prompt copied', `${key[0].toUpperCase()}${key.slice(1)} prompt copied.`, 'success');
  } catch (error) {
    toast('Could not copy prompt', error.message, 'error');
  }
});
$('#clear-logger').addEventListener('click', async () => {
  const button = $('#clear-logger');
  setBusy(button, true, 'Clearing…');
  try {
    const result = await api('/api/logger', { method: 'DELETE' });
    state.job = null;
    state.previewJob = null;
    renderLogger();
    toast('Logger cleared', `${result.cleared} log source${result.cleared === 1 ? '' : 's'} removed.`, 'success');
  } catch (error) {
    toast('Could not clear logger', error.message, 'error');
  } finally {
    setBusy(button, false);
  }
});

applyTheme();
syncForm();
syncPreviewScaleControls();
refreshStatus();
restoreApplication();
