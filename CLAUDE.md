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

**135 tests over 11 modules, green on `prod.local`.** Three modules are not in
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

GitHub Actions workflow (`.github/workflows/ci.yml`):
- Runs on pull requests (ignoring CSS/JS/HTML/MD changes)
- Sets up Python 3.10, Node 18, MariaDB 10.6, Redis
- Installs Frappe, ERPNext, Payments, and Webshop
- Runs all tests with `bench run-tests --app webshop`
- Triggers daily at midnight UTC
