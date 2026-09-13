//// Neoffice — added file (no upstream equivalent).
//// The variant selector: one row of chips per attribute, the price and the stock of the
//// chosen combination in the footer, a sold-out combination struck, and the gallery's
//// first picture following the chosen colour when the variants carry their own photo.
//// Runs on the first template product the catalogue offers; skips when there is none.

const {test, expect} = require('@playwright/test');

async function premierModele(page) {
	await page.goto('/all-products');
	await page.waitForLoadState('networkidle');
	//// A template tile carries no wishlist heart and links to its page like any other.
	const liens = await page.locator('.wsp-card--grid a[href*="/products/"]').evaluateAll((as) => [...new Set(as.map((a) => a.getAttribute('href')))]);
	for (const route of liens.slice(0, 12)) {
		await page.goto(route);
		await page.waitForLoadState('networkidle');
		if (await page.locator('#wsp-variants').count()) return route;
	}
	return null;
}

test.describe('Variantes', () => {
	test('une ligne par attribut, le prix et le stock suivent le choix', async ({page}) => {
		const route = await premierModele(page);
		test.skip(!route, 'aucun modèle à déclinaisons dans le catalogue');
		const rows = page.locator('.wsp-variants__row');
		await expect(rows.first()).toBeVisible({timeout: 15_000});
		const nRows = await rows.count();
		expect(nRows, 'au moins un attribut').toBeGreaterThan(0);

		//// Nothing chosen: no footer, no code on the button.
		await expect(page.locator('.variant-grid-footer')).toBeHidden();

		//// Choose, row by row, the first chip that is still available.
		for (let i = 0; i < nRows; i++) {
			const chip = rows.nth(i).locator('.wsp-variants__chip:not(.is-impossible):not(.is-unavailable)').first();
			await chip.click();
			await expect(chip).toHaveClass(/is-selected/);
			await expect(chip).toHaveAttribute('aria-checked', 'true');
		}
		const footer = page.locator('.variant-grid-footer');
		await expect(footer).toBeVisible();
		const code = await footer.locator('.btn-add-to-cart').getAttribute('data-item-code');
		expect(code, 'le bouton porte le code de la déclinaison choisie').toBeTruthy();
		await expect(footer.locator('.selected-variant-price')).not.toBeEmpty();
		await expect(footer.locator('.selected-variant-stock')).toContainText(/stock/i);

		//// A second click on the same chip clears the choice, and the footer with it.
		await rows.first().locator('.wsp-variants__chip.is-selected').click();
		await expect(footer).toBeHidden();
	});

	test('une combinaison épuisée est barrée, jamais cachée', async ({page}) => {
		const route = await premierModele(page);
		test.skip(!route, 'aucun modèle à déclinaisons dans le catalogue');
		await expect(page.locator('.wsp-variants__row').first()).toBeVisible({timeout: 15_000});
		//// A chip is struck relative to the OTHER rows' choice: walk the first row's values
		//// until one of them leaves a combination sold out.
		const premiere = page.locator('.wsp-variants__row').first().locator('.wsp-variants__chip:not(.is-impossible)');
		const barree = page.locator('.wsp-variants__chip.is-unavailable');
		let trouvee = (await barree.count()) > 0;
		for (let i = 0; i < (await premiere.count()) && !trouvee; i++) {
			await premiere.nth(i).click();
			trouvee = (await barree.count()) > 0;
		}
		test.skip(!trouvee, 'toutes les déclinaisons sont en stock ici');
		await expect(barree.first()).toBeVisible();
		await expect(barree.first()).toHaveAttribute('title', /.+/);
	});

	test('la photo suit la couleur choisie', async ({page}) => {
		const route = await premierModele(page);
		test.skip(!route, 'aucun modèle à déclinaisons dans le catalogue');
		const swatches = page.locator('.wsp-variants__chip--swatch:not(.is-impossible)');
		test.skip((await swatches.count()) < 2, 'aucun attribut avec des photos par valeur');
		const premiere = page.locator('.wsp-gallery__img').filter({visible: true}).first();
		const avant = await premiere.getAttribute('src');
		const cible = swatches.nth(1);
		const attendu = await cible.locator('img').getAttribute('src');
		await cible.click();
		await expect(premiere).toHaveAttribute('src', attendu);
		expect(attendu).not.toBe(avant);
	});
});
