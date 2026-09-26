(() => {
  'use strict';
  const prefix = document.body.dataset.prefix || '';
  const input = document.querySelector('#files');
  const drop = document.querySelector('#drop');
  const run = document.querySelector('#run');
  const csv = document.querySelector('#csv');
  const historyCsv = document.querySelector('#history-csv');
  const status = document.querySelector('#status');
  const tabs = document.querySelector('#document-tabs');
  const resultsEl = document.querySelector('#results');
  let results = [];
  let pdfUrls = [];
  let selected = 0;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
  const hasValue = value => value !== null && value !== undefined && String(value).trim() !== '';
  const fields = (data, omit = []) => Object.entries(data || {})
    .filter(([key, value]) => !key.startsWith('_') && !omit.includes(key) && hasValue(value))
    .map(([key, value]) => `<div class="field-row"><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`).join('');
  const section = (title, count, content) => `<section class="section"><header><h2>${esc(title)}</h2>${count === null ? '' : `<span class="count">${count}件</span>`}</header><div class="section-content">${content}</div></section>`;
  const sectionNote = message => `<p class="note">${esc(message)}</p>`;
  const numberKey = value => (String(value || '').match(/第\s*([0-9][0-9/]*)\s*号/) || [])[1] || '';

  function entryCard(entry, linked = []) {
    const cancelled = /抹消|移転前/.test(entry['状態'] || '');
    const rank = entry['順位'] ? `順位 ${entry['順位']}　` : '';
    const heading = entry['登記の目的'] || entry['内容'] || entry['抵当権者'] || '明細';
    const label = entry['状態'] || (entry._is_fuki ? '付記' : '');
    const extra = linked.length ? `<div class="linked"><div class="linked-title">関連する共同担保目録</div><ul class="linked-list">${linked.map(item => `<li>${esc(item['記号及び番号'] || '')}　${esc(item['内容'] || '')}　${esc(item['状態'] || '')}</li>`).join('')}</ul></div>` : '';
    return `<article class="entry ${cancelled ? 'cancelled' : ''}"><div class="entry-head"><strong>${esc(rank + heading)}</strong>${label ? `<span class="badge ${cancelled ? 'cancelled' : ''}">${esc(label)}</span>` : ''}</div><dl class="field-list">${fields(entry, ['順位', '登記の目的', '内容', '状態'])}</dl>${extra}</article>`;
  }

  function summary(item) {
    const record = item.record || {};
    const type = item.doc_type === 'tochi' ? '土地' : '建物';
    const main = item.doc_type === 'tochi'
      ? ['不動産番号', '所在', '地番', '地目', '地積_m2']
      : ['不動産番号', '所在', '家屋番号', '種類', '構造', '床面積_m2'];
    const labels = {'地積_m2': '地積（㎡）', '床面積_m2': '床面積（㎡）'};
    const cells = main.map(key => `<div class="summary-cell"><small>${esc(labels[key] || key)}</small><strong>${esc(record[key] || '—')}</strong></div>`).join('');
    return `<h2 class="document-title">${esc(item.filename || '')}</h2>${section(`表題部（${type}）`, null, `<div class="summary-grid">${cells}</div><details class="fallback"><summary>その他の抽出項目</summary><dl class="field-list">${fields(record, [...main, '所有者氏名', '所有者住所', '現在の所有者'])}</dl></details>`)}`;
  }

  function render(item, index) {
    if (item.error) {
      resultsEl.innerHTML = `<section class="section"><div class="section-content error"><h2>${esc(item.filename || '解析エラー')}</h2><p>${esc(item.error)}</p></div></section>`;
      return;
    }
    const record = item.record || {};
    const history = item.history || {};
    const kouku = history.kouku || [];
    const otsuku = history.otsuku || [];
    const tanpo = history.tanpo || [];
    const owners = (record['所有者氏名'] || '').split('；').map(v => v.trim()).filter(Boolean);
    const addresses = (record['所有者住所'] || '').split('；');
    const ownerList = owners.length
      ? `<ol class="owner-list">${owners.map((name, i) => `<li>${esc(name)}${addresses[i] ? `<br><small>${esc(addresses[i])}</small>` : ''}</li>`).join('')}</ol>`
      : sectionNote('所有者を抽出できませんでした。原本の甲区をご確認ください。');
    const warnings = (item.warnings || []).map(w => `<div class="warning">${esc(w)}</div>`).join('');
    const matched = new Set();
    const otsukuCards = otsuku.map(entry => {
      const key = numberKey(entry['共担目録番号']);
      const links = key ? tanpo.filter(t => numberKey(t['記号及び番号']) === key) : [];
      links.forEach(link => matched.add(link));
      return entryCard(entry, links);
    }).join('');
    const tanpoCards = tanpo.map(entry => entryCard(entry)).join('');
    const unmatched = tanpo.filter(entry => !matched.has(entry));
    const unmatchedNote = unmatched.length && matched.size
      ? `<p class="review-note">乙区の目録番号と一致しない明細が${unmatched.length}件あります。原本で関連を確認してください。</p>` : '';
    const content = warnings + summary(item)
      + section('現在の所有者', owners.length, ownerList)
      + section('甲区（所有権）', kouku.length, kouku.map(entry => entryCard(entry)).join('') || sectionNote('甲区の明細を検出できませんでした。原本を確認してください。'))
      + section('乙区（所有権以外の権利）', otsuku.length, otsukuCards || sectionNote('乙区の明細はありません。原本を確認してください。'))
      + section('共同担保目録', tanpo.length, tanpoCards + unmatchedNote || sectionNote('共同担保目録の明細はありません。原本を確認してください。'))
      + '<p class="review-note">自動抽出結果です。権利判断や転記の前に原本PDFと照合してください。</p>';
    const url = pdfUrls[index];
    resultsEl.innerHTML = `<div class="document-layout"><div class="analysis">${content}</div><aside class="pdf-pane"><header>原本PDF${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">別タブで開く</a>` : ''}</header>${url ? `<iframe title="原本PDF" src="${esc(url)}"></iframe>` : sectionNote('原本PDFを表示できません。')}</aside></div>`;
  }

  function showSelection() {
    tabs.innerHTML = results.map((item, i) => `<button type="button" data-index="${i}" class="${i === selected ? 'active' : ''}" title="${esc(item.filename || '')}">${esc(item.filename || `書類${i + 1}`)}</button>`).join('');
    tabs.querySelectorAll('button').forEach(button => button.addEventListener('click', () => {
      selected = Number(button.dataset.index);
      showSelection();
    }));
    if (results[selected]) render(results[selected], selected);
  }

  ['dragenter', 'dragover'].forEach(name => drop.addEventListener(name, event => {
    event.preventDefault(); drop.classList.add('drag');
  }));
  ['dragleave', 'drop'].forEach(name => drop.addEventListener(name, event => {
    event.preventDefault(); drop.classList.remove('drag');
  }));
  drop.addEventListener('drop', event => {
    input.files = event.dataTransfer.files;
    status.textContent = `${input.files.length}件を選択中`;
  });
  input.addEventListener('change', () => { status.textContent = `${input.files.length}件を選択中`; });

  run.addEventListener('click', async () => {
    const files = [...input.files];
    if (!files.length) { status.textContent = 'PDFを選択してください'; return; }
    run.disabled = true; csv.disabled = true; historyCsv.disabled = true;
    status.textContent = '解析中…';
    tabs.innerHTML = ''; resultsEl.innerHTML = '';
    pdfUrls.forEach(URL.revokeObjectURL); pdfUrls = files.map(file => URL.createObjectURL(file));
    const form = new FormData(); files.forEach(file => form.append('files', file));
    try {
      const response = await fetch(`${prefix}/api/analyze`, {method: 'POST', body: form});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '解析に失敗しました');
      results = data.results || [];
      selected = 0; showSelection();
      csv.disabled = !results.some(item => item.record);
      historyCsv.disabled = !results.some(item => Object.values(item.history || {}).some(entries => entries.length));
      status.textContent = `解析完了：${results.filter(item => item.record).length} / ${results.length}件`;
    } catch (error) {
      results = []; status.textContent = error.message;
    } finally { run.disabled = false; }
  });

  async function downloadCsv(endpoint, filename) {
    const response = await fetch(`${prefix}/api/${endpoint}`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({results})
    });
    if (!response.ok) { status.textContent = 'CSV出力に失敗しました'; return; }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a'); link.href = url; link.download = filename;
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  csv.addEventListener('click', () => downloadCsv('export.csv', 'touki_results.csv'));
  historyCsv.addEventListener('click', () => downloadCsv('export-history.csv', 'touki_history.csv'));
  window.addEventListener('pagehide', () => pdfUrls.forEach(URL.revokeObjectURL));
})();
