'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  storyboard: null,
  job: null,
  jobTimer: null,
  outputs: [],
  previewIndex: 0,
  previewZoom: Number(sessionStorage.getItem('valhalla-preview-zoom')) || 100,
  previewFit: sessionStorage.getItem('valhalla-preview-fit') === 'true',
  deleteResolver: null,
  promptShot: null,
  promptTab: 'positive',
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
const promptDialog = $('#prompt-dialog');

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
  item.className = `toast ${type}`;
  item.innerHTML = `<strong>${escapeHtml(title)}</strong>${escapeHtml(message)}`;
  $('#toast-region').append(item);
  setTimeout(() => item.remove(), 4800);
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
    fast: form.elements.fast.checked,
  };
}

async function resolveStoryboard(event) {
  if (event?.preventDefault) event.preventDefault();
  const button = $('#resolve-button');
  setBusy(button, true, 'Resolving…');
  emptyState.classList.add('hidden');
  shotGrid.classList.add('hidden');
  storyboardActions.classList.add('hidden');
  storyboardMeta.classList.add('hidden');
  loadingState.classList.remove('hidden');
  try {
    state.storyboard = await api('/api/storyboards', { method: 'POST', body: JSON.stringify(configPayload()) });
    renderStoryboard();
    toast('Storyboard ready', `${state.storyboard.total} compatible shots resolved.`, 'success');
  } catch (error) {
    emptyState.classList.remove('hidden');
    toast('Could not resolve storyboard', error.message, 'error');
  } finally {
    loadingState.classList.add('hidden');
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
        <span class="stage-badge ${explicit}">${escapeHtml(stage.replaceAll('_', ' '))}</span>
      </div>
      <div class="shot-body">
        <div class="shot-set">Set ${shot.photoshoot_index + 1} · ${escapeHtml(shot.wardrobe)}</div>
        <div class="shot-detail"><span>Pose</span><strong title="${escapeHtml(shot.pose.prompt)}">${escapeHtml(shot.pose.prompt)}</strong></div>
        <div class="shot-detail"><span>Action</span><strong title="${escapeHtml(shot.action.prompt)}">${escapeHtml(shot.action.prompt)}</strong></div>
        <div class="shot-detail"><span>Mood</span><strong title="${escapeHtml(shot.expression.prompt)}">${escapeHtml(shot.expression.prompt)}</strong></div>
        <div class="shot-detail"><span>Surface</span><strong title="${escapeHtml(shot.surface)}">${escapeHtml(shot.surface)}</strong></div>
      </div>
      <div class="shot-footer">
        <button data-action="inspect">Inspect prompt</button>
        <button class="reroll" data-action="reroll">↻ Reroll</button>
      </div>
    </article>`;
}

function renderStoryboard() {
  const board = state.storyboard;
  if (!board) return;
  shotGrid.innerHTML = board.shots.map(shotCard).join('');
  $('#seed-pill').textContent = `Seed ${board.config.prompt_seed}`;
  const sets = board.config.mode === 'photoshoot' ? board.config.photoshoots : 'Independent';
  storyboardMeta.innerHTML = `<span>Mode <strong>${escapeHtml(board.config.mode)}</strong></span><span>Sets <strong>${sets}</strong></span><span>Shots <strong>${board.total}</strong></span><span>Content <strong>${board.config.xxx_only ? 'Full XXX' : 'Progressive'}</strong></span>`;
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
  const button = $('#generate-button');
  setBusy(button, true, 'Queueing…');
  try {
    state.job = await api('/api/jobs', {
      method: 'POST',
      body: JSON.stringify({ storyboard_id: state.storyboard.id, fast: form.elements.fast.checked }),
    });
    showJob();
    pollJob();
    toast('Production queued', `${state.job.total} images sent to the render pipeline.`, 'success');
  } catch (error) {
    toast('Could not start generation', error.message, 'error');
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

function showJob() {
  const job = state.job;
  if (!job) return;
  $('#job-dock').classList.remove('hidden');
  $('#job-percent').textContent = `${job.progress || 0}%`;
  $('#job-progress').style.width = `${job.progress || 0}%`;
  $('#job-detail').textContent = job.status === 'queued'
    ? 'Preparing workflow…'
    : `Image ${job.completed} of ${job.total} · ${formatTime(job.eta_seconds)}`;
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
  outputs.forEach((item) => { if (!names.has(item.name)) state.outputs.push(item); });
  renderOutputs();
}

function isRenderActive() {
  return state.job && ['queued', 'running'].includes(state.job.status);
}

function syncDeleteControls() {
  const disabled = Boolean(isRenderActive());
  $('#delete-all-outputs').classList.toggle('hidden', state.outputs.length === 0);
  $$('.output-delete, #delete-all-outputs, #image-viewer-delete').forEach((button) => {
    button.disabled = disabled;
    button.title = disabled ? 'Deletion is unavailable while rendering' : '';
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
  if (isRenderActive()) {
    toast('Deletion unavailable', 'Wait for the active render job to finish or cancel it first.', 'error');
    return;
  }
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
    if (!session.active_job) return;
    state.job = session.active_job;
    try {
      state.storyboard = await api(`/api/storyboards/${state.job.storyboard_id}`);
      restoreConfig(state.storyboard.config, state.job);
      renderStoryboard();
    } catch (error) {
      toast('Storyboard recovery limited', error.message, 'error');
    }
    showJob();
    pollJob();
    toast(
      'Active render restored',
      `${state.job.completed} of ${state.job.total} images completed.`,
      'success',
    );
  } catch (error) {
    toast('Could not restore render state', error.message, 'error');
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

function switchView(name) {
  $$('.view').forEach((view) => view.classList.toggle('active', view.id === `${name}-view`));
  $$('.nav-item').forEach((item) => item.classList.toggle('active', item.dataset.view === name));
  $('#view-title').textContent = name === 'studio' ? 'Production Studio' : 'Output Gallery';
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
$('#theme-button').addEventListener('click', cycleTheme);
$('#refresh-status').addEventListener('click', () => refreshStatus(true));
$('#reset-config').addEventListener('click', () => { form.reset(); syncForm(); toast('Setup reset', 'Default production settings restored.'); });
$('#reroll-all').addEventListener('click', resolveStoryboard);
$('#generate-button').addEventListener('click', startGeneration);
$('#cancel-job').addEventListener('click', async () => {
  if (!state.job) return;
  try {
    state.job = await api(`/api/jobs/${state.job.id}/cancel`, { method: 'POST', body: '{}' });
    $('#job-detail').textContent = 'Cancellation requested · current image will finish';
  } catch (error) { toast('Could not cancel', error.message, 'error'); }
});

shotGrid.addEventListener('click', (event) => {
  const button = event.target.closest('button');
  if (!button) return;
  const number = Number(button.closest('.shot-card').dataset.shot);
  const shot = state.storyboard.shots.find((item) => item.number === number);
  if (button.dataset.action === 'inspect') openPrompt(shot);
  if (button.dataset.action === 'reroll') rerollShot(number, button);
});

$$('.prompt-tabs button').forEach((button) => button.addEventListener('click', () => {
  state.promptTab = button.dataset.prompt;
  $$('.prompt-tabs button').forEach((item) => item.classList.toggle('active', item === button));
  updatePromptContent();
}));
$('#delete-all-outputs').addEventListener('click', deleteAllOutputs);
$('#delete-dialog-confirm').addEventListener('click', () => resolveDeletion(true));
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

applyTheme();
syncForm();
syncPreviewScaleControls();
refreshStatus();
restoreApplication();
