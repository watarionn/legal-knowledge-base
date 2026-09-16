const dailyStatus = document.querySelector('#daily-status');
const dailyFavoriteButton = document.querySelector('#favorite-current');
const dailyFavoriteList = document.querySelector('#favorite-list');
const dailyRecentList = document.querySelector('#recent-list');
const dailyHistoryList = document.querySelector('#search-history-list');
const dailyThemeList = document.querySelector('#saved-theme-list');
const dailyClearRecent = document.querySelector('#clear-recent');
const dailyClearHistory = document.querySelector('#clear-history');
const dailyThemeForm = document.querySelector('#save-theme-form');
const dailyThemeTitle = document.querySelector('#theme-title');
const dailyQuestionInput = document.querySelector('#question');
const dailyLawIdInput = document.querySelector('#law-id');
const dailySelectedLaw = document.querySelector('#selected-law');
const dailyAsOfDate = document.querySelector('#as-of-date');
const dailyQueryForm = document.querySelector('#query-form');
const dailyWatchButton = document.querySelector('#watch-current');
const dailyWatchList = document.querySelector('#watch-list');
const dailyWatchUnreadTotal = document.querySelector('#watch-unread-total');
const dailyRefreshWatches = document.querySelector('#refresh-watches');

let dailySnapshot = {
  favorites: [], recent_laws: [], search_history: [], saved_themes: [],
};
let dailyCurrentLaw = { lawId: '', lawTitle: '' };
let dailyWatches = [];
let dailyWatchWarning = '';

function dailyClearNode(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function dailyEmpty(node, text) {
  const p = document.createElement('p');
  p.className = 'muted';
  p.textContent = text;
  node.appendChild(p);
}
function dailyLawLabel(item) {
  return item.law_title || item.law_num || item.law_id;
}

function dailySelectLaw(item) {
  dailyLawIdInput.value = item.law_id || '';
  dailySelectedLaw.textContent = item.law_id
    ? `対象法令: ${dailyLawLabel(item)} (${item.law_id})`
    : '';
  dailyQuestionInput.focus();
}

function dailyReplay(item) {
  dailyQuestionInput.value = item.question || '';
  dailyLawIdInput.value = item.law_id || '';
  dailyAsOfDate.value = item.requested_as_of_date || item.effective_as_of_date || item.as_of_date || '';
  dailySelectedLaw.textContent = item.law_id
    ? `対象法令: ${item.law_title || item.law_id} (${item.law_id})`
    : '';
  dailyQueryForm.requestSubmit();
}

function dailyItemButton(text, onClick) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'daily-item-button';
  button.textContent = text;
  button.addEventListener('click', onClick);
  return button;
}
function renderDailyFavorites() {
  dailyClearNode(dailyFavoriteList);
  if (!dailySnapshot.favorites.length) {
    dailyEmpty(dailyFavoriteList, 'お気に入り法令はまだありません。');
    return;
  }
  for (const item of dailySnapshot.favorites) {
    const row = document.createElement('div');
    row.className = 'daily-item';
    row.appendChild(dailyItemButton(dailyLawLabel(item), () => dailySelectLaw(item)));
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.textContent = '解除';
    remove.addEventListener('click', async () => {
      await fetch(`/api/v1/favorites/${encodeURIComponent(item.law_id)}`, { method: 'DELETE' });
      await loadDailyState();
    });
    row.appendChild(remove);
    dailyFavoriteList.appendChild(row);
  }
}

function renderDailyRecent() {
  dailyClearNode(dailyRecentList);
  if (!dailySnapshot.recent_laws.length) {
    dailyEmpty(dailyRecentList, '最近見た法令はまだありません。');
    return;
  }
  for (const item of dailySnapshot.recent_laws) {
    const label = `${dailyLawLabel(item)} · ${item.view_count}回`;
    dailyRecentList.appendChild(dailyItemButton(label, () => dailySelectLaw(item)));
  }
}
function renderDailyHistory() {
  dailyClearNode(dailyHistoryList);
  if (!dailySnapshot.search_history.length) {
    dailyEmpty(dailyHistoryList, '検索履歴はまだありません。');
    return;
  }
  for (const item of dailySnapshot.search_history) {
    const row = document.createElement('div');
    row.className = 'daily-history-item';
    const button = dailyItemButton(item.question, () => dailyReplay(item));
    const meta = document.createElement('p');
    meta.className = 'muted';
    meta.textContent = [item.law_title, item.effective_as_of_date, item.status].filter(Boolean).join(' · ');
    row.append(button, meta);
    dailyHistoryList.appendChild(row);
  }
}

function renderDailyThemes() {
  dailyClearNode(dailyThemeList);
  if (!dailySnapshot.saved_themes.length) {
    dailyEmpty(dailyThemeList, '保存テーマはまだありません。');
    return;
  }
  for (const item of dailySnapshot.saved_themes) {
    const row = document.createElement('div');
    row.className = 'daily-item';
    row.appendChild(dailyItemButton(item.title, () => dailyReplay(item)));
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.textContent = '削除';
    remove.addEventListener('click', async () => {
      await fetch(`/api/v1/saved-themes/${encodeURIComponent(item.theme_id)}`, { method: 'DELETE' });
      await loadDailyState();
    });
    row.appendChild(remove);
    dailyThemeList.appendChild(row);
  }
}
function dailyNavigationLink(text, navigation) {
  if (!navigation || !navigation.path) return null;
  const link = document.createElement('a');
  link.href = navigation.path;
  link.target = '_blank';
  link.rel = 'noopener';
  link.className = 'watch-nav-link';
  link.textContent = text;
  return link;
}

async function renderWatchEvents(watch, container) {
  dailyClearNode(container);
  const response = await fetch(`/api/v1/watches/${encodeURIComponent(watch.watch_id)}/events?limit=20`);
  const data = await response.json();
  if (!response.ok) {
    dailyEmpty(container, data.error?.message || `HTTP ${response.status}`);
    return;
  }
  if (!data.events.length) {
    dailyEmpty(container, '変更イベントはまだありません。');
    return;
  }
  for (const item of data.events) {
    const eventRow = document.createElement('div');
    eventRow.className = 'watch-event';
    const title = document.createElement('p');
    title.className = 'watch-event-title';
    title.textContent = `${item.event_type}${item.acknowledged ? ' · 確認済み' : ' · 未確認'}`;
    const meta = document.createElement('p');
    meta.className = 'muted';
    meta.textContent = [item.detected_at, item.to_revision_id].filter(Boolean).join(' · ');
    const nav = document.createElement('div');
    nav.className = 'watch-nav';
    for (const [label, value] of [
      ['改正履歴', item.navigation?.history],
      ['条文比較', item.navigation?.compare],
      ['関連資料', item.navigation?.confirmed_related_materials],
    ]) {
      const link = dailyNavigationLink(label, value);
      if (link) nav.appendChild(link);
    }
    eventRow.append(title, meta, nav);
    if (!item.acknowledged) {
      const acknowledge = document.createElement('button');
      acknowledge.type = 'button';
      acknowledge.textContent = '確認済みにする';
      acknowledge.addEventListener('click', async () => {
        const ackResponse = await fetch(`/api/v1/watch-events/${encodeURIComponent(item.event_id)}/acknowledge`, { method: 'POST' });
        if (!ackResponse.ok) return;
        await loadDailyState();
      });
      eventRow.appendChild(acknowledge);
    }
    container.appendChild(eventRow);
  }
}

function renderDailyWatches() {
  dailyClearNode(dailyWatchList);
  const unread = dailyWatches.reduce((sum, item) => sum + Number(item.unacknowledged_event_count || 0), 0);
  dailyWatchUnreadTotal.textContent = unread ? `未確認 ${unread}` : '';
  if (!dailyWatches.length) {
    dailyEmpty(dailyWatchList, 'ウォッチ中の法令はありません。');
    return;
  }
  for (const item of dailyWatches) {
    const row = document.createElement('div');
    row.className = 'daily-history-item watch-item';
    const head = document.createElement('div');
    head.className = 'daily-item';
    head.appendChild(dailyItemButton(dailyLawLabel(item), () => dailySelectLaw(item)));
    const events = document.createElement('button');
    events.type = 'button';
    events.textContent = `イベント ${item.unacknowledged_event_count || 0}`;
    const eventList = document.createElement('div');
    eventList.className = 'watch-event-list';
    eventList.hidden = true;
    events.addEventListener('click', async () => {
      eventList.hidden = !eventList.hidden;
      if (!eventList.hidden) await renderWatchEvents(item, eventList);
    });
    head.appendChild(events);
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.textContent = '解除';
    remove.addEventListener('click', async () => {
      await fetch(`/api/v1/watches/${encodeURIComponent(item.watch_id)}`, { method: 'DELETE' });
      await loadDailyState();
    });
    head.appendChild(remove);
    const meta = document.createElement('p');
    meta.className = 'muted';
    meta.textContent = item.last_evaluated_at ? `最終確認 ${item.last_evaluated_at}` : '未評価';
    row.append(head, meta, eventList);
    dailyWatchList.appendChild(row);
  }
}

async function loadWatchState() {
  dailyWatchWarning = '';
  try {
    const response = await fetch('/api/v1/watches');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || `HTTP ${response.status}`);
    dailyWatches = data.watches || [];
  } catch (error) {
    dailyWatches = [];
    dailyWatchWarning = `法令ウォッチを読み込めませんでした: ${error.message}`;
  }
}

function renderDailyState() {
  renderDailyFavorites();
  renderDailyRecent();
  renderDailyHistory();
  renderDailyThemes();
  renderDailyWatches();
  const isFavorite = dailySnapshot.favorites.some(item => item.law_id === dailyCurrentLaw.lawId);
  const currentWatch = dailyWatches.find(item => item.law_id === dailyCurrentLaw.lawId && !item.theme_id);
  dailyFavoriteButton.hidden = !dailyCurrentLaw.lawId;
  dailyFavoriteButton.textContent = isFavorite ? 'お気に入りを解除' : 'この法令をお気に入り';
  dailyFavoriteButton.dataset.favorite = isFavorite ? 'true' : 'false';
  dailyWatchButton.hidden = !dailyCurrentLaw.lawId;
  dailyWatchButton.textContent = currentWatch ? 'この法令のウォッチを解除' : 'この法令をウォッチ';
  dailyWatchButton.dataset.watchId = currentWatch?.watch_id || '';
}

async function loadDailyState() {
  const response = await fetch('/api/v1/daily-state?recent_limit=12&history_limit=30');
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || `HTTP ${response.status}`);
  dailySnapshot = data;
  await loadWatchState();
  renderDailyState();
  dailyStatus.textContent = dailyWatchWarning;
}

async function refreshDailyUse(queryData) {
  const resolution = queryData.law_resolution || {};
  dailyCurrentLaw = {
    lawId: resolution.selected_law_id || '',
    lawTitle: resolution.selected_law_title || '',
  };
  try {
    await loadDailyState();
  } catch (error) {
    dailyStatus.textContent = `マイリストを更新できませんでした: ${error.message}`;
  }
}
dailyWatchButton.addEventListener('click', async () => {
  if (!dailyCurrentLaw.lawId) return;
  const watchId = dailyWatchButton.dataset.watchId;
  const response = watchId
    ? await fetch(`/api/v1/watches/${encodeURIComponent(watchId)}`, { method: 'DELETE' })
    : await fetch('/api/v1/watches', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ law_id: dailyCurrentLaw.lawId }),
      });
  const data = await response.json();
  if (!response.ok) {
    dailyStatus.textContent = `法令ウォッチを更新できませんでした: ${data.error?.message || response.status}`;
    return;
  }
  await loadDailyState();
});

dailyRefreshWatches.addEventListener('click', async () => {
  dailyRefreshWatches.disabled = true;
  dailyStatus.textContent = 'ウォッチ対象法令の更新を確認しています…';
  try {
    const response = await fetch('/api/v1/watches/refresh', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || data.refresh?.refresh_status || `HTTP ${response.status}`);
    const status = data.refresh?.refresh_status || 'unknown';
    const count = data.refresh?.requested_law_count || 0;
    dailyStatus.textContent = status === 'succeeded'
      ? `${count}法令の更新確認とウォッチ評価が完了しました。`
      : status === 'no-watches' ? 'ウォッチ対象法令はありません。' : `更新確認結果: ${status}`;
    await loadDailyState();
  } catch (error) {
    dailyStatus.textContent = `法令ウォッチの更新確認に失敗しました: ${error.message}`;
  } finally {
    dailyRefreshWatches.disabled = false;
  }
});

dailyFavoriteButton.addEventListener('click', async () => {
  if (!dailyCurrentLaw.lawId) return;
  const isFavorite = dailyFavoriteButton.dataset.favorite === 'true';
  const response = await fetch(`/api/v1/favorites/${encodeURIComponent(dailyCurrentLaw.lawId)}`, {
    method: isFavorite ? 'DELETE' : 'PUT',
  });
  if (!response.ok) {
    const data = await response.json();
    dailyStatus.textContent = `お気に入りを更新できませんでした: ${data.error?.message || response.status}`;
    return;
  }
  await loadDailyState();
});

dailyThemeForm.addEventListener('submit', async event => {
  event.preventDefault();
  const payload = {
    title: dailyThemeTitle.value.trim(),
    question: dailyQuestionInput.value.trim(),
    law_id: dailyLawIdInput.value || null,
    as_of_date: dailyAsOfDate.value || null,
  };
  const response = await fetch('/api/v1/saved-themes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    dailyStatus.textContent = `テーマを保存できませんでした: ${data.error?.message || response.status}`;
    return;
  }
  dailyThemeTitle.value = '';
  dailyStatus.textContent = `「${data.title}」を保存しました。`;
  await loadDailyState();
});

async function dailyClearCollection(path) {
  const response = await fetch(path, { method: 'DELETE' });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || `HTTP ${response.status}`);
  await loadDailyState();
}

dailyClearHistory.addEventListener('click', async () => {
  try {
    await dailyClearCollection('/api/v1/search-history');
  } catch (error) {
    dailyStatus.textContent = `検索履歴を消去できませんでした: ${error.message}`;
  }
});

dailyClearRecent.addEventListener('click', async () => {
  try {
    await dailyClearCollection('/api/v1/recent-laws');
  } catch (error) {
    dailyStatus.textContent = `最近見た法令を消去できませんでした: ${error.message}`;
  }
});
loadDailyState().catch(error => {
  dailyStatus.textContent = `マイリストを読み込めませんでした: ${error.message}`;
});
