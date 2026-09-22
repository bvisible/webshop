//// Neoffice — added file (no upstream equivalent).
//// The catalogue and the product page, including the layout fixes of 2026-08
//// that were until now only ever checked by eye.

const {test, expect} = require('@playwright/test');
const {signIn, firstBuyableItem, readQuotation} = require('../fixtures/shop');

//// On a phone the filters live in a drawer behind the "Filters" button: open it before
//// touching a filter. A no-op on a wide screen, where the column is always there.
async function closeFilters(page) {
	const close = page.locator('#closeFilterButton');
	if (await close.isVisible()) {
		await close.click();
		await expect(page.locator('#product-filters')).toBeHidden();
	}
}

async function openFilters(page) {
	const column = page.locator('#product-filters');
	if (await column.isVisible()) return;
	const button = page.locator('#filterButton');
	if (await button.isVisible()) {
		await button.click();
		await expect(column).toBeVisible();
	}
}

test.describe('Catalogue', () => {
	//// A product that carries a video (Website Item → Videos) wears a play mark on its
	//// tile, and its gallery plays it in the lightbox — a hosted file through the
	//// browser's own player. Skips when the shop under test has no such product.
	test('a product with a video wears a badge and plays it in the lightbox', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		const tile = page.locator('.wsp-card--grid:has(.wsp-card__play)').first();
		test.skip((await tile.count()) === 0, 'no product with a video on this shop');
		await tile.locator('a[href*="/products/"]').first().click();
		await page.waitForLoadState('networkidle');
		//// the gallery draws a layout for a wide screen and a strip for a phone, one of
		//// them hidden
		const videoTile = page
			.locator('.wsp-gallery__tile--video, .wsp-gallery__slide--video')
			.filter({visible: true})
			.first();
		await expect(videoTile, 'the gallery must show a video tile').toBeVisible();
		await expect(videoTile.locator('.wsp-gallery__play')).toBeVisible();
		await videoTile.click();
		const player = page.locator('.image-zoom-view .zoom-video');
		await expect(player, 'the lightbox must hold a player').toBeVisible();
		expect(
			await page.locator('.image-zoom-view').evaluate((e) => e.parentElement.tagName)
		).toBe('BODY');
		await page.keyboard.press('Escape');
		expect(
			await page.locator('.image-zoom-view .zoom-image-container').evaluate((e) => e.children.length),
			'the player must be removed on close'
		).toBe(0);
	});

	test('the shop lists products', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		//// The theme renders thumbnails as generic .card elements: the only stable
		//// landmark is the link to the product page.
		const cards = page.locator('a[href*="/products/"]');
		expect(await cards.count(), 'the shop must show products').toBeGreaterThan(0);
	});

	test('a single visible heading on the catalogue', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		expect(await countVisibleHeadings(page), 'the double heading is back').toBe(1);
	});

	//// The one product card (templates/includes/product_card.html): every tile carries
	//// its picture, its name and its price through the same hooks, whatever the page.
	test('every card carries a picture, a name and a price', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		const cards = page.locator('.wsp-card--grid');
		expect(await cards.count(), 'no catalogue card at all').toBeGreaterThan(0);
		const first = cards.first();
		await expect(first.locator('.wsp-card__media')).toBeVisible();
		await expect(first.locator('.wsp-card__title')).toBeVisible();
		await expect(first.locator('.wsp-card__title')).not.toHaveText(/^\s*$/);
		//// a gift card shows no price; every other tile does
		const price = first.locator('.wsp-card__price');
		if (await price.count()) await expect(price).toContainText(/\d/);
	});
});

test.describe('Filters', () => {
	//// The second-hand toggle sits right after the discount one and works the same way:
	//// a checkbox, a per-visitor preference, and only used units left in the listing.
	test('the second-hand toggle follows the discount one and keeps only used units', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		const toggle = page.locator('#second-hand-filters');
		test.skip((await toggle.count()) === 0, 'no used unit published on this shop');
		await openFilters(page);
		const blocks = await page
			.locator('#product-filters .filter-block')
			.evaluateAll((els) => els.map((e) => e.id));
		expect(blocks.indexOf('second-hand-filters'), 'right after the discount block').toBe(
			blocks.indexOf('discount-filters') + 1
		);
		await page.locator('#showSecondHandOnly').check();
		await page.waitForLoadState('networkidle');
		await expect(page.locator('.active-filter-badge[data-filter-type="second_hand"]')).toBeVisible();
		const cards = page.locator('.wsp-card--grid');
		await expect(cards.first()).toBeVisible();
		const total = await cards.count();
		const used = await page.locator('.wsp-card--grid:has(.wsp-card__badge--condition)').count();
		expect(used, 'every remaining tile is a used unit').toBe(total);
		//// The chip's cross clears the toggle.
		//// the chip sits above the listing, outside the drawer: on a phone, close the
		//// drawer first
		await closeFilters(page);
		await page
			.locator('.active-filter-badge[data-filter-type="second_hand"]')
			.filter({visible: true})
			.first()
			.click();
		await page.waitForLoadState('networkidle');
		await expect(page.locator('#showSecondHandOnly')).not.toBeChecked();
		await page.evaluate(() => sessionStorage.removeItem('second_hand_filter_checked'));
	});

	//// "Clear all" and the sidebar's counter only exist under a filter; "Clear all" clears
	//// the toggles too, and a toggle lasts for the visit, not for the next one (2026-09-14).
	test('"Clear all" shows only under a filter, clears the toggles, and a toggle does not survive the visit', async ({
		page,
	}) => {
		await page.goto('/all-products');
		await page.evaluate(() => sessionStorage.clear());
		await page.reload();
		await page.waitForLoadState('networkidle');
		const clearAll = page.locator('#product-filters .clear-filters');
		await expect(clearAll).toBeHidden();
		await expect(page.locator('#results-count-live')).toHaveText('');
		const checkbox = page.locator('#showDiscountOnly, #showSecondHandOnly').first();
		test.skip((await checkbox.count()) === 0, 'neither discount nor used unit on this shop');
		await openFilters(page);
		await checkbox.check();
		await openFilters(page);
		await page.waitForLoadState('networkidle');
		await expect(clearAll).toBeVisible();
		await expect(page.locator('#results-count-live')).toContainText(/\d/);
		//// a later visit (another tab) starts clean
		const otherTab = await page.context().newPage();
		await otherTab.goto('/all-products');
		await otherTab.waitForLoadState('networkidle');
		await expect(otherTab.locator('#showDiscountOnly, #showSecondHandOnly').first()).not.toBeChecked();
		await expect(otherTab.locator('#product-filters .clear-filters')).toBeHidden();
		await otherTab.close();
		//// "Clear all" empties the toggles of this visit
		await openFilters(page);
		await clearAll.click();
		await page.waitForLoadState('networkidle');
		await expect(page.locator('#product-filters .clear-filters')).toBeHidden();
		await expect(page.locator('#showDiscountOnly, #showSecondHandOnly').first()).not.toBeChecked();
	});

	//// The quick order is offered next to the search box to whoever may use it.
	test('the quick order is offered next to the search box', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		const link = page.locator('.toolbar .wsp-quick-order-link');
		await expect(link).toBeVisible();
		await expect(link).toHaveAttribute('href', '/quick-order');
		await link.click();
		await page.waitForURL(/quick-order/);
		await expect(page.locator('.wsh-qo__input')).toBeVisible();
	});

	//// On any screen, the price slider's handles sit inside the filter column (or the drawer).
	test("the price slider's handles stay inside the filter column", async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		const track = page.locator('#price-slider-track');
		test.skip((await track.count()) === 0, 'no price filter on this shop');
		await openFilters(page);
		const column = await page.locator('#product-filters').boundingBox();
		for (const handle of ['#price-slider-min', '#price-slider-max']) {
			const box = await page.locator(handle).boundingBox();
			expect(box.x, `${handle} does not stick out on the left`).toBeGreaterThanOrEqual(column.x - 1);
			expect(
				box.x + box.width,
				`${handle} does not stick out on the right`
			).toBeLessThanOrEqual(column.x + column.width + 1);
		}
	});

	//// The price slider: a drag moves the handle, rewrites the input and filters the
	//// listing; the handles stay inside the sidebar; a second drag after a filter still
	//// obeys (the handlers used to stack up on every filter change).
	test('the price slider drags, stays in the column and survives a filtering', async ({page}, testInfo) => {
		//// A drag of the mouse is not a finger: the handles listen to touch events on a
		//// phone, which Playwright's mouse never sends. The containment is checked on a
		//// phone by the test above; the drag, on a wide screen.
		test.skip(
			Boolean(testInfo.project.use && testInfo.project.use.hasTouch),
			'a mouse drag does not simulate a finger'
		);
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		const track = page.locator('#price-slider-track');
		test.skip((await track.count()) === 0, 'no price filter on this shop');
		await openFilters(page);
		const column = await page.locator('#product-filters').boundingBox();
		const max = page.locator('#price-slider-max');
		const maxBox = await max.boundingBox();
		expect(maxBox.x + maxBox.width, 'the right handle fits in the column').toBeLessThanOrEqual(
			column.x + column.width + 1
		);
		const rail = await track.boundingBox();
		const before = Number(await page.locator('#price-max').inputValue());
		await max.hover();
		await page.mouse.down();
		await page.mouse.move(rail.x + rail.width * 0.5, rail.y + rail.height / 2, {steps: 8});
		await page.mouse.up();
		await page.waitForLoadState('networkidle');
		await openFilters(page);
		const after = Number(await page.locator('#price-max').inputValue());
		expect(after, 'the maximum went down').toBeLessThan(before);
		expect(page.url()).toContain('price_range');
		//// A second drag, after the listing re-rendered: one handler, one movement.
		const rail2 = await track.boundingBox();
		const max2 = page.locator('#price-slider-max');
		await max2.hover();
		await page.mouse.down();
		await page.mouse.move(rail2.x + rail2.width * 0.9, rail2.y + rail2.height / 2, {steps: 8});
		await page.mouse.up();
		await page.waitForLoadState('networkidle');
		const again = Number(await page.locator('#price-max').inputValue());
		expect(again, 'the maximum went back up').toBeGreaterThan(after);
	});
});

test.describe('Product page', () => {
	test.beforeEach(async ({page}) => {
		const item = await firstBuyableItem(page);
		test.skip(!item, 'no published article on this site');
		await page.goto('/' + item.route);
		await page.waitForLoadState('networkidle');
	});

	//// The theme already renders the title in its header; the product template
	//// used to add a second one. Both still exist in the DOM — one is
	//// hidden — so the test counts what is VISIBLE, not what exists.
	test('a single visible heading', async ({page}) => {
		expect(await countVisibleHeadings(page), 'the double heading is back').toBe(1);
	});

	test('the price is shown', async ({page}) => {
		const price = page.locator('.product-price, [itemprop="price"]').first();
		await expect(price).toBeVisible();
		await expect(price).toContainText(/\d/);
	});

	test('the add-to-cart button is there and can be pressed', async ({page}) => {
		const button = page.locator('.btn-add-to-cart').first();
		await expect(button).toBeVisible();
		await expect(button).toBeEnabled();
	});

	//// The promises (free delivery from, delivery time, returns) come from Webshop
	//// Settings; a shop that set none prints no block at all, so the test can only say
	//// "when there is a block, it says something".
	test("the shop's promises read under the button", async ({page}) => {
		const block = page.locator('.wsp-promises');
		test.skip((await block.count()) === 0, 'no promise configured on this site');
		await expect(block).toBeVisible();
		const lines = block.locator('.wsp-promises__item');
		expect(await lines.count()).toBeGreaterThan(0);
		await expect(lines.first()).not.toHaveText(/^\s*$/);
	});

	test('a photo opens the zoom, Escape closes it', async ({page}) => {
		const image = page.locator('.product-image img').filter({visible: true}).first();
		test.skip((await image.count()) === 0, 'product with no picture');
		await image.click();
		const zoom = page.locator('.image-zoom-view');
		await expect(zoom).toBeVisible();
		await expect(zoom.locator('.zoom-image-container img')).toBeVisible();
		await page.keyboard.press('Escape');
		await expect(zoom).toBeHidden();
	});

	test('the description is an open fold, the others unfold', async ({page}) => {
		const folds = page.locator('details.wsp-acc');
		test.skip((await folds.count()) === 0, 'product with neither description nor specs');
		const first = folds.first();
		await expect(first).toHaveJSProperty('open', true);
		//// Pin the fold by index: a `:not([open])` locator stops matching the fold the
		//// moment it opens and silently moves on to the next closed one.
		const closed = await folds.evaluateAll((els) =>
			els.map((e, i) => (e.open ? -1 : i)).filter((i) => i >= 0)
		);
		if (closed.length) {
			const shut = folds.nth(closed[0]);
			await shut.locator('summary').click();
			await expect(shut).toHaveJSProperty('open', true);
		}
	});

	//// The empty reviews block must not take up screen space just to say "0 reviews".
	//// The wording matched is the shop's own UI text, in French on the fleet.
	test('the empty reviews block shows no pointless zero', async ({page}) => {
		const block = page.locator('.reviews-section, #reviews');
		if ((await block.count()) === 0) return; // no block: as expected
		if (!(await block.first().isVisible())) return; // hidden: as expected
		await expect(block.first()).not.toHaveText(/^\s*0\s*avis\s*$/i);
	});

	test('the product picture really loads', async ({page}) => {
		//// The gallery draws one layout for a wide screen and a swipe strip for a phone;
		//// the other is in the DOM but hidden. The picture to check is the visible one.
		const image = page
			.locator('.product-image img, .website-image img, img.product-image')
			.filter({visible: true})
			.first();
		if ((await image.count()) === 0) test.skip(true, 'product with no picture');
		await expect(image).toBeVisible();
		//// naturalWidth = 0: the tag is there but the file failed to load.
		expect(await image.evaluate((i) => i.naturalWidth), 'broken picture').toBeGreaterThan(0);
	});
});

test.describe('Adding to the cart', () => {
	test('adding an article increments the cart', async ({page}) => {
		await signIn(page);
		const item = await firstBuyableItem(page);
		test.skip(!item, 'no published article');

		await page.goto('/' + item.route);
		await page.waitForLoadState('networkidle');

		const before = await cartQuantity(page);
		await page.locator('.btn-add-to-cart').first().click();
		//// Adding is asynchronous: wait for the total, not an arbitrary delay.
		await expect
			.poll(async () => cartQuantity(page), {timeout: 20_000, message: 'the cart did not move'})
			.toBeGreaterThan(before);
	});
});

/** Headings that actually occupy space on screen. */
async function countVisibleHeadings(page) {
	return page.evaluate(
		() =>
			[...document.querySelectorAll('h1')].filter((h) => {
				const cs = getComputedStyle(h);
				return (
					cs.display !== 'none' && cs.visibility !== 'hidden' && h.getBoundingClientRect().height > 0
				);
			}).length
	);
}

//// Read over HTTP, not through page.evaluate: clicking "add to cart" navigates
//// on some themes, and a frappe.call started just before that dies with
//// "Execution context was destroyed" — an error about the test harness, blamed
//// on the shop.
async function cartQuantity(page) {
	const quotation = await readQuotation(page);
	const lines = (quotation && quotation.doc && quotation.doc.items) || [];
	return lines.reduce((sum, l) => sum + (l.qty || 0), 0);
}
