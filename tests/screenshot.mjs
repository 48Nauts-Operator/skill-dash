// Visual smoke: open the dashboard, open a skill drawer, save a decision, screenshot. Run:
//   NODE_PATH=~/DevHub_Studio/factory/02-Development/xnaut/node_modules node tests/screenshot.mjs
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const base = process.env.BASE || 'http://localhost:3345';
const out = process.env.OUT || '.data';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on('pageerror', e => errors.push('pageerror: ' + e.message));
page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
await page.goto(base + '/#overview');
await page.waitForFunction(() => document.querySelectorAll('#rows tr').length > 1, null, { timeout: 15000 });
await page.screenshot({ path: `${out}/shot-overview.png`, fullPage: true });
const first = await page.getAttribute('#rows [data-skill]', 'data-skill');
await page.click('#rows [data-skill]');
await page.waitForSelector('#decision-form');
await page.screenshot({ path: `${out}/shot-drawer.png`, fullPage: false });
await page.selectOption('#decision-form [name=decision]', 'delete');
const target = first;
await page.fill('#decision-form [name=note]', 'smoke test, cleared below');
await page.click('#decision-form button[type=submit]');
await page.waitForFunction(() => document.querySelector('#toast')?.textContent.includes('Decision saved'), null, { timeout: 8000 });
await page.keyboard.press('Escape');
await page.click('[data-view="judges"]');
await page.waitForSelector('#judgment-cards .judgment-card');
await page.screenshot({ path: `${out}/shot-judges.png`, fullPage: true });
const cards = await page.$$eval('#judgment-cards .judgment-card', n => n.length);
console.log(JSON.stringify({ cards, errors }, null, 1));
// clear the smoke decision so no fake verdict survives the test
await fetch(base + '/api/decide', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: target, decision: '', note: '' }) });
await browser.close();
if (errors.length) process.exit(1);
