//// Neoffice — added file (shop assistant, no upstream equivalent).
// The chat bubble, as a visitor and as a signed-in customer. The answers come
// from the shop's real model, so the one exchange this spec makes allows the
// model its time and asserts on what cannot vary: that an answer came, from
// the assistant, in words.
const { test, expect } = require('@playwright/test');

async function assistantEnabled(page) {
	const r = await page.request.get('/api/method/webshop.webshop.assistant.api.get_config');
	if (!r.ok()) return false;
	const body = await r.json();
	return Boolean(body && body.message && body.message.enabled);
}

test.describe('Assistant de la boutique', () => {
	test.beforeEach(async ({ page }) => {
		test.skip(!(await assistantEnabled(page)), "l'assistant n'est pas activé sur cette boutique");
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
	});

	test('la pastille est là et s’ouvre sur un accueil', async ({ page }) => {
		const bubble = page.locator('#wsh-assistant .wsh-assistant__bubble');
		await expect(bubble).toBeVisible();
		await bubble.click();
		const panel = page.locator('#wsh-assistant .wsh-assistant__panel');
		await expect(panel).toBeVisible();
		await expect(panel.locator('.wsh-assistant__msg--assistant').first()).toContainText(/Bonjour/);
		await expect(panel.locator('.wsh-assistant__chip')).toHaveCount(4);
	});

	test('une question reçoit une réponse de l’assistant', async ({ page }) => {
		test.setTimeout(120_000);
		await page.locator('#wsh-assistant .wsh-assistant__bubble').click();
		await page.locator('#wsh-assistant .wsh-assistant__input').fill('Quels sont vos horaires ?');
		await page.locator('#wsh-assistant .wsh-assistant__send').click();
		await expect(page.locator('#wsh-assistant .wsh-assistant__msg--user')).toHaveCount(1);
		//// The greeting is the first assistant bubble; the answer is the second.
		const answer = page.locator('#wsh-assistant .wsh-assistant__msg--assistant').nth(1);
		await expect(answer).toBeVisible({ timeout: 90_000 });
		const text = (await answer.innerText()).trim();
		expect(text.length, 'une réponse vide').toBeGreaterThan(10);
		expect(text, 'la phrase de repli').not.toMatch(/Je n’arrive pas à répondre|Je n'arrive pas à répondre/);
	});

	test('un visiteur non connecté n’a pas de prénom dans l’accueil', async ({ page, browserName }, testInfo) => {
		test.skip(testInfo.project.name !== 'invite', 'projet visiteur seulement');
		await page.locator('#wsh-assistant .wsh-assistant__bubble').click();
		const greeting = await page.locator('#wsh-assistant .wsh-assistant__msg--assistant').first().innerText();
		expect(greeting).toMatch(/^Bonjour !/);
	});

	test('le lien « Parler à l’équipe » ouvre un formulaire qui part sans le modèle', async ({ page }, testInfo) => {
		await page.locator('#wsh-assistant .wsh-assistant__bubble').click();
		await page.locator('#wsh-assistant .wsh-assistant__team').click();
		const card = page.locator('#wsh-assistant .wsh-assistant__leave');
		await expect(card).toBeVisible();
		await expect(card.locator('.wsh-assistant__leave-text')).toBeVisible();
		//// A visitor has to say where to answer; a signed-in customer is written to at the session's address.
		if (testInfo.project.name === 'invite') await expect(card.locator('.wsh-assistant__leave-email')).toHaveCount(1);
		if (testInfo.project.name === 'client') await expect(card.locator('.wsh-assistant__leave-email')).toHaveCount(0);
		//// Nothing is sent: the message would reach the real team of the target shop.
		await card.locator('.wsh-assistant__leave-cancel').click();
		await expect(card).toHaveCount(0);
	});

	test('un client connecté est salué par son prénom', async ({ page }, testInfo) => {
		test.skip(testInfo.project.name !== 'client', 'projet client seulement');
		await page.locator('#wsh-assistant .wsh-assistant__bubble').click();
		const greeting = await page.locator('#wsh-assistant .wsh-assistant__msg--assistant').first().innerText();
		expect(greeting).toMatch(/^Bonjour \S+ !/);
	});
});
