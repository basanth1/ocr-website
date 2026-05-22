/* static/js/app.js — OCR Pipeline Studio frontend */

/* ─── State ─────────────────────────────────────── */
let pdfFile    = null;
let ocrPages   = null;   // raw pages array
let secPages   = null;   // pages to use in section builder
let secData    = null;   // built sections
let ocrFilename = null;
let secFilenames = {};   // {json:'…', md:'…'}

let currentSrc    = 'upload';
let currentMethod = 'regex';
let currentFmt    = 'json';

/* ─── Server health ─────────────────────────────── */
async function checkHealth() {
  try {
    const r = await fetch('/api/health');
    if (r.ok) setBadge('● online', 'ok');
    else      setBadge('● server error', 'error');
  } catch {
    setBadge('● offline', 'error');
  }
}
function setBadge(text, cls) {
  const el = document.getElementById('server-badge');
  el.textContent = text;
  el.className   = 'badge ' + cls;
}
checkHealth();

/* ─── Tab switching ─────────────────────────────── */
function switchTab(id) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('panel-'  + id).classList.add('active');
  document.getElementById('tab-'    + id).classList.add('active');
}

/* ─── Drag & drop helpers ───────────────────────── */
function dzOver(e, id)  { e.preventDefault(); document.getElementById(id).classList.add('over'); }
function dzLeave(id)    { document.getElementById(id).classList.remove('over'); }
function dzDrop(e, id, handler) {
  e.preventDefault();
  document.getElementById(id).classList.remove('over');
  const file = e.dataTransfer.files[0];
  if (file) handler(file);
}

/* ─── PDF tab ───────────────────────────────────── */
function onPdfChange(e)    { handlePdfFile(e.target.files[0]); }
function handlePdfDrop(f)  { handlePdfFile(f); }

function handlePdfFile(file) {
  if (!file || !file.name.endsWith('.pdf')) { alert('Please select a PDF file.'); return; }
  pdfFile = file;
  showChip('pdf-chip', 'pdf-chip-name', 'pdf-chip-size', file);
  document.getElementById('ocr-run-btn').disabled = false;
  if (!document.getElementById('ocr-prefix').value)
    document.getElementById('ocr-prefix').value = file.name.replace(/\.pdf$/i, '');
}

function clearPdf() {
  pdfFile = null;
  document.getElementById('pdf-input').value = '';
  hideChip('pdf-chip');
  document.getElementById('ocr-run-btn').disabled = true;
}

/* ─── Run OCR (POST to /api/ocr) ─────────────────── */
async function runOCR() {
  if (!pdfFile) return;

  resetResultPanel('ocr-result');
  showProgress('ocr-progress');
  clearLog('ocr-log');

  const log  = (m, t='info') => appendLog('ocr-log', m, t);
  const prog = (p, l)        => setProgress('ocr-prog-fill', 'ocr-prog-pct', 'ocr-prog-label', p, l);

  prog(5, 'Uploading PDF…');
  log(`Uploading: ${pdfFile.name} (${fmtSize(pdfFile.size)})`);

  const fd = new FormData();
  fd.append('pdf',            pdfFile);
  fd.append('dpi',            document.getElementById('ocr-dpi').value);
  fd.append('lang',           document.getElementById('ocr-lang').value);
  fd.append('angle_cls',      document.getElementById('ocr-angle').checked);
  fd.append('horiz_tables',   document.getElementById('ocr-horiz').checked);
  fd.append('extract_tables', document.getElementById('ocr-tables').checked);
  fd.append('y_threshold',    document.getElementById('ocr-y').value);
  fd.append('stem',           document.getElementById('ocr-prefix').value || 'document');

  prog(15, 'Processing pages (this may take a while)…');
  log('Sent to server. Running PaddleOCR…', 'warn');

  try {
    const res  = await fetch('/api/ocr', { method: 'POST', body: fd });
    const data = await res.json();

    if (!res.ok || data.error) {
      log('Error: ' + (data.error || res.statusText), 'err');
      prog(0, 'Failed');
      return;
    }

    prog(95, 'Finalising…');
    log(`Pages: ${data.pages} | Tables: ${data.total_tables} | Lines: ${data.total_lines}`, 'ok');
    log(`Saved → ${data.filename}`, 'ok');
    prog(100, 'Done');

    ocrPages    = data.data;
    ocrFilename = data.filename;

    document.getElementById('s-pages').textContent  = data.pages;
    document.getElementById('s-tables').textContent = data.total_tables;
    document.getElementById('s-lines').textContent  = data.total_lines;
    document.getElementById('ocr-result-meta').textContent =
      `${data.filename}  ·  ${fmtSize(JSON.stringify(data.data).length)}`;
    document.getElementById('ocr-preview').textContent =
      JSON.stringify(data.data.slice(0, 2), null, 2) + '\n\n… (truncated — download for full output)';

    showResult('ocr-result');

  } catch (err) {
    log('Network error: ' + err.message, 'err');
  }
}

function downloadOcr() {
  if (ocrFilename) window.location = `/api/download/${ocrFilename}`;
}

function sendToSection() {
  if (!ocrPages) return;
  secPages = ocrPages;
  switchTab('section');
  setSrc('pipe');
  document.getElementById('pipe-status').textContent =
    `✅ ${ocrPages.length} pages piped from OCR tab.`;
  document.getElementById('pipe-status').className = 'info-box ok';
  document.getElementById('sec-run-btn').disabled = false;
}

function resetOCR() {
  clearPdf();
  hideProgress('ocr-progress');
  resetResultPanel('ocr-result');
  clearLog('ocr-log');
  ocrPages = null;
}

/* ─── Section Builder ───────────────────────────── */
function onJsonChange(e)   { handleJsonFile(e.target.files[0]); }
function handleJsonDrop(f) { handleJsonFile(f); }

function handleJsonFile(file) {
  if (!file || !file.name.endsWith('.json')) { alert('Please select a JSON file.'); return; }
  const reader = new FileReader();
  reader.onload = e => {
    try {
      secPages = JSON.parse(e.target.result);
      showChip('json-chip', 'json-chip-name', 'json-chip-size', file);
      document.getElementById('sec-run-btn').disabled = false;
      appendLog('sec-log', `✅ Loaded ${secPages.length} pages from ${file.name}`, 'ok');
    } catch(ex) {
      alert('Invalid JSON: ' + ex.message);
    }
  };
  reader.readAsText(file);
}

function clearJson() {
  secPages = null;
  document.getElementById('json-input').value = '';
  hideChip('json-chip');
  document.getElementById('sec-run-btn').disabled = true;
}

function setSrc(s) {
  currentSrc = s;
  document.getElementById('src-upload-btn').classList.toggle('active', s === 'upload');
  document.getElementById('src-pipe-btn').classList.toggle('active',   s === 'pipe');
  document.getElementById('src-upload-area').style.display = s === 'upload' ? '' : 'none';
  document.getElementById('src-pipe-area').style.display   = s === 'pipe'   ? '' : 'none';
  if (s === 'pipe' && secPages)
    document.getElementById('sec-run-btn').disabled = false;
}

function setMethod(m) {
  currentMethod = m;
  document.getElementById('meth-regex').classList.toggle('active', m === 'regex');
  document.getElementById('meth-llm').classList.toggle('active',   m === 'llm');
  document.getElementById('llm-options').style.display = m === 'llm' ? '' : 'none';
}

function setFmt(f) {
  currentFmt = f;
  ['json', 'md', 'both'].forEach(x =>
    document.getElementById('fmt-' + x).classList.toggle('active', x === f));
}

/* ─── Run Section Builder (POST /api/sections) ─── */
async function runSections() {
  if (!secPages) { alert('No OCR data loaded.'); return; }

  resetResultPanel('sec-result');
  showProgress('sec-progress');
  clearLog('sec-log');

  const log  = (m, t='info') => appendLog('sec-log', m, t);
  const prog = (p, l)        => setProgress('sec-prog-fill', 'sec-prog-pct', 'sec-prog-label', p, l);

  prog(5, 'Sending data to server…');
  log(`Method: ${currentMethod.toUpperCase()} | Format: ${currentFmt.toUpperCase()}`);
  log(`Pages: ${secPages.length}`);

  const payload = {
    pages:         secPages,
    method:        currentMethod,
    output_format: currentFmt,
    pattern:       document.getElementById('sec-pattern').value.trim(),
    toc_end:       parseInt(document.getElementById('toc-end').value) || 3,
    groq_api_key:  document.getElementById('groq-key').value.trim(),
    groq_model:    document.getElementById('groq-model').value,
    llm_temperature: parseFloat(document.getElementById('llm-temp').value),
    extra_prompt:  document.getElementById('llm-extra').value.trim(),
    stem:          'sections',
  };

  if (currentMethod === 'llm' && !payload.groq_api_key) {
    alert('Please enter your Groq API key for LLM mode.');
    hideProgress('sec-progress');
    return;
  }

  prog(20, currentMethod === 'llm' ? 'Calling LLM…' : 'Running regex extraction…');

  try {
    const res  = await fetch('/api/sections', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });
    const data = await res.json();

    if (!res.ok || data.error) {
      log('Error: ' + (data.error || res.statusText), 'err');
      prog(0, 'Failed');
      return;
    }

    prog(95, 'Writing output files…');
    log(`Sections: ${data.section_count} | Matched: ${data.matched} | Tables: ${data.total_tables}`, 'ok');
    Object.entries(data.downloads || {}).forEach(([fmt, fn]) => log(`Saved ${fmt.toUpperCase()} → ${fn}`, 'ok'));
    prog(100, 'Done');

    secData    = data.sections;
    secFilenames = data.downloads || {};

    document.getElementById('ss-count').textContent   = data.section_count;
    document.getElementById('ss-matched').textContent = data.matched;
    document.getElementById('ss-tables').textContent  = data.total_tables;
    document.getElementById('sec-result-meta').textContent =
      `${currentMethod.toUpperCase()} · ${currentFmt.toUpperCase()} · ${new Date().toLocaleTimeString()}`;

    renderSectionTree(data.sections);
    renderPreviews(data.sections, data.downloads);
    renderDownloadRow(data.downloads);
    showResult('sec-result');

  } catch (err) {
    log('Network error: ' + err.message, 'err');
  }
}

function renderSectionTree(sections) {
  const ul = document.getElementById('sec-tree');
  ul.innerHTML = '';
  for (const sec of sections) {
    const li = document.createElement('li');
    li.className = 'sec-item';
    const badge = sec.tables.length
      ? `<span class="sec-tbadge">${sec.tables.length} table${sec.tables.length > 1 ? 's' : ''}</span>` : '';
    li.innerHTML = `
      <span class="sec-num">${esc(sec.section_number)}</span>
      <div class="sec-info">
        <div class="sec-title">${esc(sec.title)}</div>
        <div class="sec-pages">Pages ${sec.start_page} – ${sec.end_page}</div>
        <div class="sec-preview">${esc(sec.content.slice(0, 180))}</div>
      </div>
      ${badge}`;
    ul.appendChild(li);
  }
}

function renderPreviews(sections, downloads) {
  const wrap = document.getElementById('sec-previews');
  wrap.innerHTML = '';
  if (downloads.json) {
    const d = document.createElement('details');
    d.innerHTML = `<summary>JSON Preview (first 2 sections)</summary>
      <div class="detail-body">${esc(JSON.stringify(sections.slice(0,2), null, 2))}</div>`;
    wrap.appendChild(d);
  }
  if (downloads.md) {
    const md = buildMarkdown(sections);
    const d  = document.createElement('details');
    d.innerHTML = `<summary>Markdown Preview</summary>
      <div class="detail-body">${esc(md.slice(0, 900))}\n…</div>`;
    wrap.appendChild(d);
  }
}

function renderDownloadRow(downloads) {
  const row = document.getElementById('sec-dl-row');
  row.innerHTML = '';
  if (downloads.json) {
    const b = document.createElement('button');
    b.className = 'btn btn-primary btn-sm';
    b.textContent = '⬇ Download JSON';
    b.onclick = () => window.location = `/api/download/${downloads.json}`;
    row.appendChild(b);
  }
  if (downloads.md) {
    const b = document.createElement('button');
    b.className = 'btn btn-ghost btn-sm';
    b.textContent = '⬇ Download Markdown';
    b.onclick = () => window.location = `/api/download/${downloads.md}`;
    row.appendChild(b);
  }
}

function buildMarkdown(sections) {
  return sections.map(s => {
    const lvl = s.section_number === '0' ? 1 : s.section_number.split('.').length;
    const hd  = '#'.repeat(lvl) + (s.section_number === '0' ? ' FRONT MATTER' : ` ${s.section_number} ${s.title}`);
    return `${hd}\n*Page Range: ${s.start_page} – ${s.end_page}*\n\n${s.content}\n\n---\n`;
  }).join('\n');
}

function resetSection() {
  clearJson();
  hideProgress('sec-progress');
  resetResultPanel('sec-result');
  clearLog('sec-log');
  secData = null; secFilenames = {};
}

/* ─── UI helpers ─────────────────────────────────── */
function showChip(chipId, nameId, sizeId, file) {
  document.getElementById(chipId).classList.add('show');
  document.getElementById(nameId).textContent = file.name;
  document.getElementById(sizeId).textContent = fmtSize(file.size);
}
function hideChip(chipId) { document.getElementById(chipId).classList.remove('show'); }

function showProgress(id)   { document.getElementById(id).classList.add('show'); }
function hideProgress(id)   { document.getElementById(id).classList.remove('show'); }
function showResult(id)     { document.getElementById(id).classList.add('show'); }
function resetResultPanel(id) {
  const el = document.getElementById(id);
  el.classList.remove('show');
}

function appendLog(boxId, msg, type = 'info') {
  const box  = document.getElementById(boxId);
  const line = document.createElement('div');
  line.className = 'log-line ' + type;
  const ts = new Date().toLocaleTimeString('en-US', { hour12: false });
  line.textContent = `[${ts}]  ${msg}`;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}
function clearLog(id) { document.getElementById(id).innerHTML = ''; }

function setProgress(fillId, pctId, labelId, pct, label) {
  document.getElementById(fillId).style.width    = pct + '%';
  document.getElementById(pctId).textContent     = pct + '%';
  if (label) document.getElementById(labelId).textContent = label;
}

function fmtSize(bytes) {
  if (bytes < 1024)    return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}

function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}
