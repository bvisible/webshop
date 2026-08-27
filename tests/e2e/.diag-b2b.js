const {chromium} = require('@playwright/test');
const fs = require('fs'), os = require('os'), path = require('path');
for (const l of fs.readFileSync(path.join(os.homedir(), '.config/webshop-e2e.env'), 'utf8').split('\n')) {
  const m = l.match(/^([A-Z0-9_]+)=(.*)$/); if (m) process.env[m[1]] = m[2];
}
(async () => {
  const nav = await chromium.launch();
  const ctx = await nav.newContext({baseURL: process.env.WEBSHOP_E2E_URL, storageState: '.auth/session-b2b.json', locale: 'fr-CH'});
  const page = await ctx.newPage();
  await page.goto('/checkout_b2b');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(6000);

  console.log(JSON.stringify({
    url: page.url(),
    selects: await page.evaluate(() => [...document.querySelectorAll('select')].map(s => ({
      id: s.id, name: s.name, options: [...s.options].map(o => o.value).slice(0, 5), valeur: s.value }))),
    conteneur_livraison: await page.evaluate(() => {
      const c = document.querySelector('#shipping-methods-container');
      return c ? c.textContent.trim().slice(0, 120).replace(/\s+/g, ' ') : '(absent)';
    }),
    radios_adresse: await page.evaluate(() => [...document.querySelectorAll('input[type=radio]')].map(r => ({name: r.name, value: r.value, coche: r.checked}))),
    boutons: await page.evaluate(() => [...document.querySelectorAll('#b2b-checkout button')].map(b => ({
      texte: b.textContent.trim().slice(0, 30), classes: b.className.slice(0, 40), disabled: b.disabled }))),
  }, null, 2));
  await nav.close();
})();
