#!/usr/bin/env node
// Headless browser driver for the Doc2MD web app.
//
// Drives the running frontend (default http://localhost:5173) with Playwright:
// uploads a document, waits for the conversion result, exercises the
// Preview/Raw toggle, and writes screenshots to disk.
//
// Prereqs (already true in the Claude web container):
//   - A global Playwright install (resolved via createRequire on the global
//     node_modules path) and Chromium at $PLAYWRIGHT_BROWSERS_PATH.
//   - Backend running on $API_URL (default http://127.0.0.1:8000).
//   - Frontend dev server running on $APP_URL (default http://localhost:5173).
//
// Usage:
//   node driver.mjs <file-to-upload> [outdir]
//
// Env overrides: APP_URL, OUT_DIR.

import { createRequire } from 'node:module';
import { execSync } from 'node:child_process';
import path from 'node:path';
import fs from 'node:fs';

// Resolve the globally-installed playwright regardless of cwd.
const globalRoot = execSync('npm root -g').toString().trim();
const require = createRequire(path.join(globalRoot, 'noop.js'));
const { chromium } = require('playwright');

const APP_URL = process.env.APP_URL || 'http://localhost:5173';
const uploadFile = process.argv[2];
const OUT_DIR = process.argv[3] || process.env.OUT_DIR || '/tmp/doc2md-shots';

if (!uploadFile || !fs.existsSync(uploadFile)) {
  console.error(`Usage: node driver.mjs <file-to-upload> [outdir]\n` +
    `  file not found: ${uploadFile}`);
  process.exit(2);
}
fs.mkdirSync(OUT_DIR, { recursive: true });

const shot = async (page, name) => {
  const p = path.join(OUT_DIR, `${name}.png`);
  await page.screenshot({ path: p, fullPage: true });
  console.log(`screenshot: ${p}`);
};

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1100, height: 900 } });
  const errors = [];
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));

  try {
    await page.goto(APP_URL, { waitUntil: 'networkidle' });
    await page.waitForSelector('text=Doc2MD');
    await shot(page, '1-landing');

    // The dropzone renders a hidden <input type="file">. Set it directly.
    await page.setInputFiles('input[type=file]', uploadFile);

    // Wait for the conversion result (the Download button only appears on success).
    await page.waitForSelector('button:has-text("Download")', { timeout: 30000 });
    await shot(page, '2-preview');

    // Confirm rendered Markdown made it into the DOM.
    const rendered = await page.locator('.markdown-body').innerText();
    console.log('--- rendered preview (first 200 chars) ---');
    console.log(rendered.slice(0, 200));

    // Toggle to the Raw view and screenshot that too.
    await page.click('button[role=tab]:has-text("Raw")');
    await page.waitForSelector('.markdown-raw');
    await shot(page, '3-raw');

    if (errors.length) {
      console.log('\nconsole errors:');
      errors.forEach((e) => console.log('  ' + e));
    } else {
      console.log('\nno console errors');
    }
    console.log('\nDRIVER OK');
  } catch (err) {
    console.error('DRIVER FAILED:', err.message);
    await shot(page, 'error').catch(() => {});
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
