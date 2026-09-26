// 実PDF統合確認: TOUKI_SAMPLE_PDF を指定して実行する。
const { chromium } = require('playwright');

async function run() {
  if (!process.env.TOUKI_SAMPLE_PDF) {
    console.log('SKIP: TOUKI_SAMPLE_PDF を指定してください');
    return;
  }
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ acceptDownloads: true });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.TOUKI_BASE_URL || 'http://127.0.0.1:8510/touki/');
    await page.setInputFiles('#files', process.env.TOUKI_SAMPLE_PDF);
    await page.click('#run');
    await page.waitForFunction(() => document.querySelector('#status').textContent.startsWith('解析完了'),
      null, { timeout: 60000 });
    for (const label of ['甲区（所有権）', '乙区（所有権以外の権利）', '共同担保目録']) {
      if (!await page.getByRole('heading', {name: label}).count()) throw new Error(`${label} が表示されない`);
    }
    if (!await page.locator('.pdf-pane iframe').count()) throw new Error('原本PDFプレビューが表示されない');
    const [download] = await Promise.all([page.waitForEvent('download'), page.click('#history-csv')]);
    if (download.suggestedFilename() !== 'touki_history.csv') throw new Error('全履歴CSV出力に失敗');
    if (process.env.TOUKI_SCREENSHOT) {
      await page.screenshot({path: process.env.TOUKI_SCREENSHOT, fullPage: true});
    }
    if (errors.length) throw new Error(errors.join('\n'));
    console.log('PASS: 甲区・乙区・共同担保、原本表示、全履歴CSV');
  } finally { await browser.close(); }
}

run().catch(error => { console.error(error); process.exitCode = 1; });
