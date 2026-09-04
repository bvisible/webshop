<!-- //// Neoffice — added file (no upstream equivalent). -->

# Neoffice fork markers — what carries no comment

`bvisible/webshop` diverges from `frappe/webshop`. Every change we made to code
that is not ours carries a `//// Neoffice` comment saying **why**, so that
`grep -rn "////"` maps the whole divergence at the next upstream merge.

This file is the other half of that map: **what cannot carry a comment** — JSON,
compiled catalogues, bundle entry points, images — plus the whitespace-only
divergences no marker can sit on.

## Base of the divergence

| | |
|---|---|
| our branch | `bvisible/webshop` `version-15` |
| divergence base | `1a5239d4482800b8fe1cb7d88c4ea0d9e837a03e` — tip of **`frappe/webshop` `develop`** (2026-06-05, "fix: bad import caused due to erpnext refactor (#362)"), fully contained in our branch |
| our commits since | ~494 |

Careful: the branch is called `version-15` but its content is upstream
**`develop`**, plus upstream's `version-15` backport line (whose last commit here
is `6fc2573eb8`, 2025-02-19), plus our work. `git merge-base origin/version-15
upstream/version-15` therefore answers `6fc2573eb8` — 2025-02-19, sixteen months
before the real divergence point. Use the `develop` tip above.

---

## webshop

### DocType / Web Form / Workspace JSON — files we ADD

No upstream equivalent; the whole file is ours.

| file | what it is | commit |
|---|---|---|
| `webshop/webshop/doctype/webshop_payment_method/webshop_payment_method.json` | child table of the checkout tiles: one row per method offered, with its gateway, template path and order | `3bc2d836f1` (2025-02-11), then `5a94882904`, `6dd98db146`, `cb8104c7bd`, `4cfd8ca287` |
| `webshop/webshop/doctype/webshop_trust_item/webshop_trust_item.json` | child table of the trust badges shown in the buy box | `02775e7eaf` (2026-07-06) |
| `webshop/webshop/doctype/gift_card_amount/gift_card_amount.json` | child table of the face values a shop offers for its gift cards | `3bc2d836f1` (2025-02-11) |
| `webshop/webshop/doctype/b2b_customer_group/b2b_customer_group.json` | child table of the customer groups routed to the B2B tunnel | `48e2708353` (2025-03-13) |
| `webshop/webshop/doctype/frequently_bought_together/frequently_bought_together.json` | pairs computed nightly from past orders | `3c1e847e26` (2025-06-24) |
| `webshop/webshop/doctype/cross_sell_offer/cross_sell_offer.json` | cross-sell / order-bump offers, carried by a generated Pricing Rule | `8c29208cca` (2026-09-03) |
| `webshop/webshop/doctype/purchase_follow_up/purchase_follow_up.json` + `_step`, `_entry`, `_log` | per-product purchase follow-up e-mails: the campaign, its steps, the enrolled customers, what was sent | `5d19e3fed9` (2026-09-03) |
| `webshop/webshop/doctype/abandoned_cart_reminder/abandoned_cart_reminder.json` | abandoned-cart reminders | `5d19e3fed9` (2026-09-03) |
| `webshop/webshop/doctype/webshop_warehouse_source/webshop_warehouse_source.json`, `website_item_warehouse_source/website_item_warehouse_source.json` | multi-warehouse: the shop's sources, and the per-product override | `5bf2e88a1b` (2026-08-25), `98bdb60ccf` (2026-08-26) |
| `webshop/webshop/doctype/webshopsi_settings/webshopsi_settings.json`, `webshopsi_country/webshopsi_country.json`, `webshopsi_invoice_installments/webshopsi_invoice_installments.json` | the "Facture" (pay-on-invoice) method, folded in from the standalone `webshopsi_integration` app | `662c26b650` (2026-05-26) |
| `webshop/webshop/workspace/webshop/webshop.json` | the "Webshop" desk workspace — a **root** page of the Website module, so the Neoffice sidebar lists it | `86e2609b57`, `01c6358b19` (2026-09-03) |

### DocType JSON — upstream files we MODIFY

These are the ones a merge will conflict on. Fields listed are candidates for
Custom Fields if we ever want to shrink the divergence.

**`webshop/webshop/doctype/website_item/website_item.json`**
(`3bc2d836f1` 2025-02-11 · `31feefcae6` 2026-04-19 · `5bf2e88a1b` 2026-08-25 · `d984eff855` 2026-09-03)
- added: `is_gift_card`; `item_condition`, `condition_grade`, `condition_of_item`,
  `condition_details` (second-hand goods, the /occasions page);
  `image_focus` + `section_break_qjfe` (per-item image focus point, so a cover-fit
  card does not cut a face); `warehouse_sources_mode`,
  `additional_warehouse_sources` (multi-warehouse override).
- removed: `column_break_27`, `column_break_11` — layout only, dropped when the
  sections above were inserted.
- `field_order` re-shuffled accordingly.

**`webshop/webshop/doctype/webshop_settings/webshop_settings.json`** (31 commits)
- **Structure**: the single was re-cut into five tabs — `tab_general`,
  `tab_filters`, `tab_cart`, `tab_features`, `tab_emails` (+ `tab_advanced`) —
  because it had become one unreadable column (`2363401845`, 2025-12-15).
  `field_order` is therefore fully rewritten: **expect a conflict here at the
  merge and resolve by re-applying upstream's new fields into our tabs**, never
  by taking upstream's `field_order` whole.
- **Added, by feature**: listing (`default_view_type`, `default_product_sort`,
  `enable_infinite_scroll`, `enable_tag_filters`, `enable_price_filter`,
  `enable_stock_filter`, `stock_filter_default_checked`, `compare_at_price_list`,
  `category_order_section`/`category_order_html`); images
  (`product_image_section`, `product_image_fit`, `product_image_aspect_ratio`);
  cart & checkout (`enable_guest_cart`, `guest_customer`, `enable_checkout_page`,
  `payment_methods_section`, `payment_methods`, `quotation_terms`,
  `checkout_cgv`, `hide_currency_symbol_in_shop`); gift cards
  (`gift_cards_section`, `enable_gift_cards`, `gift_card_template`,
  `enable_custom_amount`, `gift_card_amounts`, `number_of_valid_months`,
  `gift_card_notification`); loyalty (`loyalty_program_section`,
  `enable_loyalty_points`, `loyalty_program`, `show_loyalty_points_for_guests`,
  `loyalty_points_conversion_text`, `loyalty_points_earned_text`); B2B
  (`activate_b2b_checkout`, `b2b_customer_group`); recommendations
  (`enable_frequently_bought_together`); SEO (`sitemap_section`, `sitemap_info`,
  `sitemap_last_generated`, `regenerate_sitemap`); maintenance
  (`maintenance_mode_section`, `maintenance_website`, `maintenance_webshop`,
  `redirect_to_login`, `maintenance_message`, `maintenance_end_time`,
  `allow_system_users_during_maintenance`); trust badges
  (`trust_badges_section`, `trust_items`); multi-warehouse
  (`multi_warehouse_section`, `enable_multi_warehouse`,
  `enable_supplier_procurement`, `procurement_mode`, `warehouse_sources_section`,
  `warehouse_sources`, `reserve_stock_on_receipt`, `delivery_holiday_list`);
  e-mails (`abandoned_cart_section` + its delays/template/incentive fields,
  `follow_up_section`, `enable_purchase_follow_ups`, `follow_up_audience`,
  `follow_up_status`, `follow_up_note`).
- **Removed**: `search_index_fields`, `item_search_settings_section`,
  `is_redisearch_loaded`, `redisearch_warning`, `is_redisearch_enabled` —
  RediSearch was disabled in favour of plain SQL search (`c54680b459` /
  `e580d79023`, 2025-12-15), and the settings that configured it were dead
  controls. **If upstream keeps RediSearch, this is a real conflict**: the code
  that read those fields is gone from our `query.py` too.
- **Changed** (label / depends_on / placement only):
  `filter_categories_section`, `checkout_settings_section`,
  `payment_success_url`, `payment_gateway_account`, `shop_by_category_section`,
  `add_ons_section`, `guest_display_settings_section`.

**`webshop/webshop/doctype/item_review/item_review.json`**
- added: `verified_purchase` — a review coming from a purchase follow-up e-mail
  is flagged, so the shop can say the buyer really bought the product
  (`5d19e3fed9`, 2026-09-03). `field_order` follows.

### Payment templates — the `.json` companion of each tile

`webshop/templates/payments/{stripe,paypal,wallee,twint,payrexx,webshopsi}.json`
— all **added**. Each one declares the tile to the checkout (gateway, template
path, assets). Upstream's shop redirects to the `payments` app's own gateway
page and has no tile registry.
`stripe` / `paypal`: `3bc2d836f1` (2025-02-11) · `wallee`: `043924b1d5`
(2025-12-10) · `twint`: `7edfb905be` (2026-05-19) · `webshopsi`: `662c26b650`
(2026-05-26) · `payrexx`: `77e7ed3c19` (2026-08-11).

### Bundle entry point

`webshop/public/web.bundle.js` — **modified**, +3 lines. It is a bench bundle
manifest (a list of `import` lines), which the marker checker treats as a built
asset; a comment in it would be flagged as non-comment. We add the imports of
`auth_dialog.js`, the no-jQuery search and the cross-sell script
(`3bc2d836f1` 2025-02-11 · `48e2708353` 2025-03-13 · `8c29208cca` 2026-09-03).

### Translations

`webshop/locale/fr.po` and `webshop/locale/main.pot` — **added**. Upstream
webshop ships no catalogue at all; ours carries the French of the whole shop,
including the strings of every feature listed above (`9ec1affe61`, 2025-12-15,
then `1dda347838`, `21c5098419`, `bcf0b88d5c`, `71ce1a8666`, `7f870f6d13`,
`bbeaf84421`, `2a305d1676`, `34e556bc99`, `c622b6bec8`). PO only — never a
`translations/*.csv` (Frappe loads `locale/*.po` first, so a fix applied only to
the CSV is silently ignored).

### Test suite manifest

`tests/e2e/package.json` — **added** with the Playwright suite (`36c14da9a6` /
`1c36a8f365`, 2026-08-27; multi-site specs `d6018e6311`, 2026-08-28).

---

## Whitespace-only divergences

No marker can sit on these; they are recorded here so a merge conflict on them
is recognised for what it is.

- **`webshop/webshop/utils/portal.py`** — the file differs from upstream by
  indentation only (`git diff -w` is empty). Resolve any conflict by taking
  upstream's content.
- **Trailing newline REMOVED by us** (upstream ends the file with a newline,
  ours does not): `webshop/hooks.py`, `webshop/templates/pages/cart.js`,
  `webshop/webshop/product_data_engine/filters.py`,
  `webshop/webshop/utils/portal.py`. Accidental — an editor without
  `insert_final_newline`. Harmless, but it makes the last line of each of those
  files show as changed in every merge.
- **Trailing newline ADDED by us** (upstream file had none):
  `webshop/patches.txt`, `webshop/public/scss/webshop-web.bundle.scss`,
  `webshop/public/scss/webshop_cart.scss`,
  `webshop/webshop/shopping_cart/cart.py`,
  `webshop/webshop/doctype/website_item/website_item_list.js`,
  `webshop/www/shop-by-category/index.js`, and the three DocType JSONs above.
- **Tabs for spaces**: parts of `webshop/hooks.py` were re-indented from four
  spaces to tabs. The marker in the file says so; take OUR side on those hunks.

---

## Hunks that cannot physically carry a marker

Sixteen changed lines sit **inside a JavaScript template literal** (or, for the
last one, inside a Python docstring), more than three lines from its opening
statement. A `//// Neoffice` comment placed there would be rendered into the
page's HTML — it would be a change to the output, not a comment — so the rule
"comments only" and the rule "every hunk carries a marker" cannot both hold.
They are recorded here instead. The surrounding block always carries its own
marker; these lines belong to it.

| file:line | what it is |
|---|---|
| `webshop/public/js/product_ui/grid.js:251` | `- 20%` instead of upstream's `20% OFF` (label dropped rather than translated: this bundle has no `__()`) |
| `webshop/public/js/product_ui/grid.js:353` | "Explore" read from `window.product_translations` |
| `webshop/public/js/product_ui/grid.js:368` | "Add to Cart" / "Add to Quote" read from `window.product_translations` |
| `webshop/public/js/product_ui/grid.js:377` | "Go to Cart" / "Go to Quote", same |
| `webshop/public/js/product_ui/list.js:105` | the Cover/Contain fit style on the row image |
| `webshop/public/js/product_ui/list.js:203` | `- 20%` instead of `20% OFF` |
| `webshop/public/js/product_ui/list.js:293` | "Available on backorder", same translation channel |
| `webshop/public/js/product_ui/list.js:313` | "In stock", same |
| `webshop/public/js/product_ui/list.js:355` | "Explore", same |
| `webshop/public/js/product_ui/list.js:372` | "Add to Cart" / "Add to Quote", same |
| `webshop/public/js/product_ui/list.js:386` | "Go to Cart" / "Go to Quote", same |
| `webshop/public/js/product_ui/search.js:319` | `.product-name-result` class on the dropdown result title |
| `webshop/public/js/product_ui/search.js:321` | the price block added to a dropdown result |
| `webshop/public/js/product_ui/views.js:912` | translated placeholder of the search box |
| `webshop/public/js/product_ui/views.js:2034` | translated "No products found" empty state |
| `webshop/webshop/product_data_engine/query.py:90` | the `sort_order` line of `ProductQuery.query()`'s docstring (sorting is ours) |

The eleven `window.product_translations` lines all have one cause, stated at
length on the markers around them: `dd08553e88` (2025-12-15) replaced Frappe's
`__()` with `window.product_translations` in these bundles, because `__()` is
not loaded on the shop's public pages and every label came out in English on a
French shop.

---

## What is deliberately NOT marked

- `.github/**` — CI is ours end to end (`79e90016ab`, 2026-08-29: the workflow
  had never fired on this fork; `afd45bdf6b`, 2026-09-03: fleet CI wave 2;
  `55915ddf1e`: this very marker workflow). The two deleted files
  `.github/helper/install.sh` and `.github/helper/site_config_mariadb.json` went
  with upstream's own CI rewrite.
- `webshop/public/dist/**` — build output, git-ignored.

---

## Auto-marked (fork-markers workflow)

- `webshop/webshop/doctype/store_closure/store_closure.json` — new child table (`from_date`, `to_date`, `label`) of exceptional store closures, shown on `/store-hours` and the public opening-hours block — no upstream equivalent (afaa23b6d8 "feat(magasin): les horaires d'ouverture, saisis dans les réglages et affichés partout")
- `webshop/webshop/doctype/store_opening_hours/store_opening_hours.json` — new child table (`weekday`, `opens`, `closes`), one row per opening range (two for a day with a lunch break) — no upstream equivalent (afaa23b6d8 "feat(magasin): les horaires d'ouverture, saisis dans les réglages et affichés partout")

---

## Path index

Every path covered above, spelled in full (the marker checker matches literally).

```
tests/e2e/package.json
webshop/locale/fr.po
webshop/locale/main.pot
webshop/public/web.bundle.js
webshop/templates/payments/paypal.json
webshop/templates/payments/payrexx.json
webshop/templates/payments/stripe.json
webshop/templates/payments/twint.json
webshop/templates/payments/wallee.json
webshop/templates/payments/webshopsi.json
webshop/webshop/doctype/abandoned_cart_reminder/abandoned_cart_reminder.json
webshop/webshop/doctype/b2b_customer_group/b2b_customer_group.json
webshop/webshop/doctype/cross_sell_offer/cross_sell_offer.json
webshop/webshop/doctype/frequently_bought_together/frequently_bought_together.json
webshop/webshop/doctype/gift_card_amount/gift_card_amount.json
webshop/webshop/doctype/item_review/item_review.json
webshop/webshop/doctype/purchase_follow_up/purchase_follow_up.json
webshop/webshop/doctype/purchase_follow_up_entry/purchase_follow_up_entry.json
webshop/webshop/doctype/purchase_follow_up_log/purchase_follow_up_log.json
webshop/webshop/doctype/purchase_follow_up_step/purchase_follow_up_step.json
webshop/webshop/doctype/store_closure/store_closure.json
webshop/webshop/doctype/store_opening_hours/store_opening_hours.json
webshop/webshop/doctype/webshop_payment_method/webshop_payment_method.json
webshop/webshop/doctype/webshop_settings/webshop_settings.json
webshop/webshop/doctype/webshop_trust_item/webshop_trust_item.json
webshop/webshop/doctype/webshop_warehouse_source/webshop_warehouse_source.json
webshop/webshop/doctype/webshopsi_country/webshopsi_country.json
webshop/webshop/doctype/webshopsi_invoice_installments/webshopsi_invoice_installments.json
webshop/webshop/doctype/webshopsi_settings/webshopsi_settings.json
webshop/webshop/doctype/website_item/website_item.json
webshop/webshop/doctype/website_item_warehouse_source/website_item_warehouse_source.json
webshop/webshop/workspace/webshop/webshop.json
```
