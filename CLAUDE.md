<!-- //// Neoffice — added file (no upstream equivalent): the fork's guide, read by Claude Code. -->
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Frappe Webshop is an open-source eCommerce platform built on the Frappe framework and designed to integrate with ERPNext. It provides a comprehensive solution for small to medium-sized businesses to create customizable online stores with features like shopping cart, checkout, payment processing, gift cards, loyalty points, and product management.

## Technology Stack

- **Backend**: Python 3.10+ (Frappe framework)
- **Frontend**: JavaScript, Jinja2 templates
- **Database**: MariaDB
- **Cache/Queue**: Redis
- **Build Tools**: bench CLI, yarn
- **Testing**: Python unittest (via bench)

## Development Setup

### Installation

This app must be installed within a Frappe bench environment:

```bash
# Create a new bench (if needed)
bench init --frappe-branch develop frappe-bench
cd frappe-bench

# Get required dependencies
bench get-app erpnext --branch develop
bench get-app payments --branch develop

# Get webshop app
bench get-app webshop

# Create a new site
bench new-site sitename --db-root-password root --admin-password admin

# Install apps
bench --site sitename install-app erpnext
bench --site sitename install-app webshop

# Build assets
bench build

# Start development server
bench start
```

### Running Tests

```bash
# Run all webshop tests
bench --site sitename run-tests --app webshop

# Run specific test file
bench --site sitename run-tests --module webshop.webshop.shopping_cart.test_shopping_cart

# Run specific test case
bench --site sitename run-tests --test webshop.webshop.shopping_cart.test_shopping_cart.TestShoppingCart.test_add_to_cart
```

### Building Assets

```bash
# Build all assets
bench build

# Build only webshop assets
bench build --app webshop

# Watch for changes during development
bench watch
```

### Code Quality

```bash
# Format Python code (configured in pyproject.toml)
black --line-length 99 webshop/

# Sort imports
isort --line-length 99 --multi-line 3 --trailing-comma webshop/
```

## Architecture

### Directory Structure

- **`webshop/hooks.py`**: Core Frappe app configuration, defines event hooks, scheduled tasks, DocType overrides, and document event handlers
- **`webshop/webshop/`**: Main application module
  - **`api.py`**: Whitelisted API endpoints for frontend (product filtering, search, etc.)
  - **`shopping_cart/`**: Shopping cart and checkout functionality including guest cart, product info, and cart utilities
  - **`doctype/`**: Custom DocTypes (Website Item, Webshop Settings, Item Review, Wishlist, etc.)
  - **`product_data_engine/`**: Product query and filtering engine with support for RediSearch
  - **`variant_selector/`**: Product variant selection logic and caching
  - **`utils/`**: Helper utilities (cart helpers, product carousel, frequently bought together, discount queries)
  - **`crud_events/`**: Document lifecycle event handlers organized by DocType (item, quotation, sales_invoice, etc.)
  - **`auth/`**: Authentication API endpoints
- **`webshop/templates/`**: Jinja2 templates
  - **`pages/`**: Python controllers and templates for main pages (cart, checkout, order, product_search, etc.)
  - **`includes/`**: Reusable template components (cart_component, product_page, mobile_menu, etc.)
  - **`generators/`**: Dynamic page generators (item pages)
  - **`web.html`**: Base template for webshop pages
- **`webshop/www/`**: Web routes and utilities (sitemap generation, maintenance page)
- **`webshop/public/`**: Static assets
  - **`js/`**: JavaScript modules (shopping_cart.js, wishlist.js, auth_dialog.js, etc.)
  - **`scss/`**: Stylesheets
  - **`dist/`**: Built/bundled assets
- **`webshop/controllers/`**: Request handlers (payment_handler.py for payment callbacks)
- **`webshop/patches/`**: Database migration patches
- **`webshop/config/`**: Workspace and navigation configuration

### Key Architectural Patterns

#### Frappe Framework Integration

This app extends Frappe's DocType system and hooks into ERPNext's domain logic:

- **DocType Overrides**: Key ERPNext DocTypes are extended (see `hooks.py` `override_doctype_class`)
  - `Payment Request`, `Item Group`, `Item`, `Sales Invoice` have custom WebshopItem implementations
- **Document Events**: Hooks trigger on document lifecycle (see `hooks.py` `doc_events`)
  - Item updates trigger website item synchronization and cache invalidation
  - Quotation validation ensures shopping cart integrity
  - Sales Invoice creation generates gift cards
- **Website Context**: Global website context updated via `update_website_context` hooks for cart count and maintenance mode

#### Shopping Cart Architecture

The shopping cart is backed by ERPNext's `Quotation` DocType:

- **Guest Cart**: Guest users get a session-based cart stored with a guest session identifier
- **User Cart**: Logged-in users have carts linked to their Customer record
- **Cart State**: Cart count stored in cookies, cart data in Quotation documents
- **Checkout Flow**: Cart → Checkout page → Payment Request → Sales Order → Sales Invoice
- **Payment Handler**: Idempotency tokens prevent duplicate payment requests

#### Product Data Engine

The product listing system uses a query builder pattern:

- **ProductQuery**: Main query class for fetching website items with filtering, sorting, pagination
- **ProductFiltersBuilder**: Dynamically builds available filters based on current query context
- **RediSearch Integration**: Optional search acceleration (check `is_search_module_loaded()`)
- **Caching**: Product carousels and frequently bought together use Redis caching

#### Template System

Templates follow Frappe's conventions:

- **Page Templates**: Located in `templates/pages/`, each page has `.py` (controller), `.html` (template), `.js` (client script)
- **Includes**: Reusable components in `templates/includes/` with standardized context variables (see `webshop_core_templates_guide.md`)
- **Jinja Methods**: Helper functions registered in `hooks.py` under `jinja.methods`
- **Web Generators**: Dynamic routes for items and item groups defined in `website_generators`

## Common Development Tasks

### Adding a New API Endpoint

1. Add whitelisted function to `webshop/webshop/api.py`:
   ```python
   @frappe.whitelist(allow_guest=True)
   def my_endpoint(param):
       # Implementation
       return {"result": "data"}
   ```

2. Call from JavaScript:
   ```javascript
   frappe.call({
       method: "webshop.webshop.api.my_endpoint",
       args: {param: "value"},
       callback: (r) => console.log(r.message)
   });
   ```

### Adding a New Template Include

1. Create template file in `webshop/templates/includes/my_component.html`
2. Document context variables and usage in `webshop_core_templates_guide.md`
3. Include in parent template: `{% include "templates/includes/my_component.html" %}`
4. Pass context from Python controller or register Jinja method in `hooks.py`

### Working with DocType Events

1. Create event handler in `webshop/webshop/crud_events/[doctype]/my_event.py`:
   ```python
   def execute(doc, method=None):
       # Event logic
       pass
   ```

2. Register in `hooks.py` under `doc_events`:
   ```python
   doc_events = {
       "Item": {
           "on_update": ["webshop.webshop.crud_events.item.my_event.execute"]
       }
   }
   ```

### Creating Database Patches

1. Create patch file in `webshop/patches/descriptive_name.py`:
   ```python
   import frappe

   def execute():
       # Patch logic
       pass
   ```

2. Add to `webshop/patches.txt`:
   ```
   webshop.patches.descriptive_name
   ```

### Working with Translations

All user-facing strings must be wrapped with translation functions:

**Python**:
```python
from frappe import _

message = _("Product added to cart")
frappe.msgprint(_("Order placed successfully"))
```

**JavaScript (Website Pages)**:

For website pages (like all-products), use `window.product_translations` which is populated server-side via Jinja:
```javascript
// In the HTML template (index.html), translations are loaded like this:
window.product_translations = {
    "Search": {{ _("Search")|json }},
    "Add to Cart": {{ _("Add to Cart")|json }}
};

// In JavaScript, use:
const translations = window.product_translations || {};
const searchText = translations["Search"] || "Search";
```

**Note**: The `__()` function only works on Frappe Desk pages, NOT on website pages. Website pages must use `window.product_translations`.

**Jinja Templates**:
```html
<h1>{{ _("Welcome to our store") }}</h1>
<button>{{ _("Add to Cart") }}</button>
```

### Translation Files Workflow (PO/POT)

Translation files are stored in `webshop/locale/` and **MUST be committed to git**:
- `main.pot` - Template file with all translatable strings
- `fr.po` - French translations (and other language files)

**Commands**:
```bash
# Generate/update POT template (extracts all translatable strings)
bench generate-pot-file --app webshop

# Update PO files from POT template
bench --site sitename update-po-files --app webshop

# Compile PO to MO (binary format used at runtime)
bench --site sitename compile-po-to-mo --app webshop
```

**Adding new translatable strings**:
1. Add the string with `_()` in Python/Jinja or add to `window.product_translations` in HTML templates
2. Run `bench generate-pot-file --app webshop` to update `main.pot`
3. Run `bench --site sitename update-po-files --app webshop` to update language PO files
4. Translate new strings in the PO file (e.g., `webshop/locale/fr.po`)
5. **Commit and push** the updated PO/POT files to git
6. On server: `bench --site sitename compile-po-to-mo --app webshop && bench --site sitename clear-cache`

**IMPORTANT**: Always commit translation files (`*.po`, `*.pot`) to git after making changes!

## Important Conventions

### Webshop Settings

The `Webshop Settings` DocType controls all webshop features:
- Enable/disable checkout, guest cart, field filters
- Configure price lists, quotation series, products per page
- Set up RediSearch indexing
- Access via `frappe.get_doc("Webshop Settings")`

### Website Items vs Items

- **Item**: ERPNext's core inventory item DocType
- **Website Item**: Webshop-specific item representation with web fields (route, web_item_name, website_image, etc.)
- Items automatically sync to Website Items via `crud_events.item.update_website_item`

### Guest Session Handling

Guest users are identified by a guest session ID stored in cookies:
- Guest cart linked to quotation with `guest_session` field
- On login, guest cart can be merged with user cart
- Session management in `webshop.webshop.shopping_cart.guest_cart`

### Payment Processing

Payment flow uses ERPNext's Payment Request system:
- Idempotency tokens prevent duplicate requests (see `payment_handler.py`)
- Payment gateway callbacks handled by `controllers/payment_handler.payment_callback`
- Multiple payment methods configured in Webshop Settings

### Second-hand units (occasion)

A used or refurbished unit is **its own Item**, linked to the new item through
`condition_of_item` — never a variant (a systematic attribute combination),
never a serial number (the cart adds items, and there is no price per serial).
The Item carries the condition (custom fields from
`patches/add_item_condition_fields.py`: `item_condition` New / Refurbished /
Second-hand, `condition_grade`, `condition_details`, `condition_of_item`;
the native `warranty_period` in days is what the page shows in months).
Website Item mirrors them (`fetch_from` + `crud_events/item/update_website_item.py`).

- Vocabulary lives in `webshop/utils/used_items.py`: what counts as second-hand,
  the schema.org / Google Merchant condition URL (the product page's JSON-LD
  used to write `NewCondition` for everything), warranty in months.
- `create_used_unit()` is the one-click action on the new item's form: copy,
  Item Price on the shop's list, Material Receipt, Website Item seeded from the
  new item's page.
- The value is `Second-hand`, not `Used`: `Used` is already translated
  "Utilisé" (coupons) in `fr.po`.
- **Two ways in, both verified on screen.** Either set the Item's `Condition`
  to Second-hand / Refurbished (the grade, story and "used unit of" fields
  appear, the Website Item mirrors on save, `/occasions` lists it at once), or
  press "Create Used Unit" on the new item, which does all of that plus the
  price, the stock receipt and the publication in one dialog.
- **The Condition section closes the Item's Details tab (`insert_after: uoms`),
  not `brand`.** A custom field lands right after its anchor, ahead of the
  older ones sharing it; a section break after `brand` therefore swallowed
  every other app's fields there (attachments, collection, alcohol flag).
  `move_item_condition_section` relocates it on existing sites.
- `/occasions` is `/all-products` with the Condition facet locked
  (`www/occasions`, `product_data_engine/listing_context.py`,
  `window.locked_field_filters`). In the sidebar the used units are a **toggle next to
  the discount one** (`views.js` `get_second_hand_filter_html`, 2026-09-13): the same
  life as "discounted only" — a checkbox, a per-visitor preference in `localStorage`,
  a chip — and one query key, `second_hand`, that the engine resolves to
  `SECOND_HAND_CONDITIONS` in `build_fields_filters`, so both query paths agree. The
  link to `/occasions` that stood at the top of the sidebar is gone. Webshop Settings accepts a **Select** as a
  filter field for this; the facet only renders once a published item is not
  New. Badges: `grid.js`, `list.js`, `product_carousel.html` — three copies,
  plus `bench build`.
- **The catalogue's toggles last for the visit** (2026-09-14). Discount, second-hand and stock
  live in `sessionStorage` through `webshop.filter_store` (top of `views.js`): in localStorage a
  toggle ticked once greeted every later visit with a filtered catalogue — on a shop with no
  discounted product, an empty grid. A toggle the page does not offer is never on
  (`window.discount_count` / `window.second_hand_count` at 0), and the discount toggle is not
  drawn when no product is discounted. "Clear all" shows only under a filter and clears the
  toggles too; the sidebar's "· N produits" is the listing's own figure (event
  `webshop:listing-count` from `update_active_filters_display`), only under a filter — it ran a
  query of its own that ignored the toggles and printed the whole catalogue's size at every load.
  An empty result clears the previous tiles.

- **Sold means gone** (2026-09-14). A used unit is one of a kind, so `Website Item.sold`
  (read-only, set on save and kept by the stock ledger: the `Stock Ledger Entry` `on_submit`
  hook in `utils/used_items.py` remembers the used units a voucher moves, and a `"*"`
  `on_submit`/`on_cancel` hook recomputes them once the voucher is done — ERPNext updates the
  warehouse's Bin only AFTER the ledger entry's submit, so a flag computed in that hook read the
  stock before the sale and the unit stayed listed; the CI caught it) takes it out of
  every listing path (`ProductQuery.filters` carries `["sold", "=", 0]` next to `published`,
  and the hand-written SQL paths say `wi.sold = 0`), out of the sidebar's second-hand count and
  out of the sitemap, and out of every other surface that offers products: the search (grid and
  legacy index), the quick order, the carousels, the product page's recommendations, "bought
  together", the discount queries, the facets' counts, the category cards and the brand counts.
  They had kept offering sold units, and their counts drifted by every unit the shop ever sold.
  `TestEveryOfferReadsSold` reads those modules for a query on `published` that forgets `sold`.
  A used unit shown without stock is one the shop cannot source, so the tile and the page print
  "Sold" only when `sold` says so, "Out of stock" otherwise. Its page answers a **302** to the new model (a bookmark, a search result:
  the unit is gone, the product is not), temporary because a return puts the unit back on sale
  at the same address. `patches/mark_sold_used_units` gave the units published before the field
  their value once. **What "sold" reads is the unit's own stock**: nothing available in any
  warehouse, orders' reservations deducted (`used_unit_in_stock`). The first version asked the
  shop's exposure rule (the multi-warehouse sources, or the website warehouse), and a unit on
  hand where the shop does not look (45 pieces and no website warehouse, on osiris) read as
  sold, left the catalogue and redirected its page; such a unit is out of stock on its page,
  which the merchant sees. A `Sales Order` `on_submit`/`on_cancel` hook recomputes the units an
  order holds, so a unit leaves the catalogue when it is ordered, not when it ships.
  `patches/recompute_sold_used_units` applies the rule once to existing sites. Never unpublish for this: frappe's renderer 404s an unpublished page
  before `get_context` can redirect, and the merchant would read "unpublished" as a mistake.
- **The new model and its used copies see each other.** The new item's page lists its
  in-stock used units right under the buy button (`get_used_units`; they sat after the offers,
  where nobody saw them); a used unit's page shows the new model as a card — picture, price on
  this site's list, stock, "See the new model" (`get_new_model`, on
  `condition_info.reference`) — and the other used copies of the same model
  (`get_sibling_units`). One Jinja macro, `used_unit_row`, draws every row; a price shows only
  where the page shows its own (`price_info`, empty for a visitor on a shop that hides prices).
- **A template's tile says "Discover"** (`Découvrir`), the merchant's word; "Explore" read
  badly in French.
- **The discount toggle counts too.** `listing_context.count_discounted()` keeps, five minutes
  per site and price list, the result of `query.count_discounted_items()` — one COUNT with the
  listing's own joins (the site's price list, a dearer list, the pricing rules) over the
  standing conditions, the SQL the toggle already ran when ticked, now in
  `ProductQuery._discounted_count_sql()` — and the Pricing Rule and Item Price hooks drop the
  cache. A catalogue view never pays the join; the figure lags a price change by at most the
  cache, and by nothing after a desk save.

### Cross-sell offers and the order bump

`Cross Sell Offer`: "when the cart holds A (item, group or brand), propose B
with an advantage". **The advantage is a Pricing Rule generated from the
offer** (`apply_rule_on_other`, or a free item): ERPNext prices B in the cart,
the order and the invoice, and drops the discount when A leaves. No second
pricing engine. `webshop/utils/cross_sell.py` answers `get_offers(placement)`
and `accept_offer()`; `public/js/cross_sell.js` draws the four placements
(product page, cart page, drawer, checkout bump) with labels sent by the server
(website pages have no `__()` catalogue). The drawer of a Builder shop is not
webshop's: `builder/templates/includes/header_footer/components/cart_drawer.html`
(the `builder` fork) calls `webshop.cross_sell.load` itself — after the window's
`load` event, because that script runs in the header before this bundle.

> Three things the ERPNext fork had to learn (all marked `#//// Neoffice`,
> `accounts_controller.py` and `pricing_rule/utils.py`): a discount-on-other-item
> rule discounted the **trigger** row too on a server-created document; it
> applied **without a document** (the catalogue price of both A and B showed
> the discount); and two rules that tie made the cart **refuse to save**.
> Generated rules carry `apply_multiple_pricing_rules` so two offers on one
> trigger coexist; `discount_query.py` ignores them.

> A Link field named `customer_group` receives the session default at insert
> time (Selling Settings) — the offer's field is `only_customer_group`.

### Purchase follow-ups and abandoned carts

`Purchase Follow-up` (the flow: after a purchase of X, these Email Templates,
N days later) enrols one `Purchase Follow-up Entry` per order and item on
submit (`webshop/utils/follow_ups.py`, hooks on Sales Order and Sales Invoice).
The cron job at 08:15 sends what is due, logs each mail on the entry and as a
**Communication on the Customer** (the customer's timeline is the audit), then
schedules the next step. Stop rules: cancel, return, unsubscribe (Frappe's own
Email Unsubscribe scoped to the Customer, linked from every mail), "ordered
again", and a step missed by more than two weeks is skipped rather than sent
late. A step can follow the item's `replenishment_days` (80% of the cycle).

Webshop Settings (Emails tab) holds the master switch `enable_purchase_follow_ups`
(off by default: nothing is enrolled, nothing goes out) and `follow_up_audience`
(shop customers only, or every customer — each flow then keeps its own
`only_website_orders`). The tab shows the figures (`get_email_stats`).

`webshop/utils/abandoned_carts.py` runs hourly on the open shopping-cart
Quotations of signed-in customers (Webshop Settings, Emails tab: delays,
template, from which email a single-use coupon is generated). The email links
land on `/cart?add=ITEM&qty=1` and `/cart?coupon=CODE`
(`templates/pages/cart.py`), and the review email on `/route#write-review`.

> `seed_follow_up_email_templates` ships the templates and two flows switched
> **off**: a client instance must never start mailing because it migrated.

<!-- //// Neoffice — documents 077ee1cc03 "fix(cart): un panier rappelé par email pouvait ne plus jamais se vider": an abandoned-cart reminder links the quotation, so update_cart's delete of the last-line cart raised LinkExistsError; _release_abandoned_cart_reminders now frees the reminders before the delete. -->
> **A reminder links the cart, and Frappe refuses to delete a linked document.**
> `update_cart` deletes the quotation when its last line goes; a customer who
> had received a reminder therefore got a 417 on the cross of their last line
> and could never empty the cart (osiris, 2026-09-07). The `LinkExistsError`
> branch now releases the reminders too (`_release_abandoned_cart_reminders`),
> next to the unsuccessful payment requests it already released.

> `frappe.db.has_column("Webshop Settings", ...)` raises TableMissingError: a
> Single has no table — ask `frappe.get_meta(...).has_field()`.

> A GET is never committed by Frappe, and `frappe.Redirect` ends the request:
> `/cart?add=` commits explicitly before redirecting. `frappe.sendmail` commits
> on its own, which discards any savepoint around it.

> **A coupon on the grand total is shown as pre-discount figures plus its own
> line.** ERPNext folds a document-level discount into `net_total`, so a summary
> that prints `net_total` next to the pre-discount tax and the full coupon line
> shows three numbers that do not add up (29.61 + 2.66 − 3.56 displayed as
> 32.00). Every summary — cart page, checkout (server render and
> `checkout.js`), thank-you page, and the Builder cart drawer in the `builder`
> fork — prints `total` minus the taxes included in the price, the tax rows'
> `tax_amount`, then `-discount_amount`. Change one, change them all.

> **The checkout removes the coupon before a shipping rule or a quantity
> change, then puts it back.** The removal predates this work; what changed is
> `restoreCoupon()`, which re-applies through `apply_coupon_code` so validity
> and usage limits are checked again. That endpoint accepts the Coupon Code
> document *name* as well as the code the customer types, because the
> quotation only stores the name. Without this, the coupon from an
> abandoned-cart email vanished at the shipping step.

<!-- //// Neoffice — new section: documents the /shop-by-category page and its fixes
(the 403 on a Select filter, gift-card/group cards leading nowhere, the useless
Condition tab, missing translations, the repeated title and lost 130px, per-card
counts, and the "Default" sort not restoring the initial order) added across
5d967ca17a, bd4341c282, bbbb6a25e4, ccce63886e, 2bafdf34c2, 4d0659d41a and
56c6de8861. -->
### The category page

`/shop-by-category` (`www/shop-by-category/`) draws one tab per filter field of
Webshop Settings, and a card per value. **It has to build what the sidebar facets
build** (`product_data_engine/filters.py`) — they had drifted, and the page had no
test at all until 2026-09-10.

> **A website page that raises answers 403.** The controller read a **Select**
> field's `.options` as a doctype name, so `frappe.get_meta("New\nRefurbished\n
> Second-hand")` raised outside the function's only try — and the whole page read
> "Non autorisé" to every visitor of every shop whose filters include the Condition
> field. One misconfigured filter now costs its own tab: an absent field, a deleted
> link doctype, a Table MultiSelect with no mandatory Link (which left `doctype`
> unbound, or carrying the PREVIOUS tab's).

> **A card is a promise that something is behind it.** `show_in_website` says a
> record MAY appear, never that the shop has anything to put in it.
> `_carried_values()` is the catalogue's own scope — published, visible on this
> site, gift cards out when they are off, variants out when hidden — and groups,
> brands and collections all go through it. A parent group whose child carries
> items stays, as in the facet. On a B2B shop with gift cards switched off, the
> first card used to read "Carte cadeau" and led nowhere: **an item group is not an
> item**, so the gift-card switch had never reached it.

> **`select_facet_is_useful()`** (in `filters.py`) is the one rule deciding whether
> a Select facet offers a choice. It used to live unnamed inside
> `get_field_filters`, so this page offered a "Condition" tab holding the single
> card "New" while the sidebar showed no Condition facet at all.

> **`frappe._()` resolves nothing on a website page** — no `__()` catalogue there.
> The page carries its own `window.product_translations`, filled server-side, like
> every other webshop page. And `context.title` is what the theme prints as the
> heading AND the last breadcrumb; leave it unset and Frappe writes the route name.

> **`frappe.get_app_path("webshop", "www", "shop-by-category", …)` scrubs the
> segments it is handed** and looks for `shop_by_category`. The module cannot be
> imported either — a hyphen is not an identifier — so its test loads it with
> `importlib.util.spec_from_file_location`.

> **The block carries no title, and `index.js` no longer anchors on one.** It used
> to print an `<h2 class="section-title">` repeating the page's own H1 and its last
> breadcrumb — the same three words three times — which `index.js` then used as the
> insertion point for its toolbar. `title` is optional in Frappe's "Section with
> Tabs" template; the toolbar is prepended to `.category-tabs` instead. Roughly
> 130 px of empty page came back: that heading (53), the tab block's `mt-12` (48,
> nested as `.category-tabs > section.section > .mt-12`, so a child selector misses
> it) and the slideshow wrapper, which kept its 2rem bottom margin on every shop
> that has no slideshow.

> **Each card prints how many products it holds** (`_carried_counts`, one grouped
> query, the same scope as the facets, so the same figure). A group answers for its
> whole subtree, since the facet keeps a group carrying items AND its ancestors.
> The search and the sort therefore read `data-name`, not the card's text — looking
> for "7" used to match every category holding seven things. And "Default" now
> restores the server's order (each card remembers its index): it used to re-insert
> the cards in their CURRENT order, so A-Z was a one-way door.

### Paying without a gateway, and who is offered what

A payment method row (`Webshop Payment Method`, the `payment_methods` table of
Webshop Settings) is **one method offered to one audience, on its own terms**.
`only_customer_group` empty means everyone; filled, it covers that group **and its
sub-groups** — customer groups are a tree. Repeat the same gateway on several rows,
one per group, when each needs its own `payment_terms_template`; when two rows of a
gateway match, the closest group wins (`utils/payment_methods.py`).

`settlement` says how the tile settles:

| value | what happens |
|---|---|
| `Online` | unchanged: the shopper is handed to the gateway, the order follows the payment |
| `Transfer before shipping` | the order is placed and **held**, a Payment Request is raised on it, and **no invoice** is issued until the money arrives |
| `On account` | the order is placed and ships, invoiced on the group's terms |

Both offline paths go through `shopping_cart/offline_payment.py`, never through
`create_payment_request`: there is no PSP to call. The endpoint refuses a method the
customer is not offered — hiding a tile is not a permission — and an idempotency
token stops a double click becoming two orders.

> **A held order cannot be invoiced, so `set_as_paid()` fails on exactly these
> requests.** ERPNext refuses to invoice a Sales Order that is On Hold, and
> `set_as_paid()` raises the invoice — so the framework's own "Set as Paid" answers
> "Sales Order … is On Hold" and books nothing. `offline_payment.settle()` lifts the
> hold first (`update_status("Draft")`, which restores the *computed* status, it does
> not draft the order), then hands over to ERPNext. The desk button lives in
> `public/js/override/payment_request.js`. Measured end to end: payment entry,
> request Paid, order To Deliver, invoice Paid on the row's terms.

> **Never name a Link field `customer_group`.** Frappe fills a Link of that name with
> the session default at insert time (Selling Settings), so "empty means everyone"
> can never happen — the rows come back naming whatever the session defaulted to, and
> on a shop whose default is a real group every method would silently be restricted to
> it. Hence `only_customer_group`, the same name and the same reason as
> `Cross Sell Offer.only_customer_group`.

> **`enable_checkout` used to drop back to 0 in silence.** Upstream's
> `validate_checkout` only looked at the single `payment_gateway_account` field, which
> the modern checkout does not read — it reads the `payment_methods` table. A shop that
> had filled the table saw the tick undo itself on save, with no message anywhere. The
> table counts now, and a refusal says so.

> **`__()` resolves nothing on the checkout either.** The sentences around the terms
> checkbox printed in English next to a link that *was* translated — the translations
> existed in `fr.po` all along, nothing could read them. `checkout.html` seeds
> `window.webshop_checkout_labels`, and `checkout.js` reads them through `say()`.

> **A custom button added from a server callback does not survive.** `refresh`
> runs several times while a form settles and each run rebuilds the action bar, so
> a button added when a late callback returns is wiped by the next redraw — it
> shows as a group that appears, then vanishes (a dashboard indicator dies the same
> way). Fetch once, keep the answer on the form, and draw **synchronously** on every
> refresh after that; forget it before `reload_doc()`. See
> `public/js/override/sales_order.js`.

> **The QR bill was already there.** `Oslo Payment Request` (neoffice_theme) has
> carried the Swiss QR from the start — company header, recipient, order reference,
> amount due, and the order number in the bill's "additional information". What was
> added is the retention sentence (read off the order's state, so it never claims a
> hold that is not happening) and the same bill **on the order itself**, built by the
> payment request's own builder so both documents print an identical bill.

### Where the features live on the desk

The workspace `Webshop` (`webshop/webshop/workspace/webshop/`) sits next to
`Website` in the same module, with counted shortcuts and four cards; forms get their buttons from
`doctype_js` (Item, Item Group, Brand) and their connections from
`override_doctype_dashboards` (Customer, Sales Order, Sales Invoice,
Quotation) plus `purchase_follow_up_dashboard.py`. `webshop.webshop.tests.test_desk`
checks all of it on a fresh install.

> **The Neoffice theme deletes, after every migrate, every workspace that no
> App Customization lists** (`neoffice_theme/migrations/cleanup_workspaces.py`
> builds the sidebar from those), and Frappe's sync imports a workspace file
> only once — a deleted record never comes back. `webshop/setup/desk.py`
> (`after_install` and `after_migrate`) re-imports the file when the record is
> missing and lists the workspace under the customization that carries
> `Website`. A workspace shipped without that registration lives exactly one
> migrate.

> **Deleting a standard Workspace in `developer_mode` deletes its source
> folder** from the app (`Workspace.on_trash`). `git checkout` brings it back.

<!-- //// Neoffice — added: documents the store-hours feature as one source of truth across settings, endpoint, page, include and Builder block (a3aa43ce16 "docs: les horaires du magasin, une seule source de vérité") -->
### Store hours

`webshop/webshop/utils/store_hours.py` is the one source of truth: rows on
Webshop Settings (`store_hours`, several per weekday; `store_closures` for
holidays), a public endpoint (`get_opening_hours`), the `/store-hours` page,
the include `templates/includes/opening_hours.html`, and the block any Builder
page can carry as one element (`<div class="webshop-opening-hours"
data-autoload>`), drawn and refreshed every minute by `public/js/opening_hours.js`.
Every computation takes the clock as an argument, so `test_store_hours.py`
fixes it.

> **The next opening is looked for on the current day first.** The footer
> <!-- //// Neoffice — client name redacted for the public repo; the WordPress shop's identity is not the point, only that it started from tomorrow (35770b0c93 "chore: describe the case, never the client") -->
> widget this replaces (the WordPress shop we migrated from) started from
> tomorrow, so between
> 12:00 and 13:30 it announced "tomorrow at 10:00". Closed for lunch means
> "today at 13:30"; a closure hides the whole day and names itself.

<!-- //// Neoffice ▼▼▼ — added: documents the public-holidays provider, the Holiday List integration, the footer/Builder block placement, and two rendering pitfalls, emoji-as-icon and transform:scale (b196bb69fb "docs(store-hours): les jours fériés, le pied de page, et deux pièges de rendu") -->
**Public holidays come from a provider, not from typing.**
`webshop/webshop/utils/holidays.py` reads **openholidaysapi.org** — free, no key,
and the only source checked that gives Swiss holidays **per canton and in
French**, which is what this needs: Valais closes on Saint Joseph's day and the
Immaculate Conception, Geneva does not, and Easter Monday, Ascension, Whit Monday
and Corpus Christi move every year. A day is kept when it is nationwide, or when
its subdivisions name the configured canton (or a district inside it, the API
going one level below). Measured: 14 days for Valais in 2026, 9 for Geneva, 4
nationwide-only.

They land in a **Holiday List** — Frappe's own doctype, so it shows on the desk,
can be edited by hand, and is reusable by the delivery delays that already read
one. `schedule()` merges its dates into the closures, *after* the hand-typed
rows, so a closure the shop wrote keeps its own wording. Settings live on the
Store tab (`store_holiday_country`, `store_holiday_region`, `store_holiday_list`)
with a "Fetch public holidays" button; a monthly job keeps next year stocked.

> **Nothing calls the provider while a visitor loads a page**, and an outage must
> never look like "no holidays this year": `fetch_holidays()` returns **None**, not
> an empty list, so `sync_holiday_list()` leaves the list exactly as it was. A
> wipe would open the shop on Christmas Day. A date typed by hand inside the
> covered years survives the next fetch too.

**Where the block can go.** The page `/store-hours`, the include
`templates/includes/opening_hours.html`, any Builder page as one element, and the
site footer through builder's `show_opening_hours` / `opening_hours_display`
(Website Header Footer Config **and** Variant — the per-profile chrome does not
inherit from the Single). Builder only drops the marker; the block, its styles and
its data are webshop's. `data-display="compact"` is the footer form: the state,
today's hours and a link to the full week. Nora knows the include exists
(`builder/ai/generators/page_generator.py` VALID_INCLUDES and the contact/about
prompts), so a generated contact page states the real hours instead of inventing
them.

> **An emoji is not an icon.** The first version carried 🕒 and 🔒 as meaning; they
> render differently on every platform and read as clip-art next to a typeset
> page. Inline SVG and a dot, both in `currentColor`. And **never `transform:
> scale()` on a full-width row**: it made today's line wider than the card that
> contained it, which is exactly what it looked like.

<!-- //// Neoffice ▲▲▲ -->

### The shop assistant

`webshop/webshop/assistant/` is the chat bubble's whole brain: `api.py` (three
public endpoints, identity from the session only), `engine.py` (the agent
loop: system prompt, memory, last turns, at most four rounds of tools),
`tools.py` (the toolbox — and the whole of it), `prompt.py` (French, the model
reads it), `llm.py` (any OpenAI-compatible endpoint; Nora's by default),
`escalation.py` (Raven, email, Helpdesk ticket, each with a fallback). Settings
live on the Assistant tab of Webshop Settings; conversations are
`Shop Assistant Conversation` with their `Shop Assistant Message` rows and the
tokens each turn cost.

> **A tool never takes an identity as an argument.** `get_my_orders` reads
> `frappe.session.user`, resolves the customer through `get_party` (the cart's
> own path) and returns "sign in" to a guest. `get_order(number)` filters on
> that customer too: somebody else's order is "not found". Results are explicit
> dicts — what a tool does not name, the model never sees; there is no path to
> a purchase price or a valuation.

> **The model is scripted in tests, never called.** `test_assistant.py`
> replaces `llm.complete` with a fake and `api.settings()` with an in-memory
> copy of Webshop Settings: no `tabSingles` write, which on a shared site
> waited on another suite's lock until it timed out. A real answer from Nora
> was checked by hand on osiris (hours, products with prices and links, the
> customer's order).

> **Descriptions and returned texts of tools are French, the code is
> English.** The model reads the former; nobody else reads the latter in
> French (RULE #00 and the `nora-engine` rule, same split).

<!-- //// Neoffice — added: documents the usage report, nightly purge and customer-form conversations shipped with the assistant billing/retention work (84412d0bec "feat(assistant): rapport d'usage, purge de nuit, conversations sur la fiche client") -->
The Assistant tab shows the month (`usage_stats`); the report
`Shop Assistant Usage` (by day or by customer, with the estimated cost from
`assistant_token_price`) is what the service is billed from. A nightly job
(`purge_old_conversations`) forgets conversations older than
`assistant_retention_days`, except the escalated ones. A conversation shows
under its Customer's connections. `tests/e2e/specs/08-assistant.spec.js`
exercises the bubble against the real model, and skips when the switch is off.

<!-- //// Neoffice — added: documents the fallback to the shop's selling-list Item Price when get_price's warehouse kwarg (fork-only) fails on stock ERPNext (87fd31ff01 "docs: le repli du prix de liste sur un ERPNext standard") -->
> **`get_product_info_for_website` raises on stock ERPNext** (it passes
> `warehouse=` to `get_price`, a keyword only our fork knows). The product
> tools fall back to the Item Price of the shop's selling list — a price the
> shop published, never a buying list — so the CI's fresh site and a shop on a
> plain ERPNext still get a price.

> **`HD Ticket.customer` links to Helpdesk's own `HD Customer`, not to
> ERPNext's Customer.** Setting the ERPNext name made the insert fail on
> `LinkValidationError`; the ticket now only carries it when an HD Customer of
> that name exists, and falls back to a message to the team when the ticket
> cannot be created at all.

<!-- //// Neoffice — added: the answering machine section, documenting the scripted notice and the "leave a message" escalation path used when the model is unreachable or a limit is hit (814347b504 "feat(assistant): un répondeur quand le modèle tombe ou la limite est atteinte") -->
**The answering machine.** When the model fails (timeout, 503, nothing
configured), or the visitor's daily limit or the shop's monthly cap is reached,
`send` does not apologise and stop: it answers with a scripted notice (the
merchant's `assistant_offline_message`, the store's opening status from
`store_hours`, an invitation) and the widget shows a form whose text reaches
the team through `leave_message` → `escalation.contact_team`, with no model
involved: Raven, support email, confirmation to the visitor, conversation
Escalated. A failure arms a 120 s outage flag in Redis (`OUTAGE_KEY`) so the
next visitors get the notice at once instead of a 25 s wait, and `get_config`
carries the notice from the first screen. The "Talk to the team" link opens
that form directly. A signed-in visitor is written to at the session's address
whatever the form says; a guest must give a valid one.

<!-- //// Neoffice — added: documents the reseller quick-order page, the server-side is_reseller() gate, and the shared add-to-cart validation path it reuses (939e007ad8 "feat(quick-order): la commande rapide des revendeurs — lot 1") -->
### The quick order

`/quick-order` (`www/quick-order/`, `webshop/webshop/quick_order/api.py`) is
<!-- //// Neoffice — reworded: open to any signed-in customer and an anonymous visitor where the shop allows a guest cart, not resellers only, and each grid now has its own "add to cart" button (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille") -->
the page a customer restocks from: type a reference, a name or a barcode, the
model's colour × size grid opens, quantities go in at the keyboard, each grid
has its own "add to cart" and one "send everything" writes the whole draft.
It is open to whoever may fill a cart on this site — `require_shopper()`: any
signed-in customer, and an anonymous visitor where the shop allows a guest
cart and the site is not reserved for business accounts — because nothing in
it is professional but the pace. Everything in the module is scoped the same
way as the catalogue: a published Website Item, visible on this site
(`excluded_item_names()`), priced at the site's tariff
(`effective_price_list()`), stocked by the shop's own rule. The draft lives in
the browser (`localStorage`, per user and site, seven days) until it is sent;
the cart is the state afterwards. A guest's batch goes through
`create_guest_quotation`, the cart's own rebuild-from-list path.

> **`get_variant_matrix` of `neoffice_theme` answers 403 to a Website User** —
> it needs the desk's read permission on Item, correctly. `get_matrix()` is its
> portal counterpart: same shape, built from the Website Item and the variants
> cache, sizes sorted by the theme's `_smart_sort_values` when the app is
> installed and by the attribute master otherwise. Every dict names its fields;
> no buying price, no valuation, no supplier field can leave.

> **The batch goes through the rule of "add to cart", not a copy of it.**
> `validate_cart_line()` and `available_cart_qty()` were split out of
> `update_cart` for this — `update_cart` calls them and behaves as before
> (same messages). `add_lines()` validates every line, loads the customer's
> quotation once, merges, saves once. What the shop cannot serve is capped and
> named (`capped`), what it cannot sell here is refused and named (`refused`);
> a valid line is never held back by a refused one.

<!-- //// Neoffice — documents the second upstream check found by CI (c12b9a4d5e "fix(quick-order): tarifer et sauvegarder le panier au nom du client sur ERPNext standard"): get_party_account, alongside get_item_details, blocks a portal customer's own quotation save -->
> **Upstream ERPNext version-15 checks Item and Account permissions inside the
> quotation's validate** (`get_item_details`, `get_party_account`) — a portal
> customer holds neither, so their own cart cannot be priced or saved on a stock
> site (the CI). The fleet's fork has neither check yet. `add_lines()` prices
> and saves through `_save_on_behalf()` — the shop's rights, the customer's
> `owner`/`modified_by` put back — and neoffice-maintenance#277 tracks what
> `update_cart` must do before the next merge of the fork.

> **`get_web_items_qty_in_stock()`** (`utils/product.py`) is the bulk version
> of the shop's stock rule — same SQL, one query per warehouse for thirty
> variants instead of thirty calls. With multi-warehouse on, the grid shows
> `get_aggregate_stock()` per variant, the figure the cart will honour.

<!-- //// Neoffice — documents the price-list resolution added in 6696be727a "feat(quick-order): le prix du client, et la commande en Excel": the grid used to price at the site tariff only -->
> **The grid prices what the cart will charge.** `customer_price_list()` is
> `_set_price_list()`, the cart's own resolution — the site's tariff, else the
> customer's default list (or their group's), else the shop's — and every
> variant goes through ERPNext's `get_price()` with the customer's group and
> party, so the shop's pricing rules apply as on the product page. A rule shows
> as the list price struck through next to the price. Measured on osiris: a
> plain customer sees 99.80 → 89.82, a reseller whose Customer carries
> `default_price_list = Vente B2B` sees 79.80 → 71.82, and both carts bill
> exactly that.

<!-- //// Neoffice — documents the two upstream ERPNext pitfalls found while reading the CI (7fbb9e4181 "docs(quick-order): les deux pièges ERPNext standard trouvés en lisant la CI"): the mrp-read-before-assignment crash in get_price, and modules run twice on the same CI site inheriting each other's leftover fixtures -->
> **Upstream's `get_price` crashes on a priced item with no pricing rule.** It
> sets `mrp` only inside `if pricing_rule:`, then reads it two lines later — so
> on a *stock* ERPNext, any item that has a price and matches no rule (the common
> case) raises `UnboundLocalError`. Our erpnext fork captures `mrp` before that
> block, so nothing shows on the fleet; it only bites the CI. This is a *second*
> upstream gap, separate from the missing `warehouse` keyword (which raises
> `TypeError`) — code that must hold on stock ERPNext has to catch **both**.
> `_price_of` falls back to the plain Item Price rate (`_raw_price`): no rule
> means no discount, so the list rate is exactly what the cart carries. Drop the
> shim once the CI's ERPNext carries the fork's `get_price`.

> **The CI runs some modules twice on the same site, and what one run leaves, the
> next inherits.** The blocking step runs each module on its own, then the
> informative step runs `run-tests --app webshop` on that *same* `test_site`. A
> test that writes to a fixture nobody deletes must restore it in `try/finally`
> (and commit the restore — a downstream commit escapes the rollback), and
> `setUpClass` should reset defensively. Real case: `test_quick_order` set
> `Customer.default_price_list` to the reseller list and never put it back, so
> the informative run repriced three tests at 80 instead of 100.

**The way in from the catalogue.** A quiet link next to the search box (`.wsp-quick-order-link`,
`views.js` `prepare_search`), offered by `listing_context.quick_order_url()` to whoever may use
the page — `quick_order_offered()`: require_shopper's rule without its side effect, since
`get_party()` creates a customer for an account that has none and a page view must never do that.

**The order as a spreadsheet.** `utils/order_export.py` → `download_order_xlsx`
(GET, `doctype` + `name`): a bold header row, one line per item with code,
name, the variants' attribute columns, barcode, quantity, unit, rate and
amount, then a summary block (order, date, customer, status, currency, totals).
Same permission as the order page (`frappe.has_website_permission`); anybody
else gets 403. Linked from the order page's Actions menu and from the thank-you
page, for every customer.

Tests: `quick_order/test_quick_order.py` (the gate for a customer, a visitor
and an account without customer, search by code, name and barcode, site
scoping, tariff of the site, the batch and its capping — all with an in-memory
Webshop Settings and a fake Website Profile on `frappe.local`, nothing written
to the Single) and `tests/e2e/specs/10-quick-order.spec.js` (`b2b` types,
reloads and sends; `client` is served; `invite` fills a guest cart where the
shop sells to visitors, and is sent to sign in elsewhere).

### What search engines, feeds and AI crawlers read (`webshop/webshop/seo/`)

One package says what the shop tells the outside world, so a page, its structured data
and (lot 3) a Merchant Center feed can never say two different things about a product.
The study, the rules and the plan live in Obsidian (`Neoffice/SEO-GEO-Shopping/`), the
defects in neoffice-maintenance#691.

- **One JSON-LD graph per page, no microdata anywhere.** The product page carried a second
  Product in microdata, named "Code article:", holding the names and prices of the recommended
  products; the tiles' `itemprop`s attached to the page's product. `seo/test_seo.py` fails on
  any `itemscope`/`itemprop` in the templates or `views.js`. The breadcrumb's JSON-LD is
  printed by `includes/breadcrumbs.html` itself, from the trail it shows.
- **The product graph is built in Python from what the page computed** (`seo/facts.py` →
  `seo/jsonld.py` → `context.product_jsonld`, printed once by `item.html`): the price the buy
  column prints (× `conversion_factor`), the struck price only when `formatted_mrp` is printed,
  a sale's dates in ISO 8601 with the site's offset, the gallery's pictures, a GTIN only when its
  check digit is right and it is the item's own unit, a `sku` without whitespace, the reviews
  block's rating and reviews, the characteristics, the videos Google can describe. The feed
  (lot 3) reads the same facts. A failure is logged and costs the markup, never the page.
- **Declare only what the page shows.** A gift card's page shows amounts to choose, and a
  model's page shows the variant selector: neither prints a price, so neither gets an offer —
  a polo's page offered 39.00 in its markup and nowhere in its HTML (2026-09-24). The variants'
  offers belong in a `ProductGroup`, which waits for decision D-1 of the plan.
- **Availability comes from `seo/availability.py`, never from `product_info.in_stock`**, which
  `get_product_info_for_website` only fills when the shop DISPLAYS its stock: a shop hiding it
  told Google everything was out of stock. A shop that takes orders beyond its stock is
  `BackOrder`.
- **The site's identity is the chrome's, declared once on the home page.** builder's
  `site_graph.py` prints the `WebSite` and the `Organization` there and calls the
  `site_organization` hook: `jsonld.site_organization` makes it an `OnlineStore` (legal name,
  a Swiss UID as `vatID`), declares the return window and the free delivery the product page
  promises (`site_policies`, only in the company's country), and returns the physical store as
  a `Store` node (the Store tab's address, hours and closures). Every offer points at those
  policies by `@id`, only when the home page declares them. `seo/site.py::shop_name()` asks the
  chrome for the site's name first (builder's `display_name`), so og:site_name, the title
  suffix and the seller say what the home page says, per site.
- **The site's icon is builder's too** (`site_icon.py`): the icon somebody chose, else a PNG
  drawn from the chrome's mark or the site's initial, served at `/site-icon.png?v=<key>` and
  `/favicon.ico`; every website page names it, the desk keeps its own.
- **`/sitemap.xml` is the index** (pages, products, categories, blog); the lists are built in
  `seo/sitemaps.py` with the catalogue's own scope (`product_data_engine/catalogue_scope.py`,
  shared with `/shop-by-category`). No brand URLs until real brand pages exist; no
  `changefreq`/`priority`; `lastmod` only when true. The pages sitemap names the shop's
  listings instead of calling `frappe.website.router.get_pages()`, which dies on any non-UTF-8
  file in any app's `www` folder (macOS `._*` files, osiris 2026-09-24).
- **robots.txt**: `seo/robots.py` fills it when nobody wrote one (the `update_website_context`
  hook in `seo/meta.py`). Paths are anchored (`/cart$`, `/cart?`), or `/cart` would close
  `/cartes-cadeaux`; `/api/` stays open while the category grids load through it.
- **noindex, canonical, descriptions**: `seo/meta.py` — private pages and searched or filtered
  listings are `noindex, follow`; the listings name one canonical; a category without text says
  what it holds. What narrows a listing (search, facets, price range) is one tuple,
  `seo.meta.LISTING_PARAMETERS`, read by robots.txt, the `noindex`, the canonical and the
  server's first page: three copies had drifted, and a listing narrowed by price was neither
  closed nor `noindex`. Generic strings get a translation `context`: `suite` translates "{0} at {1}"
  as a time, and Frappe's merged catalogue lent it to ours.
- **A route change leaves a 301** (`seo/redirects.py`, `doc_events` of Website Item and Item
  Group), written straight into `Website Route Redirect` rows: `WebsiteSettings.save()` would
  validate the whole document and could refuse a product's save for an unrelated setting.
  Frappe's `resolve_redirect` extends the hooks list it gets from `get_hooks` (cached for the
  request), so a test resolving twice in one request clears `frappe.local.cache` in between.
- **A listing's first page is in its HTML** (lot 2): `server_listing` in
  `product_data_engine/listing_context.py` asks the listing API for the page the script's first
  request finds for a visitor with no preference (locked filters, default stock toggle, default
  sort, `?start=`), and `includes/listing_ssr.html` prints its cards and a pager of real links.
  A searched or filtered listing stays the script's. `views.js` keeps the server's cards on screen
  until its first result replaces them — no skeleton over them, no jump — and its own pager is
  made of links too. Each page of a series is its own canonical. Beyond the last page a `www`
  listing answers 404 through `context.http_status_code`: frappe renders a
  `PageDoesNotExistError` raised during a render at the request's status, 200 (a soft 404,
  `serve.handle_exception`; fixed in the `frappe` fork for the other pages). A category's
  sub-category pills come with the page too (`includes/sub_categories.html`,
  `listing_context.sub_categories`, which the listing API answers with as well), and only
  towards a child group that carries something this site shows: the script inserted them above
  its toolbar once the listing had loaded (70px of drop measured on osiris), and once more after
  every filter change — two rows of the same pills after one click.
- **The skeleton's `<style>` gave the product areas their 10px margin**: skipping the skeleton
  lost it, and the grid rose 26px under the toolbar. `add_product_loader_styles()` injects the
  styles alone, on both paths.
- **A visitor reads the settings' display switches, never the document** (neoffice-maintenance
  #711): `get_shopping_cart_settings` (allow_guest) and the listing API answered all of Webshop
  Settings — the assistant's model endpoint, its Raven channel, its token price. Over HTTP both
  answer `public_settings()`; a switch a page's script must read goes into `PUBLIC_SETTINGS`
  (`webshop_settings.py`), and Python callers keep the whole document.
- **The Google Merchant Center feed** (lot 3, `seo/feeds/google.py`): one RSS file per site,
  written by a nightly job and by the button of the settings' Google Shopping tab, served at
  `/feeds/google.xml?token=…` (404 without the switch, the token and a file). It reads the page's
  facts, priced as a visitor with no account (`serving()`), because Google compares the feed with
  the page and refuses an item over a cent. A model's variants are the items, tied by
  `item_group_id`; gift cards, services, excluded items and groups are left out and counted in
  the report. A site that hides its prices or sells only to businesses has no feed.
- **`frappe.set_user()` inside a web request spoils the session of whoever made it.** It sets
  `session.sid` to the user's name and empties `session.data` on the live object, which the
  request writes back to the cache when it ends. The feed's button therefore queues a job
  (`generate_now` → `generate_feeds(notify=user)`, which sends the report over realtime), and
  `serving()` raises where `frappe.local.session_obj` exists — only an HTTP request has one.
- **A pull request runs a third check, "Frappe Linter"** (`semgroup-rules.yml`, frappe's
  semgrep rules, only on the lines a PR changes). Read it with the other two: it was red on two
  PRs while the tests were green, and it had found the two defects above plus a controller
  method named `after_save`, a hook Frappe never calls. A reviewed finding carries
  `# nosemgrep: <rule id>` with the review written next to it. Replay it locally with
  `uvx semgrep scan --config <frappe/semgrep-rules>/rules --baseline-commit origin/version-15`.
- **`ci.yml` cannot run on a working branch by hand**: it installs the frappe branch named like
  the ref (`github.base_ref || github.ref_name`), so a `workflow_dispatch` on `seo/…` dies at
  the install. Open a draft pull request against `version-15` instead.
- `tests/e2e/specs/17-seo-crawler-view.spec.js` reads the pages with no JavaScript, the way AI
  crawlers and Google Shopping's checks do.

## Integration Points

### ERPNext Dependencies

Required ERPNext modules:
- **Stock**: Item, Item Group, Warehouse
- **Selling**: Quotation, Sales Order, Sales Invoice
- **Accounts**: Payment Request, Payment Entry, Loyalty Program
- **CRM**: Customer, Address, Contact

### Payments App

The `payments` app is required for payment gateway integrations (Stripe, PayPal).

## Testing Strategy

Two layers, and they answer different questions.

### Python tests — the endpoints

Tests are organized by module:
- **DocType Tests**: `webshop/webshop/doctype/[doctype]/test_[doctype].py`
- **Module Tests**: `webshop/webshop/[module]/test_[module].py`
- Tests follow Python unittest conventions
- Use `frappe.set_user()` to test different user contexts
- Use `frappe.get_doc()` and `.insert()` to create test data

```bash
# On a real site (dev or prod), run modules one at a time and skip the fixtures:
bench --site sitename run-tests --skip-test-records --module webshop.webshop.utils.test_discount_query

# The whole app only works on a site that has ERPNext's test records:
bench --site sitename run-tests --app webshop
```

**171 tests over 15 modules, green on `prod.local`** (second-hand 8, cross-sell 10, follow-ups 16 and desk 4, added on 2026-09-03). Three modules are not in
that count — `shopping_cart`, `website_item`, `product_data_engine` — because
they are built on ERPNext's test fixtures (`_Test Company`,
`_Test Price List India`, `_Test Tax 1 - _TC`). Run those on a dedicated test
site; bending them to a real site would make them less faithful, not more useful.

**The informative suite's 23 errors belong to four modules**, measured on 2026-09-16 on the run of
`b5ef1c3f86` (358 tests, 23 errors, 39 skipped): `product_data_engine` 8, `multi_warehouse` 7,
`website_item` 7, `shopping_cart` 1, and nothing else. The first three are the fixture-bound ones
just named; `multi_warehouse` dies on `TypeError: get_price() got an unexpected keyword argument
'warehouse'`, the keyword only the fork carries — so that gap costs seven errors here, not only the
one test that skips itself. None of the four can join `ci.yml`'s blocking list while the CI runs
stock ERPNext. Read that log for what it is: the full-app run prints failures only, so a module
absent from it is not thereby green — it may have been skipped entirely — and a module green in the
full run can still fail alone, without the data an earlier module left behind.

The two modules that decide what a customer pays carry the most tests:
`test_multi_site` (34) checks that the site's price list beats every caller's
default, that a professional site refuses an anonymous cart, and that the SQL and
ORM scoping paths never disagree — plus, throughout, that all of it degrades to
nothing on a single-site shop. `test_payment_handler` (13) covers idempotency —
one token, one charge — and who may conclude a payment, an `allow_guest`
endpoint whose id travels in a redirect URL.

> **A green test is not a test.** Before this suite was audited, six
> `test_payment_handler` cases passed while asserting nothing: two applied the
> fix to a `MagicMock` *inside the test* and checked their own line, one called
> `self.skipTest()` unconditionally, three skipped on an absent custom field.
> Read what a test asserts, not whether it is green — and read the *skipped*
> count.

> **A module that skips on an empty site is green by day and red by night.**
> `test_product_page` reads `_published_item()` and skips when the site has no published
> Website Item: the CI's fresh site has none, so the blocking step passed while the nightly
> "Tests" run, which has data, executed them and failed three times over (#399, seen only at
> night, 2026-09-13). Being in `ci.yml`'s blocking list is not enough: a module that needs a
> published item must create it (`make_test_item()` and a Website Item) instead of skipping,
> and a skip must be read as "not run", never as "passed".

> **Ask the site for its fixtures, never assume them.** `webshop.webshop.tests.utils`
> resolves the item group, price list, customer group and company at runtime.
> The upstream tests hard-code "Products", "Standard Selling" and
> "All Customer Groups" — none of which exist on a site installed in French, so
> every one of them died on a LinkValidationError before its first assertion.
> `make_test_item()` wraps ERPNext's `make_item` for the same reason.

<!-- //// Neoffice — documents the _Test Comm Account 1 / default_outgoing trap found while auditing the assistant test suite (74db9a51d5 "test(assistant): la spec tourne aussi déconnectée, et repart d'une conversation neuve") -->
> **A test run on a real site kills that site's outgoing email.** Any
> `bench run-tests` on `prod.local` — even a module that sends nothing, like
> `test_store_hours` — recreates Frappe's fixture Email Account
> `_Test Comm Account 1`, and it takes `default_outgoing` from the shop's real
> account. Its SMTP host is `smtp.example.com`, which does not resolve, so every
> mail after that fails: on osiris the queue held 281 Error, 108 stuck Sending
> and 41 Not Sent before this was found. `--skip-test-records` does not prevent
> it. After running tests on a real site, put the default back:
> `frappe.delete_doc_if_exists("Email Account", "_Test Comm Account 1")` then
> set `default_outgoing` on the shop's account. The symptom a customer sees is a
> modal "Incorrect Configuration / Outgoing mail server or port invalid" popped
> by a `frappe.throw` inside `frappe.sendmail` — which is why the assistant's
> escalation mails go through `_send_quietly`.

> **`--skip-test-records` is what makes the suite runnable on a real site.**
> Without it, Frappe first builds ERPNext's test records and crashes on a
> Warehouse whose company is null. And if a test record on the site is itself
> inconsistent, *every* module fails before running: an Email Account with
> `enable_automatic_linking` but no `enable_incoming` blocked the entire suite
> this way, with an error naming neither webshop nor the module under test.

> **A Single doctype survives `frappe.db.rollback()`.** Anything a test writes to
> `Webshop Settings` stays written — a test run reconfigured a live shop this
> way. Snapshot with `snapshot_webshop_settings()` and restore with
> `restore_webshop_settings()` (both in `webshop.webshop.tests.utils`).
> Same rule for `frappe.db.commit()` inside a whitelisted endpoint: it escapes
> the test rollback entirely.

<!-- //// Neoffice — documents a test-suite pitfall found while auditing the suite (90baa6a45 "docs(tests): un Single pollué fait rater silencieusement une Pricing Rule"): get_pricing_rule_for_item filters on company, and a test creating its rule in default_company() while the code prices with Webshop Settings.company can silently miss the rule when the two diverge, which happens in the full `run-tests --app webshop` run because ERPNext-fixture modules leave stale values on the Single that survive rollback. -->
> **And a polluted Single makes a Pricing Rule silently miss.**
> `get_pricing_rule_for_item` filters on the **company**. A test that creates its
> rule in `default_company()` while the code under test prices with
> `Webshop Settings.company` never sees the rule apply once the two diverge — no
> error, just an undiscounted price. They *do* diverge in
> `run-tests --app webshop`: the ERPNext-fixture modules leave
> `company = "_Test Company"` and `price_list = "_Test Price List India"` on the
> Single, which survives the rollback, while `default_company()` still answers the
> real company. A targeted-module run starts from a clean Single, so the defect
> shows **only** in the informative suite. Create the rule in the company the code
> prices in. Note too that `ensure_shop_settings()` copies `selling_price_list()`,
> which *honours* a list already set on the Single — it normalises less than it
> looks. When a failure exists only in the full-app run, push a temporary `print`
> into the test and read the CI log: the ERPNext-fixture modules die on a French
> site (no "Item Group: Products"), so no local run can reproduce it.

> **Fixtures built in `setUpClass` need a commit.** `FrappeTestCase` rolls back
> between tests, and that rollback takes uncommitted class fixtures with it —
> the tests then report their own data as missing. Commit at the end of
> `setUpClass`, and purge in `tearDownClass` (and again at the start of
> `setUpClass`, for whatever an interrupted run left behind).

> **`frappe.enqueue` does not run inline under tests.** `is_async` stays true, so
> a rebuild triggered by `save()` is handed to a worker that may not exist. A
> test asserting on a cache must rebuild it itself — see
> `reconstruire_cache_variantes()` in `test_variant_selector.py`.

### Browser tests — that the pages actually work

`tests/e2e/` — Playwright, ~90 tests across desktop, mobile, B2B and multi-site. They cover
what the endpoints cannot say: sign-in, account creation, catalogue, cart
(including multi-warehouse), the four-step checkout, and **a real Stripe charge**
against test keys.

```bash
cd tests/e2e && npm install && npx playwright install chromium
npm test                # everything
npm run test:customer   # signed in, desktop
npm run test:guest      # signed out (sign-in, account creation, what a visitor must not reach)
npm run test:b2b        # the B2B tunnel, which has its own customer and its own page
npm run test:payment    # the Stripe scenarios
npm run test:multisite  # both domains (B2C / B2B)
```

Credentials live in `~/.config/webshop-e2e.env` (chmod 600), never in the repo.
Full setup, gotchas and cleanup: `tests/e2e/README.md`.

> **Use `npm test`, not `npx playwright test`.** `npx` pulls its own copy of
> Playwright, and two versions in the same run make every spec fail to load with
> "test.describe() called in a file imported by the configuration file" —
> an error that points at your spec and has nothing to do with it.

> **A skipped test reads exactly like a passing one.** A conditional
> `test.skip()` firing for the wrong reason leaves the summary green: one run
> reported "18 passed" while **23 tests were being skipped in silence**. After
> touching the suite, read all three numbers — passed, failed, *skipped*.

> **The Stripe specs create real documents** on the target site (Payment
> Request, Sales Order, Payment Entry) using Stripe's public test cards against
> a `pk_test_` key. No money moves, but the orders are real. Cleanup commands
> are in `tests/e2e/README.md`.

> **The suite buys the first product it finds — and a second-hand unit is one
> of a kind.** The newest product in the catalogue was a used unit with one
> piece in stock; the B2B spec ordered it for real, and seven cart tests then
> failed on an item nobody could add twice. `premierArticleAchetable` skips
> second-hand units, and every helper reads the product code from the buy
> button: the Builder cart drawer sits in the header and its lines carry
> `data-item-code` too. After a Playwright upgrade, run
> `npx playwright install chromium` first — otherwise every test is red with
> "Executable doesn't exist", and the shop has nothing to do with it.

### The visual harness, and what moving the styles taught

`tests/e2e/visual/` (`capture.mjs`, `compare.py`, `pages.json`) captures the shop's
pages before and after a change and says what moved, page by page, in pixels and in
height. It is the condition of every lot of the theme work (Obsidian note 19): a
change to the templates or the stylesheets is not done until the comparison is
read. Usage and the reasons behind each choice are in `tests/e2e/README.md`.

> **A capture is only worth what it excludes.** Three things had to be silenced
> before two captures of the *same* build agreed (0.00 %): the page is **not
> scrolled** (scrolling asks a listing for its next batches, and 96, 120 or 168
> products arrived depending on the server's load — lazy images are woken with
> `loading=eager` instead); transitions and animations are frozen (a sticky header
> caught mid-slide is a difference); and only `<main>` is captured — the site
> header, the theme's title block and the footer are the site chrome, which changes
> on its own: another session regenerated osiris' design during a verification,
> and every page "changed" by 30 %. A page captured on a 502 is `INVALID`, not
> compared. Read the `items` column before reading `MOVED`.

> **No `<style>` lives in a template any more** (lot 0a, 2026-09-11). Page styles
> are partials of the shop bundle (`public/scss/webshop_*.scss`); a component a
> Builder page can include (product carousel, brand carousel, opening hours) has its
> own `<name>.bundle.scss` and prints it itself, once per request, through
> `utils/assets.py::component_css` — a Builder page loads neither
> `web_include_css` nor `web_include_js`. Two exceptions on purpose:
> `www/maintenance.html` (a self-contained page) and two rules in `macros.html`
> (a fragment rendered inside Builder pages).

> **A rule inline on one page becomes a rule on every page once bundled.** The
> harness found six: `thank_you.html` capped `.website-image` at 50 px and the main
> picture of every product page became a thumbnail; `my_addresses.html` restyled
> `.card`, `.card-title` and `.badge` (Bootstrap classes), `cgv.html` `.page-title`,
> `gift_cards.html` `.badge-dark`, `payment-success.html` `.progress-bar`, and
> `item.html` put `html { scroll-behavior: smooth }` on the catalogue too. Every
> page-local rule is scoped on its page's root class (added to the template when it
> had none: `.thank-you-page`, `.my-addresses-page`, `.cgv-page`). When moving
> styles, list the selectors that are Bootstrap's or an element's before trusting
> a green diff.

> **`context.title` is the heading, not only the tab.** The site chrome prints it
> as the H1 and as the last breadcrumb, so a controller that suffixes it with the
> shop name for SEO ("Fleece | <shop>", reported on a client shop) writes that suffix
> on screen. The product page had the split since July (`context.html_title`, fed to
> `{% block title %}`); the category page got it on 2026-09-11, with
> `tests/test_item_group_page.py`. The suffix itself is Website Settings' `app_name`
> — "Neoffice" on an instance nobody renamed.

> **`bench run-tests` on `prod.local` is refused by the fleet's bench** (a guard from
> incident #245: a fixture takes the default outgoing mail account). Osiris'
> `subtest.local` has no webshop. A new test module runs in CI only — put it in
> `ci.yml`'s blocking list, or it is never read. Since `efcf65bd61` the workflow checks itself:
> a step compares the `test_*.py` on disk with the modules the workflow names, and fails the
> pipeline on a test file nothing runs, or on a module named for a file that is gone. It caught
> nine unlisted modules the day it landed, one of them three tests that were false as well as
> invisible.

### The shop's design tokens (`--wsh-*`)

`public/scss/webshop_tokens.scss` is the one place a colour, a radius, a shadow or
a duration is written; every other partial draws with `var(--wsh-…)`. Each token
reads the site chrome's variable first (Builder's `theme_variables.html` puts
`--primary-color`, `--text-color`, `--radius`, `--shadow`, `--transition`… on every
page, the shop's included), then Frappe's token, then a literal equal to what the
shop drew before it had tokens. Names say what a thing *means* — `--wsh-muted`,
`--wsh-line`, `--wsh-ok-soft` — never what colour it is. The partial is imported
first by the shop bundle and by every component bundle a Builder page can include.

> **Builder's `--transition` is a duration and an easing (`200ms ease`), not a
> shorthand.** `--wsh-motion` aliases it and is used as `transition: all
> var(--wsh-motion)`; writing `transition: var(--wsh-motion)` yields an invalid
> declaration and no transition at all.

> **`color: #fff` means two different things.** On a block that paints
> `--wsh-primary`, white is `--wsh-on-primary` (Builder's `--primary-text`, which a
> light brand colour sets to dark); anywhere else it is `--wsh-on-ink`, white on a
> dark badge or overlay. A shadow's depth is read off its **blur**, not its alpha:
> `0 1px 2px rgba(0,0,0,.3)` is `--wsh-shadow-sm`, `0 16px 60px rgba(0,0,0,.08)` is
> `--wsh-shadow-lg`. A flat chrome sets the shadows to `none` and the shop goes flat.

> **A block painted with `--wsh-text` writes with `--wsh-bg`.** The text colour is dark on a
> light site and light on a dark one, so the block inverts with the site and its ink must
> too; the pager's current page and the active view toggle always did. The active-filter
> chip, the second-hand badge, the loyalty tooltips, the disabled button's tooltip, the
> video tile's play mark under the cursor and two Bootstrap badges wrote white on it, and
> vanished on a dark site (1.09:1, 2026-09-14) while the audit said 0: the chip only exists
> once a filter is on. `tests/test_stylesheet_inks.py` refuses the pair, and a badge, button,
> chip or tooltip painted that way without naming its ink (Bootstrap's is white). A state
> that needs a click is audited with `WEBSHOP_CONTRAST_CLICK` (e2e README).

> **The opening-hours block keeps its own tokens, namespaced `--wsh-oh-*`** and
> reading the shop's; its dark-scheme and footer variants are the block's own
> design. Two token families sharing a name would silently shadow each other.

> **Measured on osiris (2026-09-11), 0.5–2.5 % of pixels moved on 13 pages and no
> height changed:** inputs and cards took the chrome's corner radius, muted text
> took the chrome's 60 % tint, input borders went from `#999` to the line token.
> Left as literals on purpose: Google's brand colours on the sign-in button, the
> white glass buttons over photos, three status borders in the checkout and cart.

> **`--wsh-primary` is the page's action colour, not the brand's primary.** It reads
> `--btn-primary` first: the token the site chrome fills, since Builder 806e0c18
> (2026-09-13), with what its own buttons wear — the primary when it reads on the page
> background, a deeper shade of it when it is pale, the secondary when the primary *is*
> the background, the text colour last (`header_footer.py::button_colours`) — and the
> token frappe's own `.btn-primary` reads. `--wsh-on-primary` reads `--btn-primary-text`.
> On a site whose primary is its page background, the raw primary painted an invisible
> "add to cart" next to a readable header button. Without the chrome (a plain frappe
> site, or one whose chrome predates the token), everything falls back to the primary,
> which is what the shop drew before.

### The shop's buttons (`webshop_buttons.scss`)

The site chrome draws every button of a site through `:where(.u-btn)` — inline-flex,
12px 24px, the site's radius, the body font at .95rem / 500, line-height 1 — and the
shop drew its own (Frappe's 6px 16px at 14px, a 4px radius whatever the site, a buy
button at 600), so a customer crossed a visible seam between a page and the shop of the
same site. `webshop_buttons.scss` writes the shape once, as a mixin the product page and
the variant footer include, gives every `.btn-primary` the action colour and its label,
and draws `.btn-outline-primary` / `.btn-secondary` like the site's outline (transparent,
the ink, a `currentColor` border, a 12 % tint under the cursor). Small buttons, the
pager, the spinner keys, the catalogue's view toggle (whose active button wears
`.btn-primary` as a state) and the tile's quiet button keep their own size.

> **Measure the parity where the shop draws.** The chrome's `:where(.u-btn)` rule is on
> the shop's pages too, so an `<a class="u-btn u-btn--primary">` injected into a shop
> page is the reference, measured on the same page: `13-site-buttons.spec.js` compares
> the buy button, the cart's and the checkout's buttons with it, and the outline buttons
> with `.u-btn--outline`. Measured on osiris and on a client site on 2026-09-13: 41.2 px,
> identical padding, radius, font and colours.

> **`.font-md` pins 14px with `!important`** (`webshop_cart.scss`, upstream's) and the
> cart's and the checkout's buttons carry it in their markup: the mixin overrides it on
> the buttons it shapes — the size of a button is the system's, not the markup's.

### The ground under the shop's pages (`webshop_ground.scss`)

Every page the shop renders carries `body.product-page` — upstream's name for the
product page alone; the shop gives it to all of its pages, and **a new page controller
must set `context.body_class = "product-page"` too**, or it keeps Frappe's light-ground
literals. Under that class, `webshop_ground.scss` re-anchors Frappe's own tokens
(`--text-color`, `--heading-color`, `--text-muted`, `--text-light`, `--icon-stroke`) on
the `--wsh-*` tokens inside the page wrapper and the chrome's title band, makes every
card the shop draws a chrome surface (`.frappe-card`, `.category-card`), and gives
Frappe's controls (inputs, selects, default and outline buttons, tabs, the current page
of the pager) the tokens.

> **A light chrome proves nothing for a dark one.** The tokens read the chrome, so their
> values only exist once a real site renders them. The theme shipped to a dark reseller
> site on 2026-09-11 with the product title, the filter heading, the search icon and the
> hearts dark on dark: the chrome's own rule of 2026-09-09 (`body.product-page … { color:
> #1f272e }`, written while the shop painted a white ground whatever the site) turned the
> shop's ink dark once the shop followed the chrome. And the reverse on a card Frappe
> paints white: the shop's light `--wsh-text` on `--card-bg`. Before a client deploy, run
> `tests/e2e/visual/contrast.mjs` against **that** site (see the e2e README).

> **`var(--x)` resolves where the property is defined, not where it is read.**
> `--wsh-text: var(--text-color)` on `:root` keeps the chrome's value even when an
> ancestor redefines `--text-color` — which is what lets the ground re-anchor Frappe's
> tokens on the shop's. At equal specificity the chrome's inline sheet (in the body) comes
> after the bundle (in `<head>`): the element in the selector (`div.page-content-wrapper`,
> `section.site-page-header`) is what wins.

> **Frappe's literal inks get a floor; Frappe's surface tokens follow the chrome** (2026-09-14).
> Frappe's and ERPNext's bundles compile some inks from Bootstrap's light-ground variables:
> every heading `#171717`, a `.table`'s text `#525252`, `.text-dark` `#383838 !important`,
> `.text-muted` `#7c7c7c !important` and `.badge-secondary` white on that grey (3.97:1 on a dark
> site, 4.17:1 on a light one: the catalogue's "Filtres actifs", its pager, the toolbar's
> active-filter badges; they now read the site's muted ink, its text at 60 %), a
> white `.card`, ERPNext's `.order-items` gray-700, the account page's `--gray-900/700`. On a
> dark site the cart line's name, "Résumé du paiement", the checkout's headings and the
> summary's figures were dark on dark, the cart summary's labels white on a white card. The
> ground floors them behind `:where(body.product-page)` — the exact weight of the bundle's rule,
> winning because the shop's bundle loads after Frappe's and ERPNext's, so any rule of the shop
> (one class or more) still beats it — and points Frappe's surface tokens (`--fg-color`,
> `--card-bg`, `--control-bg`, `--modal-bg`, `--popover-bg`, the avatar's) at the chrome's on the
> body, so web forms, dialogs, toasts and the portal's cards follow. `--wsh-line-strong` is mixed
> from the chrome's ink and ground: it read Frappe's `--gray-300`, a literal no chrome
> redefines, and outlined the quantity box, the notes field and the upcoming checkout steps in
> white. A heading inherits: it reads like the box it sits in.

> **The customer's account pages are the shop's.** Frappe renders them (the portal menu's
> routes — orders, invoices, addresses, gift cards… — and `/me`, `/update-password`), so they
> never got the scope class: on a dark site they sat on Frappe's gray-50 with the chrome's light
> ink on white cards and forms. `shopping_cart/utils.py::update_website_context` adds
> `product-page` to them (`is_account_page`; the hook runs after the page's own `get_context`,
> so it adds, never overwrites), and `--body-bg-color` is the chrome's ground.
> `tests/test_account_pages.py` is in the CI's blocking list.

> **Audit the cart full and the checkout step by step, signed in.** The audit said 0 on a dark
> site whose merchant then found the cart and the checkout unreadable: it had only ever read
> them as a visitor with an empty cart. `WEBSHOP_SID` + a filled cart +
> `WEBSHOP_CONTRAST_REVEAL=.step-section` reads every step; `WEBSHOP_CSS_OVERRIDE=<file.css>`
> audits a locally compiled stylesheet against the client's real chrome before it deploys.

> **The shop's pages sit on the chrome's grid** (2026-09-14). The chrome lays its header, footer
> and title band on `--container-width` with `--container-padding` (`-tablet` under 768px,
> `-phone` under 576px — the thresholds of `header_styles.html`); the shop sat in Frappe's
> `main.container` (1290px, 5rem of padding from xl), so its content started 50 to 90px right of
> the logo and of the title above it — more once a site set its own grid (1440 / 48). The ground
> gives the page's outer container the chrome's grid: `main.container` under the page wrapper,
> the product breadcrumbs' container, and on an account page Frappe's container holding the
> portal sidebar (`:has(> .row > .main-column)`); a container nested in it — the checkout's
> second page wrapper, an account page's main column — adds no gutter, and the checkout's
> narrow-screen padding reset keeps to its nested container. Fallbacks are Frappe's values.
> Measured with the stylesheet served locally against a client's two sites, then deployed on
> osiris: the shop's content box equals the header's and the title band's to the pixel, at 1400,
> 1680 and 700px (`preview_grid`-style probe: content box = rect ± padding). The category page's cards
> were upstream's 300px squares with a 30px margin in a wrapping row: on a narrower grid they fell
> to two per row with a third of the width empty — the row is a filling grid now (auto-fill, 240px
> minimum), and its search bar and card column take the grid's edges. The visual harness caught it
> (`compare.py before after`: the page grew by 1440px); read its `height` column, not only pixels. The catalogue's
> tile row kept Bootstrap's -15px pull while its columns padded 6px: the first picture started 4px
> outside the grid (20px instead of 24 on a phone). The row's pull and the columns' gutter are one
> variable now (`--wsp-tile-gutter-half` on `#products-grid-area`).

> **The status shades follow the ground.** `--wsh-ok-strong` is
> `color-mix(--wsh-ok 70%, --wsh-text)` and `--wsh-ok-soft` `color-mix(--wsh-ok 14%,
> --wsh-bg)` (same for warn and danger): the text shade lightens and the box darkens on
> a dark site, and both stay within a few units of the old literals on white. A state
> button (the active view toggle, the current page) inverts the ink instead of using the
> primary: on one site the primary colour *is* the page background.

> **A CSS-only change deploys with `bench build --app webshop` and `clear-cache`, no
> restart** — the bundle hash sits in a Redis cache, not in the workers. Through the
> neoservice hop, run a long build under `nohup` and read its log: the hop closes the
> connection mid-build.

### One product card

`templates/includes/product_card.html` is the only product card, in four variants
(`grid`, `list`, `carousel`, `wishlist`). The listing endpoint
(`api.get_product_filter_data`) renders the tile of every item it returns —
`card_html` and `list_html`, through `utils/product_card.py` — and `grid.js` /
`list.js` only append what they are given; the carousel and the wishlist call the
macro directly. The `wsp-card*` classes are the hooks a theme styles; the legacy
classes (`item-card`, `product-title`, `like-action`, `cart-indicator`,
`btn-add-to-cart-list`, `go-to-cart-grid`, `cart-action-container`, `remove-wish`)
stay on the same elements because the stylesheet and the cart and wishlist
handlers read them — and the add-to-cart handler finds its "go to cart" twin with
`$btn.parent().find()`, so both stay direct children of the card's body.

> **Before this, the card lived in six places and three languages** (JS template
> strings, Jinja, a macro) and every fix was made three times — the second-hand
> badge was the last one. Measured after the change: 0.00 % on the catalogue, the
> item group, the wishlist and the product pages' carousels, 18 browser tests of
> the catalogue and the cart green. Two harmonisations on purpose: the carousel's
> discount badge reads "- 20%" like the catalogue's, and a card without picture
> shows `get_abbr`'s two letters everywhere.

> **Calling a macro from Python**: `frappe.get_template(path).module.product_card(…)`
> returns the rendered Markup; the sandboxed environment exposes `frappe.utils`,
> `frappe.session` and the jinja methods of `hooks.py` to it, but nothing from the
> page's context — pass the settings in. `course_offer_count` is the LMS app's and
> is guarded with `is defined`. The environment does not autoescape: titles and
> categories go through `| e`.

> **The cover-fit styles stay inline on the tile** (`aspect-ratio`, `object-fit`,
> the item's focus point): the Webshop Settings toggle must take effect without a
> `bench build`, and the focus is per item.

### The product page

`templates/generators/item/item.html` composes the page (2026-09-11, the one look the
shop has): a flat hero — the gallery on 60 % of the width, the buy column beside it,
sticky on a wide screen — then full-width sections that exist only when they have
something to show (recommendations, bought together, tabs, free content, reviews,
recently viewed). The gallery (`item_image.html`) follows the number of photos: a
mosaic from three (two large, then the rest, every row filled), a thumbnail rail with
two, one picture otherwise, a swipe strip on a phone; any picture opens the zoom. Its
tiles are portrait when Webshop Settings' image fit is Cover and square otherwise. The
buy column (`item_details.html`) keeps every control the cart, wishlist and
multi-warehouse handlers read (`item_add_to_cart.html` is untouched but for the "MRP"
prefix), adds the shop's **promises** (`item_promises.html`, `utils/promises.py`) and
three folds — description, characteristics, brand — as native `<details>`.

The promises are four fields of Webshop Settings (`free_shipping_from`,
`delivery_delay`, `return_days`, `promise_note`, section "Shopping Promises") which a
Website Profile overrides for its site through custom fields the shop adds to that
doctype (`patches/add_promise_fields_to_website_profile.py`); `get_shopping_cart_settings`
does the shadowing, `shopping_promises()` writes the lines, and an empty set prints
nothing — no block, no heading.

> **Never name a throwaway variable `_` in a template.** `{% set _ = list.append(x) %}`
> assigns None to the translation function, and the next `_("…")` in the template
> raises `'NoneType' object is not callable` — on the pages where that `set` sits at
> top level, which is why only the single-picture page answered 500 while the mosaic
> pages, whose `set` lived inside a loop, rendered. Use `_appended`, `_ignored`,
> anything else.

> **Upstream's product-page rules live in `webshop_cart.scss`** (`.product-container
> .item-cart .product-price` and friends, a 22px price, a 13px description, a padded
> 350px picture box). They outrank a lone class, so every rule of the new column is
> rooted on `.wsp-product`, and the gallery neutralises `.product-image` — a class the
> browser tests and the zoom still read — on its own containers. The `@media (max-width:
> var(--md-width))` blocks in that file never applied: a media query cannot read a
> custom property.

> **`.filter({ visible: true })` before `.first()`** when a locator can match a hidden
> twin: the gallery draws one layout for a wide screen and a strip for a phone, and the
> other is in the DOM but hidden; `first()` alone picked the hidden one and the mobile
> image test failed while the desktop one passed.

### The catalogue tile

`public/scss/webshop_product_card.scss` dresses the one card (`grid` and `carousel`
variants) and is imported by the shop bundle **and** the carousel bundle: no frame,
the picture first (square for an object on white, portrait 4/5 when Webshop Settings'
image fit is Cover, with the item's focus point), badges top left and the wishlist
heart top right over it, a second picture on hover when the item has a slideshow
(`utils/product_card.py::second_pictures`, one query per listing), then brand in small
caps, the name on two lines, the stock, the price, and a quiet button that only shows
under a cursor (`@media (hover: hover)`; always on a phone). Four columns from 1200 px
(`col-6 col-md-4 col-xl-3`), two on a phone; the carousel shows two cards and a half on
a phone so the half says there is more to swipe. The listing query
(`ProductQuery.fields`) carries `brand` and `slideshow` for it; the product page's
recommendations — manual (`get_recommended_items`) and automatic (`RAND()` in the same
item group) — carry `brand` and `item_condition`.

> **The old `.item-card` block of `webshop-web.bundle.scss` and the carousel bundle's
> `.card` rules are gone**, not overridden. What is left in `webshop_cart.scss` about
> `.product-container` is upstream's product page and still dead weight.

> **A fixture that reads the whole page reads the neighbours too.** `premierArticleAchetable`
> rejected any product whose page carried a `.condition-badge`, to skip one-of-a-kind used
> units; once the recommendations carousel badged its used items, every page carried one,
> the fixture answered "no product" and the suite skipped itself green (24 tests, 5
> skipped, none failed). It reads the buy column only now (`.product-condition`,
> `.wsp-buy .condition-badge`). Read the `skipped` count after every change to a tile.

> **Stars are painted through `--star-fill`, not `fill`.** Frappe's `#icon-star` symbol
> paints its path with `fill="var(--star-fill)"`, so a `fill` on the `<svg>` never reaches
> it: five hollow stars sat next to "4/5" until `.star-filled` set `--star-fill`. The
> Rating field stores 0..1; a review row that compares it with 1..5 draws nothing.

> **A `sid` minted with `bench browse` expires within the hour.** A probe or a capture
> that still carries it silently runs as Guest: signed-in pages render as a visitor's
> (empty cart, 403 on an order) and a comparison against them means nothing. Mint again
> before a signed-in run, and print `frappe.session.user` in any probe that matters.

> **The variant grid binds its button by class.** `document.querySelector('.btn-add-to-cart')`
> took the first such button of the document; the grid's own is
> `.variant-grid-footer .btn-add-to-cart`, and it now carries the chosen variant's
> `data-item-code`. Two demonstration products live on osiris for the eye
> (`DEMO-TRAIL-01`, five photos, reviews, bought-together, discount; `DEMO-TEE`, 3
> colours × 4 sizes, three sizes sold out) — `hide_variants` is on there so the twelve
> sizes do not flood the listings; the brand facet still counts them.

> **Both hero columns are sticky, and that is what makes the shorter one stay.** A
> sticky box only holds while its grid row runs past it, so under a tall mosaic the buy
> column stays, and under a long buy column the gallery stays — no script measures
> anything. The offset is 84px under a sticky site header (`body:has(.site-header--sticky)`),
> 24px otherwise. "Bought together" draws the carousel's tiles like the
> recommendations; a tile prints a price only when the item has one on the **shop's**
> price list (`Webshop Settings.price_list`) — the listing may price it through the
> customer's list, the helpers here do not.

### Product videos

Website Item carries a `videos` table (`Website Item Video`: YouTube, Vimeo or a
hosted file, a title, an optional poster). `utils/videos.py` turns a row into what
the page needs — the platform id read off the address as the browser shows it, an
embed URL (`youtube-nocookie.com`, Vimeo `dnt=1`) or the file's `src` and mime, a
poster (the merchant's, else YouTube's own thumbnail, else a hosted file's first frame
through `<video preload="metadata">`) — and `has_video`, a hidden Check mirrored in
`validate`, is what the listing query, the recommendations and the carousel read to
put a play mark on the tile. The gallery draws the videos after the photos, as tiles
with a play badge; the lightbox creates the player only then, and empties its host
on close so nothing keeps playing. `utils/test_videos.py` is in the CI's blocking list.

> **The lightbox lives under `<body>`, moved there on init.** A sticky box is a stacking
> context: the fixed overlay inside the sticky gallery column painted *under* the buy
> column, sticky too and later in the DOM, and the player sat behind the price. Never
> keep a full-screen layer inside the hero.

> **A third party is reached only on the click.** The poster is a static image; the
> iframe is created when the visitor presses play. A shop that would rather show no
> YouTube thumbnail at load attaches a poster.

### The variant selector

`item_configure_grid.html` / `.js` draws one row of chips per attribute, in the
template's order, the values in the attribute's own order (`get_all_variants_info`
returns `attribute_values`; numeric attributes sort numerically). A chip is struck
(`is-unavailable`, still clickable: the footer then says out of stock and hides the
button) when no variant in stock satisfies it given the other rows, and absent
(`is-impossible`) when no variant carries it. An attribute whose variants have their
own picture (a colour) shows picture chips, and the gallery's first picture follows
the choice through `window.wspGallery.showImage(url)` (`null` restores). The footer
(price, stock, add to cart) is the old one, and **its button carries `data-item-code`
only once a variant is chosen**: the browser-test fixture reads "a code on the buy
button" as "a purchasable article", and a code posted empty at load made four
catalogue tests open a template page. `12-variants.spec.js` runs signed out.

### Gift cards, seen from the shop

The product `is_gift_card` shows amounts as chips (`.wsp-gift__chip`, Webshop
Settings' `gift_card_amounts`, a custom amount when allowed); no unit line, no stock
line, no delivery or return promise under it. The line reaches the cart with a
pre-generated code in `gift_card_data`; the paid invoice (`create_gift_cards_from_invoice`)
mints a `Coupon Code` of type Gift Card for the customer, valid `number_of_valid_months`,
and sends `gift_card_notification`; the customer finds it on `/gift_cards` (linked from
the account menu — `standard_portal_menu_items`, which `bench migrate` does **not** sync:
`patches/add_gift_cards_portal_menu` runs Portal Settings' `sync_menu` for existing
sites — and from the cart's quiet links) and
redeems it through the coupon field: the discount is the card's balance, and
`process_gift_card_split` carries the remainder to a new card on the order. Measured
on osiris on 2026-09-13, end to end. A gift-card line carries no stock source and no
delivery estimate (`decorate_cart_line` skips it).

> **TWO families of gift card live on one instance, and both are spendable on both
> sides.** The till issues `coupon_type = "Promotional"` with `pos_next_gift_card = 1`;
> the shop issues `coupon_type = "Gift Card"`. Reading the type alone sent a till card
> down the promotional branch — its discount came from its Pricing Rule and its BALANCE
> was never decremented, and those cards carry `maximum_use = 0`, so nothing capped
> them either: a 15.- card granted its 15.- on a completed order and was accepted again
> on the next cart (measured 2026-09-22; POSNext had the mirror defect on ours, #646).
> `is_gift_card_coupon()` reads both, a card with no balance is refused, and a till card
> is **settled in place** — its balance goes down on itself and it keeps the code
> printed on the customer's card, which is how the till settles it. Only the shop's own
> cards are split. The rule is POSNext's, COPIED: webshop must hold without that app.

> **`card.save()` did not persist the balance; `frappe.db.set_value` does.** A 15.- card
> settled for 10.- came back with 15.- on it. A settlement that silently does nothing is
> the defect it was written to close, so the balance is written directly.

> **A gift card's document is named after a human label, not after its code**
> ("Carte cadeau CHF 100.00 - <someone> - YMI2-RYUC-DGM3" for the code
> `YMI2-RYUC-DGM3`). Every `coupon_code` field is a **Link**, so it carries the document
> NAME: webshop writes names everywhere (`coupon_list[0].name`, `gift_card_coupon`) and
> is safe, but anything that sends what a human typed dies on `LinkValidationError` —
> which is what happened at the till (2026-09-22). Renaming the existing documents would
> be worse than the disease; the rule is simply that **a code is resolved to a name
> before it touches a Link**, and that a new card should be named after its own code.

> Two merchant decisions the code does not make: VAT on the sale of the card (the item's
> tax template applies; a multi-purpose voucher is normally taxed at redemption) and
> loyalty points earned on buying one.

### Multi-warehouse on the product page

When a product has several sources, the buy column offers one radio per source with
its stock and its delivery estimate, and **the delivery promise follows the chosen
source** (`data-promise="delay"` in `item_promises.html`, updated by
`mw_sync_delivery_promise`); it falls back to Webshop Settings' text when the source
carries no delay. The settings' "delivered in 2 to 4 days" under a supplier source
saying ~15 days was a contradiction on one screen.

> **The catalogue tile's picture is centred by the card's own rule, not upstream's.**
> `.item-card-group-section .card-img` keeps a 1rem margin and a 210px cap: the picture
> sat 16px right and down in its box, clipped on two sides. On hover the second picture
> has its own ground and the first one fades: a contained picture leaves bands, and the
> first picture showed through them.

### Testing with a non-desk account

After any upstream merge, permission change or routing change, test with **three
identities**, not one — Administrator passes everything by construction:

1. **Anonymous** (logged out)
2. **Website User** (portal customer, no desk role) — the one everybody forgets
3. **Admin / staff**

For the Website User, probe the API from *their* session, not just the UI:
anything other than a `403` on private data is a leak. `01-authentication.spec.js`
does this for the anonymous case, and it is why the catalogue helpers read the
shop pages instead of `frappe.client.get_list` — which correctly refuses them.

## CI/CD

GitHub Actions workflow (`.github/workflows/ci.yml`) — **green, and it runs**:
- On push to `version-15`, on pull requests, daily at midnight UTC, and on
  demand (`gh workflow run ci.yml --repo bvisible/webshop --ref version-15`)
- Sets up Python 3.10, Node 18, MariaDB 10.6, Redis; installs Frappe, ERPNext,
  Payments and Webshop on a fresh site
- Installs the setup-wizard fixtures, then runs the ten modules that must pass
  everywhere — one at a time, failing on the first red one
- Then runs `bench run-tests --app webshop` as a **non-blocking** step, so the
  state of the whole suite stays visible without making red permanent

> **It had never run once on this fork.** The workflow listened only to
> `pull_request` and `schedule`; we push straight to `version-15` and GitHub
> does not run scheduled workflows on a fork. On top of that the workflow itself
> was `disabled_manually`. The red runs visible from this repo were upstream's
> (`frappe/webshop`, branch `develop`) — `gh run list` resolves to the upstream
> remote unless you pass `--repo bvisible/webshop`.

> **CI runs against *standard* ERPNext, on purpose.** Pointing it at
> `bvisible/erpnext` was tried and fails: our fork reads
> `Item.buying_standard_rate` and makes `Customer.default_currency` mandatory
> through a Custom Field and a Property Setter that belong to **no app** — they
> were created by hand on the server, and would not survive a reinstall. So the
> CI answers "does webshop hold up on a stock ERPNext"; what it cannot check is
> variant pricing by warehouse, since `get_price(..., warehouse=...)` only
> exists on our fork. That test skips itself explicitly there.
> The same goes for the cross-sell cart and catalogue tests: `needs_fork` in
> `test_cross_sell_offer.py` skips the five that need the fork's pricing guards
> and `get_price(..., warehouse=...)`; the rest of the module runs everywhere.

> **What CI found that the server could not.** Three suites passed on
> `prod.local` only because earlier runs had left their data behind:
> `multi_warehouse` (its customer), `item_review` (the contact linking user to
> customer), `variant_selector` (its variants). And a real defect: a fresh
> install created **3 custom fields out of 20** — `install-app` marks
> `patches.txt` as applied instead of running it, so a new shop started without
> `custom_idempotency_token`, and the first query in `create_payment_request`
> raised `Unknown column`, which the blanket `except` turned into "error
> creating the payment request". Nobody could pay. Fixed in
> `webshop/setup/install.py`: **a patch that creates a field belongs in
> `CHAMPS_A_CREER_A_L_INSTALLATION`.**

> **Filters in a drawer on every screen** is a Webshop Settings check (`filters_in_drawer`,
> off by default): the listing's `body_class` gains `wsp-filters-drawer`, and the
> stylesheet applies the phone's drawer rules — one `@mixin` in `webshop_catalogue.scss`,
> included under the phone's media query and under that class — at every width, gives the
> sidebar's column back to the products and shows the Filters button. The wide-screen
> sticky sidebar rule carries the id, so the drawer-mode rule carries it too.

> **`bind_price_filters` runs again after every filter change, so it must bind once.**
> The slider's bounds follow the result set, and the rebind stacked a new set of
> handlers with stale bounds on the same handles and inputs each time: after a few
> filters a drag fought itself. Namespaced events (`.wspPrice`) are removed before
> binding, the restored range is clamped to the current bounds, and the track is inset
> by half a handle so the handles stay inside the sidebar (2026-09-13).

> **A `/* … */` marker outside a `<style>` block prints on the page.** HTML has no
> such comment: the browser draws it as text. Two `//// Neoffice` markers had been
> written that way, just above the `<style>` they described, and both showed to
> customers — one of them right next to "Ajouter au panier" on every product page,
> the other on the catalogue. In a template the comment syntax follows *where the
> line sits*, not what it talks about: `{# … #}` in Jinja, `<!-- … -->` in HTML,
> `/* … */` only inside `<style>` or `<script>`. Marking a fork change is not a
> reason to reach for the wrong one.

