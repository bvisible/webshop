//// Neoffice — added file (shop assistant, no upstream equivalent).
//// The chat bubble, as a visitor and as a signed-in customer. The answers come
//// from the shop's real model, so the one exchange this spec makes allows the
//// model its time and asserts on what cannot vary: that an answer came, from
//// the assistant, in words.
////
//// The greetings matched below are the shop's own UI text, which the fleet
//// serves in French: the words have to be French for the assertion to mean
//// anything. Everything else in this file is English.
const {test, expect} = require('@playwright/test');

async function assistantEnabled(page) {
	const r = await page.request.get('/api/method/webshop.webshop.assistant.api.get_config');
	if (!r.ok()) return false;
	const body = await r.json();
	return Boolean(body && body.message && body.message.enabled);
}

test.describe('Shop assistant', () => {
	test.beforeEach(async ({page}) => {
		test.skip(!(await assistantEnabled(page)), 'the assistant is switched off on this shop');
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		//// Neoffice — a conversation is resumed for 30 days, so without this the panel opens
		//// on the previous run's turns and every count assertion below is off by that history.
		await page.evaluate(
			() =>
				new Promise((resolve) => {
					frappe.call({
						method: 'webshop.webshop.assistant.api.reset',
						type: 'POST',
						args: {},
						callback: resolve,
						error: resolve,
					});
				})
		);
		await page.reload();
		await page.waitForLoadState('networkidle');
	});

	test('the bubble is there and opens on a greeting', async ({page}) => {
		const bubble = page.locator('#wsh-assistant .wsh-assistant__bubble');
		await expect(bubble).toBeVisible();
		await bubble.click();
		const panel = page.locator('#wsh-assistant .wsh-assistant__panel');
		await expect(panel).toBeVisible();
		await expect(panel.locator('.wsh-assistant__msg--assistant').first()).toContainText(/Bonjour/);
		await expect(panel.locator('.wsh-assistant__chip')).toHaveCount(4);
	});

	test('a question gets an answer from the assistant', async ({page}) => {
		test.setTimeout(120_000);
		await page.locator('#wsh-assistant .wsh-assistant__bubble').click();
		await page.locator('#wsh-assistant .wsh-assistant__input').fill('Quels sont vos horaires ?');
		await page.locator('#wsh-assistant .wsh-assistant__send').click();
		await expect(page.locator('#wsh-assistant .wsh-assistant__msg--user')).toHaveCount(1);
		//// The greeting is the first assistant bubble; the answer is the second.
		const answer = page.locator('#wsh-assistant .wsh-assistant__msg--assistant').nth(1);
		await expect(answer).toBeVisible({timeout: 90_000});
		const text = (await answer.innerText()).trim();
		expect(text.length, 'an empty answer').toBeGreaterThan(10);
		expect(text, 'the fallback sentence').not.toMatch(
			/Je n’arrive pas à répondre|Je n'arrive pas à répondre/
		);
	});

	test('a signed-out visitor has no first name in the greeting', async ({page}, testInfo) => {
		test.skip(testInfo.project.name !== 'guest', 'visitor project only');
		await page.locator('#wsh-assistant .wsh-assistant__bubble').click();
		const greeting = await page
			.locator('#wsh-assistant .wsh-assistant__msg--assistant')
			.first()
			.innerText();
		expect(greeting).toMatch(/^Bonjour !/);
	});

	test('the "talk to the team" link opens a form that goes out without the model', async ({page}, testInfo) => {
		await page.locator('#wsh-assistant .wsh-assistant__bubble').click();
		await page.locator('#wsh-assistant .wsh-assistant__team').click();
		const card = page.locator('#wsh-assistant .wsh-assistant__leave');
		await expect(card).toBeVisible();
		await expect(card.locator('.wsh-assistant__leave-text')).toBeVisible();
		//// A visitor has to say where to answer; a signed-in customer is written to
		//// at the session's address.
		if (testInfo.project.name === 'guest')
			await expect(card.locator('.wsh-assistant__leave-email')).toHaveCount(1);
		if (testInfo.project.name === 'customer')
			await expect(card.locator('.wsh-assistant__leave-email')).toHaveCount(0);
		//// Nothing is sent: the message would reach the real team of the target shop.
		await card.locator('.wsh-assistant__leave-cancel').click();
		await expect(card).toHaveCount(0);
	});

	test('a signed-in customer is greeted by their first name', async ({page}, testInfo) => {
		test.skip(testInfo.project.name !== 'customer', 'customer project only');
		await page.locator('#wsh-assistant .wsh-assistant__bubble').click();
		const greeting = await page
			.locator('#wsh-assistant .wsh-assistant__msg--assistant')
			.first()
			.innerText();
		expect(greeting).toMatch(/^Bonjour \S+ !/);
	});
});
