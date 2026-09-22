//// Neoffice — added file (no upstream equivalent).
//// The variant selector: one row of chips per attribute, the price and the stock of the
//// chosen combination in the footer, a sold-out combination struck, and the gallery's
//// first picture following the chosen colour when the variants carry their own photo.
//// Runs on the first template product the catalogue offers; skips when there is none.

const {test, expect} = require('@playwright/test');

async function firstTemplateProduct(page) {
	await page.goto('/all-products');
	await page.waitForLoadState('networkidle');
	//// A template tile carries no wishlist heart and links to its page like any other.
	const links = await page
		.locator('.wsp-card--grid a[href*="/products/"]')
		.evaluateAll((as) => [...new Set(as.map((a) => a.getAttribute('href')))]);
	for (const route of links.slice(0, 12)) {
		await page.goto(route);
		await page.waitForLoadState('networkidle');
		if (await page.locator('#wsp-variants').count()) return route;
	}
	return null;
}

test.describe('Variants', () => {
	test('one row per attribute, the price and the stock follow the choice', async ({page}) => {
		const route = await firstTemplateProduct(page);
		test.skip(!route, 'no template product in the catalogue');
		const rows = page.locator('.wsp-variants__row');
		await expect(rows.first()).toBeVisible({timeout: 15_000});
		const rowCount = await rows.count();
		expect(rowCount, 'at least one attribute').toBeGreaterThan(0);

		//// Nothing chosen: no footer, no code on the button.
		await expect(page.locator('.variant-grid-footer')).toBeHidden();

		//// Choose, row by row, the first chip that is still available.
		for (let i = 0; i < rowCount; i++) {
			const chip = rows
				.nth(i)
				.locator('.wsp-variants__chip:not(.is-impossible):not(.is-unavailable)')
				.first();
			await chip.click();
			await expect(chip).toHaveClass(/is-selected/);
			await expect(chip).toHaveAttribute('aria-checked', 'true');
		}
		const footer = page.locator('.variant-grid-footer');
		await expect(footer).toBeVisible();
		const code = await footer.locator('.btn-add-to-cart').getAttribute('data-item-code');
		expect(code, 'the button carries the chosen variant code').toBeTruthy();
		await expect(footer.locator('.selected-variant-price')).not.toBeEmpty();
		await expect(footer.locator('.selected-variant-stock')).toContainText(/stock/i);

		//// A second click on the same chip clears the choice, and the footer with it.
		await rows.first().locator('.wsp-variants__chip.is-selected').click();
		await expect(footer).toBeHidden();
	});

	test('a sold-out combination is struck through, never hidden', async ({page}) => {
		const route = await firstTemplateProduct(page);
		test.skip(!route, 'no template product in the catalogue');
		await expect(page.locator('.wsp-variants__row').first()).toBeVisible({timeout: 15_000});
		//// A chip is struck relative to the OTHER rows' choice: walk the first row's values
		//// until one of them leaves a combination sold out.
		const firstRow = page
			.locator('.wsp-variants__row')
			.first()
			.locator('.wsp-variants__chip:not(.is-impossible)');
		const struck = page.locator('.wsp-variants__chip.is-unavailable');
		let found = (await struck.count()) > 0;
		for (let i = 0; i < (await firstRow.count()) && !found; i++) {
			await firstRow.nth(i).click();
			found = (await struck.count()) > 0;
		}
		test.skip(!found, 'every variant is in stock here');
		await expect(struck.first()).toBeVisible();
		await expect(struck.first()).toHaveAttribute('title', /.+/);
	});

	test('the picture follows the chosen colour', async ({page}) => {
		const route = await firstTemplateProduct(page);
		test.skip(!route, 'no template product in the catalogue');
		const swatches = page.locator('.wsp-variants__chip--swatch:not(.is-impossible)');
		test.skip((await swatches.count()) < 2, 'no attribute carries a photo per value');
		const firstPicture = page.locator('.wsp-gallery__img').filter({visible: true}).first();
		const before = await firstPicture.getAttribute('src');
		const target = swatches.nth(1);
		const expected = await target.locator('img').getAttribute('src');
		await target.click();
		await expect(firstPicture).toHaveAttribute('src', expected);
		expect(expected).not.toBe(before);
	});
});
