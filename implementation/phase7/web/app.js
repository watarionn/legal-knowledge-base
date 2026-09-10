const form = document.querySelector('#query-form');
const question = document.querySelector('#question');
const asOfDate = document.querySelector('#as-of-date');
const lawId = document.querySelector('#law-id');
const selectedLaw = document.querySelector('#selected-law');
const submitButton = document.querySelector('#submit-button');
const progress = document.querySelector('#progress');
const result = document.querySelector('#result');
const statusBanner = document.querySelector('#status-banner');
const candidatesPanel = document.querySelector('#law-candidates');
const answer = document.querySelector('#answer');
const evidenceList = document.querySelector('#evidence-list');
const evidenceCount = document.querySelector('#evidence-count');
const technical = document.querySelector('#technical');
const dialog = document.querySelector('#source-dialog');
const dialogClose = document.querySelector('#dialog-close');
const dialogPath = document.querySelector('#dialog-path');
const dialogText = document.querySelector('#dialog-text');
const dialogMeta = document.querySelector('#dialog-meta');

function setBusy(isBusy) {
  submitButton.disabled = isBusy;
  progress.textContent = isBusy ? '対象法令と根拠を確認しています…' : '';
}

function clearNode(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function valueOrDash(value) {
  return value === null || value === undefined || value === '' ? '—' : String(value);
}

function renderStatus(data) {
  const temporal = data.temporal_resolution;
  let text = '';
  if (data.status === 'law-candidates') {
    text = '対象法令を1件に確定していません。候補から選択してください。';
  } else if (data.status === 'law-not-found') {
    text = '質問から対象法令を確認できませんでした。法令名、略称、法令番号のいずれかを追加してください。';
  } else if (data.status === 'blocked-temporal') {
    text = `対象版を一意に確定できません。temporal status: ${valueOrDash(temporal?.status)}`;
  } else if (data.status === 'blocked-content') {
    text = '対象revisionは確認できましたが、本文が利用できません。別revisionでは代用しません。';
  } else if (data.status === 'no-hits') {
    text = '対象版は確定しましたが、提示できる検索根拠が見つかりませんでした。';
  } else if (data.status === 'answered') {
    text = `${data.effective_as_of_date} 時点の対象版を確定し、根拠付き回答を表示しています。`;
  } else if (data.status === 'evidence-only') {
    text = `${data.effective_as_of_date} 時点の対象版を確定しました。現在は生成回答を使わず、一次根拠を表示しています。`;
  } else {
    text = `status: ${valueOrDash(data.status)}`;
  }
  statusBanner.dataset.status = data.status || '';
  statusBanner.textContent = text;
}

function renderCandidates(data) {
  clearNode(candidatesPanel);
  const candidates = data.law_resolution?.candidates || [];
  if (!candidates.length || data.status !== 'law-candidates') {
    candidatesPanel.hidden = true;
    return;
  }
  const title = document.createElement('h2');
  title.textContent = '対象法令の候補';
  const note = document.createElement('p');
  note.textContent = '自動で1件に決めず、選択後に同じ質問を再実行します。';
  const list = document.createElement('div');
  list.className = 'candidate-list';
  for (const candidate of candidates) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'candidate-button';
    button.textContent = candidate.law_title || candidate.abbrev || candidate.law_num || candidate.law_id;
    button.addEventListener('click', () => {
      lawId.value = candidate.law_id;
      selectedLaw.textContent = `選択中: ${button.textContent} (${candidate.law_id})`;
      form.requestSubmit();
    });
    list.appendChild(button);
  }
  candidatesPanel.append(title, note, list);
  candidatesPanel.hidden = false;
}

function renderAnswer(data) {
  clearNode(answer);
  const payload = data.answer || {};
  if (payload.answer_text) {
    const p = document.createElement('p');
    p.textContent = payload.answer_text;
    answer.appendChild(p);
    for (const claim of payload.claims || []) {
      const item = document.createElement('p');
      item.textContent = `${claim.text} [${(claim.evidence_ids || []).join(', ')}]`;
      answer.appendChild(item);
    }
    return;
  }
  const p = document.createElement('p');
  p.className = 'answer-empty';
  if (data.status === 'evidence-only') {
    p.textContent = '生成回答プロバイダーはまだ接続していません。右側の根拠原文を直接確認できます。';
  } else {
    p.textContent = 'この状態では回答生成を実行していません。';
  }
  answer.appendChild(p);
}

function showSource(evidence) {
  dialogPath.textContent = evidence.display_path || '構造pathなし';
  dialogText.textContent = (evidence.source_nodes || [])
    .map(node => node.text_original || '')
    .filter(Boolean)
    .join('\n');
  clearNode(dialogMeta);
  const values = [
    ['Evidence ID', evidence.evidence_id],
    ['Law ID', evidence.law_id],
    ['Revision', evidence.law_revision_id],
    ['Source XML SHA-256', evidence.source_xml_sha256],
  ];
  for (const [key, value] of values) {
    const dt = document.createElement('dt');
    const dd = document.createElement('dd');
    dt.textContent = key;
    dd.textContent = valueOrDash(value);
    dialogMeta.append(dt, dd);
  }
  dialog.showModal();
}

function renderEvidence(data) {
  clearNode(evidenceList);
  const items = data.evidence || [];
  evidenceCount.textContent = String(items.length);
  if (!items.length) {
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = '表示できるEvidenceはありません。';
    evidenceList.appendChild(empty);
    return;
  }
  items.forEach((item, index) => {
    const card = document.createElement('article');
    card.className = 'evidence-card';
    card.id = `evidence-${index + 1}`;
    const heading = document.createElement('h3');
    heading.textContent = `E${index + 1} · ${item.display_path || '構造参照'}`;
    const quote = document.createElement('p');
    quote.className = 'quote';
    quote.textContent = item.quote || '原文テキストなし';
    const meta = document.createElement('p');
    meta.className = 'mono muted';
    meta.textContent = `revision ${item.law_revision_id} · SHA ${item.source_xml_sha256_short}`;
    const actions = document.createElement('div');
    actions.className = 'evidence-actions';
    const open = document.createElement('button');
    open.type = 'button';
    open.textContent = '原文を見る';
    open.addEventListener('click', () => showSource(item));
    actions.appendChild(open);
    card.append(heading, quote, meta, actions);
    evidenceList.appendChild(card);
  });
}

function renderTechnical(data) {
  technical.textContent = JSON.stringify({
    query_id: data.query_id,
    law_resolution: data.law_resolution,
    temporal_resolution: data.temporal_resolution,
    retrieval: data.retrieval,
    timing_ms: data.timing_ms,
    warnings: data.warnings,
  }, null, 2);
}

async function submitQuery() {
  const payload = { question: question.value };
  if (asOfDate.value) payload.as_of_date = asOfDate.value;
  if (lawId.value) payload.law_id = lawId.value;
  setBusy(true);
  try {
    const response = await fetch('/api/v1/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error?.message || `HTTP ${response.status}`);
    }
    result.hidden = false;
    renderStatus(data);
    renderCandidates(data);
    renderAnswer(data);
    renderEvidence(data);
    renderTechnical(data);
  } catch (error) {
    result.hidden = false;
    statusBanner.dataset.status = 'error';
    statusBanner.textContent = `処理できませんでした: ${error.message}`;
    candidatesPanel.hidden = true;
    clearNode(answer);
    clearNode(evidenceList);
    evidenceCount.textContent = '0';
    technical.textContent = '';
  } finally {
    setBusy(false);
  }
}

form.addEventListener('submit', event => {
  event.preventDefault();
  submitQuery();
});

for (const button of document.querySelectorAll('[data-example]')) {
  button.addEventListener('click', () => {
    question.value = button.dataset.example || '';
    lawId.value = '';
    selectedLaw.textContent = '';
    question.focus();
  });
}

dialogClose.addEventListener('click', () => dialog.close());
dialog.addEventListener('click', event => {
  if (event.target === dialog) dialog.close();
});
