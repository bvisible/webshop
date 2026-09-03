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
- `/occasions` is `/all-products` with the Condition facet locked
  (`www/occasions`, `product_data_engine/listing_context.py`,
  `window.locked_field_filters`). Webshop Settings accepts a **Select** as a
  filter field for this; the facet only renders once a published item is not
  New. Badges: `grid.js`, `list.js`, `product_carousel.html` — three copies,
  plus `bench build`.

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

> **Ask the site for its fixtures, never assume them.** `webshop.webshop.tests.utils`
> resolves the item group, price list, customer group and company at runtime.
> The upstream tests hard-code "Products", "Standard Selling" and
> "All Customer Groups" — none of which exist on a site installed in French, so
> every one of them died on a LinkValidationError before its first assertion.
> `make_test_item()` wraps ERPNext's `make_item` for the same reason.

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
npm run test:client     # signed in, desktop
npm run test:invite     # signed out (sign-in, account creation, what a visitor must not reach)
npm run test:b2b        # the B2B tunnel, which has its own customer and its own page
npm run test:paiement   # the Stripe scenarios
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

### Testing with a non-desk account

After any upstream merge, permission change or routing change, test with **three
identities**, not one — Administrator passes everything by construction:

1. **Anonymous** (logged out)
2. **Website User** (portal customer, no desk role) — the one everybody forgets
3. **Admin / staff**

For the Website User, probe the API from *their* session, not just the UI:
anything other than a `403` on private data is a leak. `01-authentification.spec.js`
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
