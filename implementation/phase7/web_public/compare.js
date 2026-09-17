function clearComparisonOutput() {
  clearNode(compareOverview);
  clearNode(compareChanges);
  clearNode(compareDetail);
}

function prepareComparisonFromQuery(queryData) {
  compareLawId = queryData.law_resolution?.selected_law_id || '';
  compareScopeKey.value = '';
  comparePanel.hidden = !compareLawId;
  if (!compareLawId) return;
  if (!compareToDate.value) compareToDate.value = queryData.effective_as_of_date || '';
  compareStatus.textContent = '比較したい2つの時点を選択してください。';
}

function prepareComparison(historyData) {
  compareLawId = historyData.law?.law_id || '';
  compareScopeKey.value = '';
  comparePanel.hidden = !compareLawId;
  if (!compareLawId) return;
  if (!compareToDate.value) compareToDate.value = historyData.as_of_date || '';
  compareStatus.textContent = '比較元と比較先を選択してください。履歴の各revisionから日付を入れられます。';
}

function selectCompareDate(side, dateValue, lawIdValue) {
  if (!dateValue || !lawIdValue) return;
  compareLawId = lawIdValue;
  comparePanel.hidden = false;
  if (side === 'from') compareFromDate.value = dateValue;
  if (side === 'to') compareToDate.value = dateValue;
  compareStatus.textContent = `${side === 'from' ? '比較元' : '比較先'}に ${dateValue} を設定しました。`;
}

function compareSideLabel(side) {
  const temporal = side?.temporal_resolution || {};
  return `${valueOrDash(side?.as_of_date)} · ${valueOrDash(temporal.status)} · ${valueOrDash(side?.law_revision_id)}`;
}

function renderComparisonStatus(data) {
  if (data.status === 'blocked-temporal') {
    compareStatus.textContent = `時点を一意に確定できないため比較を停止しました。元: ${compareSideLabel(data.from)} / 先: ${compareSideLabel(data.to)}`;
    return;
  }
  if (data.status === 'blocked-content') {
    compareStatus.textContent = `本文が両側に揃っていないため比較できません。元: ${valueOrDash(data.from?.content_status)} / 先: ${valueOrDash(data.to?.content_status)}`;
    return;
  }
  if (data.status === 'same-revision') {
    compareStatus.textContent = `両方の日付は同じrevision ${valueOrDash(data.from?.law_revision_id)} に解決されました。`;
    return;
  }
  if (data.status === 'blocked-article-ambiguous') {
    compareStatus.textContent = '指定条番号が複数の構造スコープに存在するため、条文比較を停止しました。';
    return;
  }
  compareStatus.textContent = `${data.from?.as_of_date} → ${data.to?.as_of_date} の条文構造を比較しました。`;
}

function renderComparisonOverview(data) {
  clearNode(compareOverview);
  const summary = data.summary;
  if (!summary) return;
  const grid = document.createElement('div');
  grid.className = 'compare-count-grid';
  for (const key of ['changed', 'added', 'removed', 'unchanged']) {
    const item = document.createElement('div');
    item.className = 'compare-count-card';
    const strong = document.createElement('strong');
    strong.textContent = String(summary.counts?.[key] || 0);
    const label = document.createElement('span');
    label.textContent = key;
    item.append(strong, label);
    grid.appendChild(item);
  }
  compareOverview.appendChild(grid);
}

function renderComparisonChanges(data) {
  clearNode(compareChanges);
  const changes = data.summary?.changes || [];
  if (!changes.length) return;
  const title = document.createElement('h3');
  title.textContent = '変更された条文';
  compareChanges.appendChild(title);
  for (const change of changes) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'compare-change-button';
    button.dataset.status = change.status;
    const label = change.right_label || change.left_label || `Article ${change.article_num}`;
    button.textContent = `${label} · ${change.status}`;
    button.addEventListener('click', () => {
      compareArticleNum.value = change.article_num;
      compareScopeKey.value = change.scope_key || '';
      compareForm.requestSubmit();
    });
    compareChanges.appendChild(button);
  }
  if (data.summary?.changes_truncated) {
    const note = document.createElement('p');
    note.className = 'muted';
    note.textContent = '変更一覧は上限件数で省略されています。条番号を直接指定して比較できます。';
    compareChanges.appendChild(note);
  }
}

function buildDiffText(segments, side) {
  const pre = document.createElement('pre');
  pre.className = 'compare-text';
  for (const segment of segments || []) {
    const text = side === 'left' ? segment.left : segment.right;
    if (!text) continue;
    const span = document.createElement('span');
    span.dataset.op = segment.op;
    span.textContent = text;
    pre.appendChild(span);
  }
  return pre;
}

function renderComparisonArticle(data) {
  clearNode(compareDetail);
  const article = data.article;
  if (!article) return;
  const heading = document.createElement('h3');
  heading.textContent = `条文詳細 · ${article.scope_label || 'スコープ未指定'} · ${article.article_num}`;
  compareDetail.appendChild(heading);

  if (article.status === 'not-found' || article.status === 'ambiguous') {
    const note = document.createElement('p');
    note.textContent = article.status === 'ambiguous'
      ? 'この条番号は本則・附則など複数の構造スコープに存在するため、自動対応付けしません。'
      : 'この条番号はどちらのrevisionにも見つかりませんでした。';
    compareDetail.appendChild(note);
    if (article.status === 'ambiguous') {
      for (const candidate of article.candidates || []) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'compare-change-button';
        button.textContent = `${candidate.scope_label || candidate.scope_key} · ${candidate.article_num}`;
        button.addEventListener('click', () => {
          compareScopeKey.value = candidate.scope_key;
          compareForm.requestSubmit();
        });
        compareDetail.appendChild(button);
      }
    }
    return;
  }

  const grid = document.createElement('div');
  grid.className = 'compare-text-grid';
  const left = document.createElement('article');
  const right = document.createElement('article');
  left.className = 'compare-side';
  right.className = 'compare-side';
  const leftTitle = document.createElement('h4');
  const rightTitle = document.createElement('h4');
  leftTitle.textContent = `比較元 · ${data.from?.as_of_date}`;
  rightTitle.textContent = `比較先 · ${data.to?.as_of_date}`;
  left.append(leftTitle);
  right.append(rightTitle);
  const segments = article.diff_segments || [];
  if (segments.length) {
    left.appendChild(buildDiffText(segments, 'left'));
    right.appendChild(buildDiffText(segments, 'right'));
  } else {
    const leftText = document.createElement('pre');
    const rightText = document.createElement('pre');
    leftText.className = 'compare-text';
    rightText.className = 'compare-text';
    leftText.textContent = article.left?.text || '（このrevisionには存在しません）';
    rightText.textContent = article.right?.text || '（このrevisionには存在しません）';
    left.appendChild(leftText);
    right.appendChild(rightText);
  }

  const leftMeta = document.createElement('p');
  const rightMeta = document.createElement('p');
  leftMeta.className = 'mono muted';
  rightMeta.className = 'mono muted';
  leftMeta.textContent = `revision ${valueOrDash(data.from?.law_revision_id)} · SHA ${valueOrDash(data.from?.source_xml_sha256)}`;
  rightMeta.textContent = `revision ${valueOrDash(data.to?.law_revision_id)} · SHA ${valueOrDash(data.to?.source_xml_sha256)}`;
  left.appendChild(leftMeta);
  right.appendChild(rightMeta);
  grid.append(left, right);
  compareDetail.appendChild(grid);
}

function renderComparison(data) {
  clearComparisonOutput();
  renderComparisonStatus(data);
  renderComparisonOverview(data);
  renderComparisonChanges(data);
  renderComparisonArticle(data);
}

async function submitComparison() {
  if (!compareLawId) {
    compareStatus.textContent = '先に対象法令を質問から確定してください。';
    return;
  }
  clearComparisonOutput();
  compareButton.disabled = true;
  compareStatus.textContent = '2つの時点と条文構造を比較しています…';
  const params = new URLSearchParams({
    from_date: compareFromDate.value,
    to_date: compareToDate.value,
  });
  if (compareArticleNum.value.trim()) {
    params.set('article_num', compareArticleNum.value.trim());
    if (compareScopeKey.value) params.set('scope_key', compareScopeKey.value);
  }
  try {
    const response = await fetch(`/api/v1/laws/${encodeURIComponent(compareLawId)}/compare?${params}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || `compare HTTP ${response.status}`);
    renderComparison(data);
  } catch (error) {
    clearComparisonOutput();
    compareStatus.textContent = `比較できませんでした: ${error.message}`;
  } finally {
    compareButton.disabled = false;
  }
}

compareArticleNum.addEventListener('input', () => { compareScopeKey.value = ''; });

compareForm.addEventListener('submit', event => {
  event.preventDefault();
  submitComparison();
});
