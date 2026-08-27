const {chromium} = require('@playwright/test');
const fs = require('fs'), os = require('os'), path = require('path');
for (const l of fs.readFileSync(path.join(os.homedir(), '.config/webshop-e2e.env'), 'utf8').split('\n')) {
  const m = l.match(/^([A-Z0-9_]+)=(.*)$/); if (m) process.env[m[1]] = m[2];
}
(async () => {
  const nav = await chromium.launch();
  const page = await (await nav.newContext({baseURL: process.env.WEBSHOP_E2E_URL, locale: 'fr-CH', viewport: {width: 1280, height: 900}})).newPage();
  await page.request.post('/api/method/login', {form: {usr: process.env.WEBSHOP_E2E_B2B_USER, pwd: process.env.WEBSHOP_E2E_PASSWORD}});
  await page.request.post('/api/method/webshop.webshop.shopping_cart.cart.update_cart', {form: {item_code: 'EAP723', qty: 2}});
  await page.goto('/checkout_b2b');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(8000);
  const infos = await page.evaluate(() => ({
    titre: document.querySelector('h1')?.textContent.trim(),
    texte_entete: (document.querySelector('#b2b-checkout')?.textContent || '').replace(/\s+/g,' ').slice(0, 300),
    adresse_affichee: !!document.querySelector('#b2b-checkout .address-container, #b2b-checkout [data-address-name]'),
    livraisons: [...document.querySelectorAll('#shipping-methods-container input[type=radio]')].map(r => r.value),
    bouton: (() => { const b = document.querySelector('.btn-place-order'); return b ? {texte: b.textContent.trim(), disabled: b.disabled} : null; })(),
    recap: (document.querySelector('.order-summary, #order-summary')?.textContent || '').replace(/\s+/g,' ').slice(0, 120),
  }));
  console.log(JSON.stringify(infos, null, 2));
  await page.screenshot({path: '/tmp/b2b.png', fullPage: false});
  await nav.close();
})();
