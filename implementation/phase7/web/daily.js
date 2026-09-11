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

let dailySnapshot = {
  favorites: [], recent_laws: [], search_history: [], saved_themes: [],
};
let dailyCurrentLaw = { lawId: '', lawTitle: '' };

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
function renderDailyState() {
  renderDailyFavorites();
  renderDailyRecent();
  renderDailyHistory();
  renderDailyThemes();
  const isFavorite = dailySnapshot.favorites.some(item => item.law_id === dailyCurrentLaw.lawId);
  dailyFavoriteButton.hidden = !dailyCurrentLaw.lawId;
  dailyFavoriteButton.textContent = isFavorite ? 'お気に入りを解除' : 'この法令をお気に入り';
  dailyFavoriteButton.dataset.favorite = isFavorite ? 'true' : 'false';
}

async function loadDailyState() {
  const response = await fetch('/api/v1/daily-state?recent_limit=12&history_limit=30');
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || `HTTP ${response.status}`);
  dailySnapshot = data;
  renderDailyState();
  dailyStatus.textContent = '';
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
