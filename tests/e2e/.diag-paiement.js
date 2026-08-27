const {chromium} = require('@playwright/test');
const fs = require('fs'), os = require('os'), path = require('path');
for (const l of fs.readFileSync(path.join(os.homedir(), '.config/webshop-e2e.env'), 'utf8').split('\n')) {
  const m = l.match(/^([A-Z0-9_]+)=(.*)$/); if (m) process.env[m[1]] = m[2];
}
(async () => {
  const nav = await chromium.launch();
  const page = await (await nav.newContext({baseURL: process.env.WEBSHOP_E2E_URL, locale: 'fr-CH'})).newPage();

  page.on('console', m => { if (m.type() === 'error') console.log('CONSOLE ERR:', m.text().slice(0, 200)); });
  page.on('response', async r => {
    if (/make_payment|create_payment_request|handle_payment_failure/.test(r.url())) {
      let corps = '';
      try { corps = (await r.text()).slice(0, 500); } catch (e) { corps = '(illisible)'; }
      console.log(`RESEAU ${r.status()} ${r.url().split('/').pop()} -> ${corps.replace(/\s+/g, ' ')}`);
    }
  });

  await page.request.post('/api/method/login', {form: {usr: process.env.WEBSHOP_E2E_USER, pwd: process.env.WEBSHOP_E2E_PASSWORD}});

  // Panier minimal
  const lire = async () => { const r = await page.request.post('/api/method/webshop.webshop.shopping_cart.cart.get_cart_quotation'); try { return JSON.parse(await r.text()).message; } catch { return null; } };
  let d = await lire();
  for (const l of (d && d.doc && d.doc.items) || []) {
    await page.request.post('/api/method/webshop.webshop.shopping_cart.cart.update_cart', {form: {item_code: l.item_code, qty: 0, ...(l.warehouse ? {warehouse: l.warehouse} : {})}});
  }
  await page.goto('/all-products'); await page.waitForLoadState('networkidle');
  const route = await page.evaluate(() => { const a = document.querySelector('a[href*="/products/"]'); return a ? new URL(a.href, location.origin).pathname.replace(/^\//,'') : null; });
  await page.goto('/' + route); await page.waitForLoadState('domcontentloaded');
  const code = await page.evaluate(() => document.querySelector('[data-item-code]')?.getAttribute('data-item-code'));
  await page.request.post('/api/method/webshop.webshop.shopping_cart.cart.update_cart', {form: {item_code: code, qty: 1}});

  await page.goto('/checkout'); await page.waitForLoadState('networkidle'); await page.waitForTimeout(4000);
  await page.locator('#step-address .next-step').click(); await page.waitForTimeout(7000);
  const radios = page.locator('#step-shipping input[type=radio]');
  if (await radios.count()) {
    const id = await radios.first().getAttribute('id');
    const lab = page.locator(`label[for="${(id||'').replace(/"/g,'\\"')}"]`);
    if (await lab.count()) await lab.first().click(); else await radios.first().check({force: true});
    await page.waitForTimeout(4000);
  }
  await page.locator('#step-shipping .next-step').click(); await page.waitForTimeout(12000);

  const tuile = page.locator('.payment-method-item').filter({hasText: /stripe/i}).first();
  await tuile.click(); await page.waitForTimeout(8000);
  await tuile.locator('#cardholder-name').fill('Test E2E');
  await tuile.locator('#cardholder-email').fill('test.e2e@example.com');
  const cadre = tuile.frameLocator('[name="card-element"] iframe').first();
  await cadre.locator('input[name="cardnumber"]').fill('4242424242424242');
  await cadre.locator('input[name="exp-date"]').fill('1228');
  await cadre.locator('input[name="cvc"]').fill('123');
  const lbl = tuile.locator('.form-check-label').first();
  if (await lbl.count()) await lbl.click();
  await page.waitForTimeout(1000);

  console.log('--- clic sur Payer ---');
  await tuile.locator('.btn-submit-payment:visible').first().click();
  await page.waitForTimeout(60000);
  console.log('URL finale:', page.url());
  await page.screenshot({path: '/tmp/apres-paiement.png'});
  await nav.close();
})();
