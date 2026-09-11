const relatedPanel = document.querySelector('#related-panel');
const relatedIncludeNonconfirmed = document.querySelector('#related-include-nonconfirmed');
const relatedCount = document.querySelector('#related-count');
const relatedStatus = document.querySelector('#related-status');
const relatedList = document.querySelector('#related-list');
const relationDialog = document.querySelector('#relation-dialog');
const relationDialogClose = document.querySelector('#relation-dialog-close');
const relationDialogTitle = document.querySelector('#relation-dialog-title');
const relationDialogState = document.querySelector('#relation-dialog-state');
const relationDialogMeta = document.querySelector('#relation-dialog-meta');
const relationAssertions = document.querySelector('#relation-assertions');

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

function relationStateLabel(relation) {
  if (relation.citation_ready) return 'confirmed · 引用可';
  return `${relation.effective_state} · 引用不可`;
}

function addDefinition(dl, term, value) {
  const dt = document.createElement('dt');
  const dd = document.createElement('dd');
  dt.textContent = term;
  dd.textContent = valueOrDash(value);
  dl.append(dt, dd);
}

function prepareRelatedMaterialsFromQuery(queryData) {
  const law = queryData.law_resolution?.selected_law_id || '';
  const dateValue = queryData.effective_as_of_date || '';
  if (law !== relatedContext.lawId) relatedIncludeNonconfirmed.checked = false;
  relatedContext = { lawId: law, asOfDate: dateValue };
  relatedPanel.hidden = !law;
  if (!law) clearRelatedMaterials();
}

async function showRelationDetail(sourceRelationId) {
  clearNode(relationDialogMeta);
  clearNode(relationAssertions);
  relationDialogState.textContent = '関連付けの証拠を確認しています…';
  relationDialog.showModal();
  try {
    const response = await fetch(`/api/v1/source-relations/${encodeURIComponent(sourceRelationId)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || `HTTP ${response.status}`);
    relationDialogTitle.textContent = data.title || '関連付けの根拠';
    relationDialogState.textContent = `${data.effective_state} · ${data.citation_ready ? '引用可' : '引用不可'}`;
    addDefinition(relationDialogMeta, '資料種別', relatedFamilyLabel(data.source_family));
    addDefinition(relationDialogMeta, 'relation', data.relation_kind);
    addDefinition(relationDialogMeta, 'target', `${data.target_kind}: ${data.target_id}`);
    addDefinition(relationDialogMeta, 'provider', data.provider_code);
    addDefinition(relationDialogMeta, 'snapshot', data.snapshot_id);
    addDefinition(relationDialogMeta, 'RAW SHA-256', data.source_file_sha256);

    const heading = document.createElement('h3');
    heading.textContent = `assertion ${data.assertions?.length || 0}件`;
    relationAssertions.appendChild(heading);
    for (const assertion of data.assertions || []) {
      const card = document.createElement('article');
      card.className = 'relation-assertion';
      const top = document.createElement('strong');
      top.textContent = `${assertion.assertion_status} · ${assertion.assertion_basis}`;
      const locator = document.createElement('p');
      locator.className = 'mono muted';
      locator.textContent = assertion.source_locator || 'source locatorなし';
      const evidence = document.createElement('pre');
      evidence.className = 'relation-evidence';
      evidence.textContent = JSON.stringify(assertion.evidence || {}, null, 2);
      card.append(top, locator, evidence);
      relationAssertions.appendChild(card);
    }
  } catch (error) {
    relationDialogState.textContent = `根拠を取得できませんでした: ${error.message}`;
  }
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
  card.dataset.citationReady = material.citation_ready ? 'true' : 'false';

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
    const row = document.createElement('div');
    row.className = 'related-relation';
    row.dataset.citationReady = relation.citation_ready ? 'true' : 'false';
    const badge = document.createElement('span');
    badge.className = 'history-badge';
    badge.textContent = relationStateLabel(relation);
    const label = document.createElement('span');
    label.textContent = `${relation.relation_kind} · ${relation.target_kind}`;
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = '関連付けの根拠';
    button.addEventListener('click', () => showRelationDetail(relation.source_relation_id));
    row.append(badge, label, button);
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
  if (data.revision_scope_available) {
    relatedStatus.textContent = `${data.as_of_date} のrevisionと法令全体に紐づく資料を表示しています。`;
  } else {
    relatedStatus.textContent = `${data.as_of_date} は ${temporalStatus} のため、法令全体に紐づく資料だけを表示しています。`;
  }
  if (data.include_nonconfirmed) {
    relatedStatus.textContent += ' 候補資料を含みます。引用可否を必ず確認してください。';
  }

  if (!(data.materials || []).length) {
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = data.include_nonconfirmed
      ? 'この範囲に関連資料はありません。'
      : 'confirmed資料はありません。「候補も表示」で未確認relationを確認できます。';
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
  const params = new URLSearchParams({
    as_of_date: relatedContext.asOfDate,
    include_nonconfirmed: relatedIncludeNonconfirmed.checked ? 'true' : 'false',
  });
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

relatedIncludeNonconfirmed.addEventListener('change', async () => {
  if (!relatedContext.lawId) return;
  try {
    await fetchRelatedMaterials();
  } catch (error) {
    clearNode(relatedList);
    relatedCount.textContent = '';
    relatedStatus.textContent = `関連資料を取得できませんでした: ${error.message}`;
  }
});

relationDialogClose.addEventListener('click', () => relationDialog.close());
