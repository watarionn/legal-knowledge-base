const relatedPanel = document.querySelector('#related-panel');
const relatedCount = document.querySelector('#related-count');
const relatedStatus = document.querySelector('#related-status');
const relatedList = document.querySelector('#related-list');

let relatedContext = { lawId: '', asOfDate: '' };

function clearRelatedMaterials() {
  clearNode(relatedList);
  relatedCount.textContent = '';
  relatedStatus.textContent = '';
}

function relatedFamilyLabel(value) {
  return ({
    'official-gazette': '官報',
    'diet-minutes': '国会会議録',
    'imperial-diet-minutes': '帝国議会会議録',
    'ndl-search': 'NDL資料',
  })[value] || value;
}

function prepareRelatedMaterialsFromQuery(queryData) {
  relatedContext = {
    lawId: queryData.law_resolution?.selected_law_id || '',
    asOfDate: queryData.effective_as_of_date || '',
  };
  relatedPanel.hidden = !relatedContext.lawId;
  if (!relatedContext.lawId) clearRelatedMaterials();
}
function safeExternalUrl(value) {
  if (!value) return null;
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : null;
  } catch (_error) {
    return null;
  }
}

function renderMaterialCard(material) {
  const card = document.createElement('article');
  card.className = 'related-card';

  const title = document.createElement('h3');
  title.textContent = material.title || `${relatedFamilyLabel(material.source_family)}資料`;
  const meta = document.createElement('p');
  meta.className = 'muted';
  meta.textContent = [
    relatedFamilyLabel(material.source_family),
    material.issued_on,
    material.provider_code,
  ].filter(Boolean).join(' · ');
  card.append(title, meta);

  const relations = document.createElement('div');
  relations.className = 'related-relations';
  for (const relation of material.relations || []) {
    if (!relation.citation_ready || relation.effective_state !== 'confirmed') continue;
    const row = document.createElement('div');
    row.className = 'related-relation';
    const badge = document.createElement('span');
    badge.className = 'history-badge';
    badge.textContent = 'confirmed · 引用可';
    const label = document.createElement('span');
    label.textContent = `${relation.relation_kind} · ${relation.target_kind}`;
    row.append(badge, label);
    relations.appendChild(row);
  }
  card.appendChild(relations);

  const actions = document.createElement('div');
  actions.className = 'history-actions';
  const externalUrl = safeExternalUrl(material.canonical_url);
  if (externalUrl) {
    const link = document.createElement('a');
    link.href = externalUrl;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = '公式資料を開く';
    actions.appendChild(link);
  }
  const sha = document.createElement('span');
  sha.className = 'mono muted';
  sha.textContent = material.source_file_sha256 ? `RAW SHA ${material.source_file_sha256}` : 'RAW snapshotなし';
  actions.appendChild(sha);
  card.appendChild(actions);
  return card;
}
function renderRelatedMaterials(data) {
  clearNode(relatedList);
  relatedCount.textContent = String(data.material_count || 0);
  const temporalStatus = data.temporal_resolution?.status || 'unknown';
  relatedStatus.textContent = data.revision_scope_available
    ? `${data.as_of_date} のrevisionと法令全体に紐づくconfirmed資料を表示しています。`
    : `${data.as_of_date} は ${temporalStatus} のため、法令全体に紐づくconfirmed資料だけを表示しています。`;

  if (!(data.materials || []).length) {
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = 'この範囲にconfirmed関連資料はありません。';
    relatedList.appendChild(empty);
    return;
  }
  for (const material of data.materials) {
    relatedList.appendChild(renderMaterialCard(material));
  }
}

async function fetchRelatedMaterials() {
  if (!relatedContext.lawId) return;
  relatedStatus.textContent = '関連資料を確認しています…';
  const params = new URLSearchParams({ as_of_date: relatedContext.asOfDate });
  const response = await fetch(
    `/api/v1/laws/${encodeURIComponent(relatedContext.lawId)}/related-materials?${params}`,
  );
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || `HTTP ${response.status}`);
  renderRelatedMaterials(data);
}

async function loadRelatedMaterials(queryData) {
  prepareRelatedMaterialsFromQuery(queryData);
  if (!relatedContext.lawId) return;
  relatedPanel.hidden = false;
  await fetchRelatedMaterials();
}
