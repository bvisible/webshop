<!-- //// Neoffice — added file (no upstream equivalent). How to run the Playwright suite, -->
<!-- //// what it needs, and what it leaves behind on the target site (d2a0754333 / -->
<!-- //// 1c36a8f365 / 7698e3fc18, 2026-08-27). Upstream ships no browser test at all; -->
<!-- //// these cover what an endpoint test cannot say — that the pages work in a browser. -->
# End-to-end tests (Playwright)

Browser tests for the shop: sign-in, account creation, catalogue, product page,
cart (including multi-warehouse) and the complete checkout tunnel.

They complement the Python suite (`bench run-tests --app webshop`), which covers
the endpoints. These cover what the endpoints cannot say: that the pages actually
work in a browser.

## Install

```bash
cd tests/e2e
npm install
npx playwright install chromium
```

## Configuration

Credentials live **outside the repository**, in `~/.config/webshop-e2e.env`
(`chmod 600`). Environment variables win, so CI can inject them.

```ini
WEBSHOP_E2E_URL=https://osiris.neoffice.me
WEBSHOP_E2E_USER=test.e2e@example.com
WEBSHOP_E2E_PASSWORD=…
# Optional — see "Multi-source article"
WEBSHOP_E2E_MULTISOURCE_ROUTE=products/…
```

The account must be a **Website User attached to a customer** (`Portal User`),
with at least two addresses so the address book is exercised. Set its password:

```bash
ssh osiris "cd /home/neoffice/frappe-bench && bench --site prod.local set-password <email> '<password>'"
```

## Run

```bash
npm test                   # every project
npm run test:customer      # signed in, desktop
npm run test:guest         # signed out (sign-in, account creation, what a visitor must not reach)
npm run test:b2b           # the B2B tunnel
npm run test:mobile        # catalogue + cart on a Pixel 7
npm run test:payment       # the Stripe scenarios
npm run test:multisite     # both domains (B2C / B2B)
npm test -- -g "address"   # by name
npm run ui                 # interactive mode
./node_modules/.bin/playwright show-trace test-results/…/trace.zip   # replay a failure
```

> [!warning] `npm test`, never `npx playwright test`
> `npx` downloads **its own** copy of Playwright. Two versions in one run and
> every spec refuses to load with "test.describe() called in a file imported by
> the configuration file" — an error that points at your spec and has nothing to
> do with it. The npm scripts above use the local binary.

## Layout

| File | Project | Covers |
|---|---|---|
| `01-authentication.spec.js` | `guest` | E-mail check, account creation (refusals **and** the real journey), sign-in, the dialog, what an anonymous visitor is walled off from |
| `02-catalogue.spec.js` | `customer`, `mobile` | Product listing, product page (single heading, price, picture, empty reviews), adding to the cart |
| `03-cart.spec.js` | `customer`, `mobile` | Lines, quantities, removal, and multi-warehouse: two sources = two lines |
| `04-checkout.spec.js` | `customer` | The four steps, address book, moving forward and back, payment methods, polling cadence, stability |
| `05-stripe-payment.spec.js` | `customer` | **Paying for real**: accepted card → order, declined card, double click, terms and conditions |
| `06-checkout-b2b.spec.js` | `b2b` | Recognising the B2B customer, reaching the tunnel, ordering, partitioning |
| `07-new-customer.spec.js` | `guest` | **A first-time buyer's journey**: signing up, activating through the link, typing an address, paying |
| `08-multi-site.spec.js` | `multi-site` | **Two shops, two domains**: a catalogue of its own per site, price shown = price charged, partitioning of the professional site |
| `09-business-account-request.spec.js` | `multi-site` | **Business account application**: public form, expected refusals, and what an approval creates (customer, account, the site's rate) |
| `14-loyalty-points.spec.js` | `customer` | **Loyalty**: applied points cut the bill, the order spends them for good, removing them hands the bill back unspent |
| `15-gift-card.spec.js` | `customer` | **Gift card**: it pays part of the basket, locks the loyalty block, and comes off unspent |
| `16-account-lifecycle.spec.js` | `guest` | **An account's whole life**: created through the shop, deleted, and its address free again |

Shared helpers live in `fixtures/shop.js`, `fixtures/payment.js`,
`fixtures/stripe.js`, `fixtures/account.js`, `fixtures/activation.js`,
`fixtures/loyalty.js` and `fixtures/sites.js`.

## Known limit: the whole suite is less stable than its parts

Run file by file, every spec passes. On a complete run (~10 min), two or three
fall over — and not always the same ones. Two causes, neither related to what
they test:

- **The cart is shared.** One account, one quotation: a spec that orders or
  empties the cart changes the ground under the next one. `beforeEach` puts back
  what it can, not everything.
- **The server gives way under the duration.** osiris runs at ~130 MB of free
  RAM; a ten-minute suite is enough to make it answer in HTML, in 404, or not at
  all (see below).

In practice: `npm test -- --retries=1`, and in front of a failure, **replay the
file on its own** before concluding there is a regression.

## What to know before touching this

**A saturated server lies about the nature of its failure.** When osiris is
loaded, `/api/method/login` answers **404** (not 429), `get_cart_quotation`
answers **HTML** with a 200 status, and a payment stalls on its spinner with no
error logged anywhere. The same call in curl answers correctly a second later.
Before reading code: `ssh osiris uptime` and `free -h`. The helpers tolerate a
non-JSON body rather than dying on "Unexpected token '<'", and `global-setup`
retries five times.

**A skipped test reads exactly like a passing one.** That is this suite's main
trap. A conditional `test.skip()` firing for the wrong reason leaves the summary
green: one run reported "18 passed" while **23 tests were being skipped in
silence**. After every change, read the skipped count, not only the failures.

**The theme renders the cart twice.** The page's table and a side drawer
(`#builder-cart-drawer`) carry the same `data-item-code`. Always target
`.cart-table …`, or you grab the drawer, off-screen, and the test fails on
"element is not visible" while blaming the page.

**Go through HTTP, not through the DOM.** `page.request` rather than
`page.evaluate` + `frappe.call`: adding to the cart navigates on some themes, and
a call started just before dies with "Execution context was destroyed".

**A customer account cannot list doctypes.** `frappe.client.get_list` answers
`403` to a Website User — which is the correct behaviour, and
`01-authentication` checks it. The helpers therefore read the catalogue through
the pages, like a customer.

**Sign-in happens once** (`global-setup.js`) and is shared through
`storageState`. Signing in again in every spec tripped Frappe's attempt limit and
failed unrelated tests. The `guest` project deliberately runs signed out.

**The shipping radios are hidden** (`class="hide"`): the clickable thing is the
styled label. Use `chooseShipping()`.

**The quotation's state persists between tests.** The checkout's `beforeEach`
puts the default address back, without which a test that picks another one leaves
it for the next.

## Card payment (Stripe)

The scenarios in `05-stripe-payment.spec.js` go **all the way to the charge**:
they use Stripe's public test numbers
([documentation](https://docs.stripe.com/testing)) against a `pk_test_` key.

| Card | Effect |
|---|---|
| `4242 4242 4242 4242` | accepted, without 3-D Secure |
| `4000 0000 0000 0002` | declined by the issuer |
| `4000 0000 0000 9995` | insufficient funds |

These are **not** real cards: no money moves, no bank is reached. Never put a
real number in these files.

The site must be in **test mode** (`Stripe Settings` → public key `pk_test_…`,
secret key `sk_test_…`). A site on production keys would make real charges: check
before running.

> [!danger] These tests leave real documents behind
> A successful payment creates a **Payment Request**, a **Sales Order** and a
> **Payment Entry**, exactly like a customer's order. That is the price of a test
> that goes all the way — and the only way to prove the chain works. Count them
> before running the suite on a shared site.

### Known defect: the method selection is lost while the card is typed

`_updateOrderSummary()` calls `refreshPaymentMethods()` while on the payment
step, which **re-renders the whole method list**. If that lands while the
customer is filling in their card, the tile loses its `selected` class; the terms
handler, bound to `.payment-method-item.selected #terms-acceptance`, then stops
applying and the "Pay" button is never re-enabled — in front of a form that is
nonetheless complete.

`submitPayment()` re-selects the tile up to three times to work around it, but
**this is a real defect of the application**, not of the test: a customer would
live through the same thing. Fixing it means deciding what becomes of the
button's amount label once the re-rendering stops — not done here.

## Business account application

A `b2b_only` site refuses any account that is not approved: with no form, a
prospect has no door at all. The `B2B Account Request` DocType, the public
endpoint and the `/compte-professionnel` page live in **neoffice_theme**, next to
`Website Profile` and the gating.

The approval tests need server access (`WEBSHOP_E2E_SSH_HOST` /
`WEBSHOP_E2E_SITE`), like the activation ones. Without it, they skip themselves
and say so.

> [!warning] The `www/` convention: hyphens and underscores
> `compte-professionnel.html` goes with `compte_professionnel.py`. A hyphen in
> the `.py` name and Frappe **does not load the controller** — with no error and
> no log: the page renders, but its context is empty. It can be read off the
> neighbouring pages (`mes-reservations.html` ↔ `mes_reservations.py`).

## Multi-site: two shops on one ERP

A single Frappe site serves several shops, one per domain, described by the
`Website Profile` DocType (app `neoffice_theme`): home page, price list,
catalogue subset and access rules of its own for each.

```ini
WEBSHOP_E2E_B2B_URL=https://osiris-b2b.neoffice.me
```

Without this variable, the multi-site tests skip themselves and say so.

Playwright pins **one `baseURL` per project**: the tests that compare two domains
therefore open explicit contexts (`fixtures/sites.js`) instead of relying on
`baseURL`.

> [!note] A `b2b_only` site has no anonymous cart
> `update_cart` answers **403**, `/cart` redirects to `/login`, and the add
> button becomes an invitation to sign in. Any test that needs a cart on that
> domain must sign in first — `signInOnSite()` picks the account that is allowed
> (the consumer account is refused at the door).

> [!warning] An article with no rate on the site shows no button at all
> No price, no button, not even the sign-in call: the product page hides its
> whole action block. On osiris, 6 articles out of 310 carry a reseller rate. A
> test that compares buttons must therefore pick an article **priced on both
> domains**, otherwise it compares two empty pages.

> [!warning] Two notions of "B2B" not to be confused
> - `Webshop Settings.b2b_customer_group` → which **tunnel** (`/checkout_b2b`)
> - `Website Profile.allowed_customer_groups` → who may **enter the site**
>
> On osiris they diverge: a customer can be recognised as B2B by the webshop and
> refused at sign-in on the B2B domain. It is configuration, but the confusion
> costs time.

neoffice_theme's Python suite is complementary — infrastructure (home page,
robots, sitemap, cache isolation) where this one covers the shop:

```bash
ssh osiris 'cd /home/neoffice/frappe-bench && \
  bench --site prod.local execute neoffice_theme.tests.multisite.e2e.run_all'
```

It reads the test account's password from `site_config.json`
(`e2e_test_user_password`): **if you change the Playwright account's password,
change it there too**, or its B2B gating test fails.

## New customer: creation and activation

`07-new-customer.spec.js` follows a first-time buyer end to end. It needs to
activate an account, which requires server access:

```ini
WEBSHOP_E2E_SSH_HOST=osiris
WEBSHOP_E2E_SITE=prod.local
```

Without these variables, the activation scenarios skip themselves and say so.

> [!warning] Why not simply read the Yopmail inbox?
> Because **nothing goes out**. This site's default outgoing account is
> `_Test Comm Account 1` (`test_comm@example.com`) and its queue is in error: no
> welcome mail is ever sent. A real throwaway inbox would stay empty for ever.

> [!danger] The activation key cannot be read from the database
> Frappe stores the **SHA-256 hash** of `reset_password_key`; the clear-text
> value exists only in the e-mail. Reading the column and putting it in the URL
> hands the server `sha256(hash)` and always produces "this link has already been
> used or is invalid". The helper therefore mints a key, stores its hash and
> hands back the clear text — exactly what Frappe does when it composes the mail.

> [!danger] Never delete test accounts with `force=True`
> Other apps attach every new user to their own records (Drive adds one to a
> team, Activity Log keeps a trace). A forced deletion leaves those rows pointing
> at nothing, and Frappe then raises a `LinkValidationError` **from an unrelated
> app** on the next account's activation — 39 orphan rows had piled up before the
> cause was found. `deleteAccount()` (fixtures/activation.js) deletes without
> force: the quotation, the contact, the addresses and the customer when nothing
> links them, then the User; an account that carries orders keeps its history and
> is renamed out of the way so the address comes free. It refuses any address
> that is not one of the suite's throwaways (`e2e.…@yopmail.com`).

## B2B tunnel

`/checkout_b2b` (with an underscore) is a **single** page: company, address,
shipping, "Place order". **No payment step** — a B2B customer orders and is
billed on their account terms. The expected proof is therefore not "did they
pay" but "was an order created, and only for whoever is entitled to it".

A customer is B2B when their `customer_group` appears in
**Webshop Settings → B2B Customer Group**, and `activate_b2b_checkout` is on.

The `b2b` project has its own session (`WEBSHOP_E2E_B2B_USER`). Without that
variable, the B2B specs skip themselves — and therefore show up in the skipped
count.

## Multi-source article

The multi-warehouse tests need a published article offering at least two sources.
The automatic detection only walks the first page of the catalogue; if the
article sits further down, set `WEBSHOP_E2E_MULTISOURCE_ROUTE`. Without it and
without detection, those tests skip themselves — and therefore show up in the
skipped count.

## The money paths: loyalty and gift card

Two specs added on 2026-09-22, because a client shop redeems points 177 times per
90 days and holds 128 gift cards, and nothing here covered them. What they prove,
and the others did not say:

- `14-loyalty-points.spec.js` — applied points cut the bill, the order **spends
  them for good**, and they do not come back to the balance afterwards; removing
  the points before ordering hands the original bill back **without** spending
  them.
- `15-gift-card.spec.js` — a customer's own card pays part of the basket,
  **locks the loyalty block** while it is on (the two are exclusive), and
  removing it hands the bill back without consuming the card, so the spec can run
  every day on the same one.

> **The loyalty and coupon blocks live inside step 4 of the tunnel**
> (`#step-payment`), hidden before it. Reading them from a freshly loaded
> `/checkout` finds nothing, and a spec written that way **skips itself in
> silence** instead of failing — which is what happened on the first draft. The
> loyalty balance is therefore read through the shop's own endpoint
> (`loyaltyBalanceShown`, in `fixtures/payment.js`), which answers at any step;
> only the applying goes through the screen.

> **Wait on the quotation, never on the button.** Applying points or a coupon
> re-renders the whole of step 4, so the button that says "applied" is destroyed
> and rebuilt under the test — and it comes back BEFORE the document is saved.
> `waitForQuotation` / `pressUntil` (`fixtures/payment.js`) poll the shop's own
> document and press again when a click was eaten by the re-render.

> **Buying earns points at the same moment redeeming spends them.** An order that
> redeems 10 and earns 112 leaves the balance 102 higher than before: a test
> asserting "the balance went down by what I spent" fails on a shop that works
> perfectly. What proves the redemption is the ledger (`fixtures/loyalty.js`):
> entries of exactly minus what was applied, tied to that order's invoice, still
> there afterwards. And the checkout **rounds the offered balance down to the
> nearest ten** (`get_loyalty_points_html`), so the block's figure and the
> ledger's are two different numbers — never subtract one from the other.

> **The order is placed without a gateway when the shop offers one**
> (`orderWithoutGateway`): "on account" or "transfer before shipping" place a
> real order without calling a provider. A shop whose tiles are all gateways —
> osiris — falls back to Stripe's test card (`settleTheOrder`), because skipping
> here would leave the only test that proves consumption reading as a pass.

> **What the target instance needs**: a loyalty programme with at least ten
> points on the test account, and an unused gift card in its name. On osiris both
> exist. The gift-card spec consumes nothing; the loyalty one spends ten points
> per run.

## The payments suite lives in the `payments` repository

`payments/payments/tests/e2e/playwright/` carries twenty Playwright tests **in
Python**: TWINT, Stripe, Payrexx, Wallee, the invoice, switching provider
mid-tunnel, the declined payment, re-checkout, account creation, the cart,
loyalty and B2B. They target osiris by default. **No workflow runs them**
(checked on 2026-09-22), and their virtual environment was dead: its interpreter
had disappeared from the machine. Rebuilt the same day with Python 3.13. Before
any update at a client's, those are the ones that answer "does TWINT hand back
its QR, does Stripe answer".

## The gate before a client update (`preflight.mjs`)

One command, two halves, because they cannot be the same check:

```bash
#### On an instance we own — everything, including the money paths
PAYMENTS_E2E_DIR=~/GitHub/payments/payments/tests/e2e/playwright \
PAYMENTS_E2E_PYTHON=~/GitHub/payments/.venv-e2e/bin/python \
  node preflight.mjs --rehearsal https://osiris.neoffice.me

#### On the client's live shop — read-only, before AND after the update
node preflight.mjs --client https://<client> --snapshot before.json
#### … deploy …
node preflight.mjs --client https://<client> --baseline before.json
```

The rehearsal half runs the whole browser suite and the payments repository's
Python suite (TWINT, Stripe, Payrexx, Wallee, the invoice): it places real
orders, so it never points at a client.

The client half only makes the GETs a visitor makes: the pages answer, the
chrome is there (header, its search, footer, how many links), the catalogue
lists products, a product page prices and offers its buy button, and every text
reads on its ground.

> **A regression is something that WAS there and is not any more.** The first
> version asserted absolutes and cried wolf on the first site it met — "no search
> field in the header", on a shop whose header never had one. Facts are recorded
> with `--snapshot` before the update and compared with `--baseline` after; a
> boolean that goes from true to false fails, and a count that loses more than a
> fifth fails.

> **An audit that reads nothing proves nothing.** The contrast audit reads
> `<main>`, and a Builder home page keeps its content outside it: `/` answered
> "0 elements read" and would have counted as clean. The home page is probed for
> its chrome and audited by nobody; the shop's own pages, product page included,
> are what the audit reads — and a page that reads nothing fails.

## What these tests leave behind

**Accounts** — `01-authentication` creates a real account on every run, prefixed
`e2e.auto.<timestamp>@example.test`. `07-new-customer` and
`16-account-lifecycle` create `e2e.<label>.<timestamp>@yopmail.com` and delete
them at the end of the file.

**Orders** — every successful Stripe payment and every B2B order leaves a
submitted quotation, a sales order and, for Stripe, a payment entry. To find
them:

```bash
ssh osiris 'cd /home/neoffice/frappe-bench/sites && ../env/bin/python -c "
import frappe
frappe.init(site=\"prod.local\"); frappe.connect()
for so in frappe.get_all(\"Sales Order\",
        filters={\"customer\": [\"like\", \"%Test%E2E%\"]},
        fields=[\"name\",\"customer\",\"status\",\"grand_total\"]):
    print(so)
"'
```

Do not delete them blindly: a paid order carries an accounting entry. Cancel them
from the desk if needed.

**Deleting the test accounts:**

```bash
ssh osiris 'cd /home/neoffice/frappe-bench/sites && ../env/bin/python -c "
import frappe
frappe.init(site=\"prod.local\"); frappe.connect()
for name in frappe.get_all(\"User\", filters={\"email\": [\"like\", \"e2e.auto.%\"]}, pluck=\"name\"):
    frappe.delete_doc(\"User\", name, ignore_permissions=True)
frappe.db.commit()
"'
```

## Visual harness (`visual/`)

Captures of the shop's content (the `<main>` element: the header, the title block
and the footer are the site chrome, which changes without us), desktop and
mobile, of the pages listed in `visual/pages.json`, then a pixel-by-pixel
comparison between two sets. It is the guardrail of any work that touches the
templates or the stylesheets.

What the capture does to be reproducible, measured on 2026-09-11 on osiris: it
does **not scroll** the page (scrolling asks the catalogue for its next batches,
and how many arrive at the moment of the shot depends on the server's load — 96,
120 or 168 products from one shot to the next); it wakes lazy images by setting
`loading=eager` and waits for them to load; it freezes transitions and animations
(a sticky header caught mid-slide counted as a difference). Two captures of the
same build: 0.00 % on every page.

```bash
export WEBSHOP_E2E_URL=https://<instance>
export WEBSHOP_SID=<sid>          # bench --site <site> browse --user <customer>, for signed-in pages
npm run visual:capture -- baseline
# … the changes …
npm run visual:capture -- after
npm run visual:compare -- baseline after --threshold 0.5
```

Captures go to `visual/shots/<label>/` (not versioned); diffs to
`visual/shots/<after>/diff/`, moved pixels in red. `WEBSHOP_ONLY=cart,checkout`
restricts the capture to a few pages.

The pages in `pages.json` name articles published on the development instance;
`product_mosaic` is a page with four photos (the mosaic gallery), `product_photos`
a bookable service (another page, the theme's), `product_secondhand` a used unit,
`product_variants` a template with variants.

`compare.py`'s table also reads each set's `summary.json`: the `items` column
gives the number of products shown, and a page where only that number changes
(common pixels identical) is marked `items`, not `MOVED`; a capture taken on a
page in error (status ≠ 200) is marked `INVALID` — it proves nothing, take it
again (`WEBSHOP_ONLY=<page>` with the same label overwrites only the capture
concerned, but replaces the whole `summary.json`: keep a copy and merge it, or
take everything again).

### Contrast audit (`visual/contrast.mjs`)

The shop draws with the chrome's tokens: its colours only exist once a real site
renders them, and a shop that is perfect on a light chrome shipped its title dark
on dark to a reseller (2026-09-11). The audit walks every text, field, `<select>`,
button and icon of `<main>` and of the chrome's title band, composes the real
background through the ancestors (alpha included, Chrome's `color(srgb …)`
included) and computes the WCAG ratio; everything below the threshold is listed
with its path, and the exit code is 1 — enough to gate a deploy.

```bash
WEBSHOP_E2E_URL=https://<site> node visual/contrast.mjs /all-products /<a-product> /shop-by-category /wishlist
WEBSHOP_E2E_URL=https://<site> node visual/contrast.mjs            # the public pages of pages.json (+ the `auth` ones with WEBSHOP_SID)
WEBSHOP_CONTRAST_MIN=4.5 …                                          # threshold (3 by default); --json for the raw output
```

Run it **on the target site** before any deploy at a client's; anonymous is
enough. The `11-contrast` spec (project `guest`) does the same thing on the
suite's own instance.

**Signed in, cart filled, step by step.** On 2026-09-14 the audit said 0 on a
dark site whose merchant then found the cart and the checkout unreadable: it had
only ever read them as a visitor with an empty cart. For a client's site: a
session (`bench browse`), an item in the cart, then

```bash
WEBSHOP_SID=<sid> WEBSHOP_CONTRAST_REVEAL=.step-section WEBSHOP_E2E_URL=https://<site> \
  node visual/contrast.mjs /cart /checkout /quick-order /me /orders /addresses
```

`WEBSHOP_CSS_OVERRIDE=<file.css>` serves a locally compiled stylesheet in place
of the shop's bundle: a colour fix can be audited against the client's real
chrome before it is deployed (compile the bundle with `sass`, paths
`webshop/public/scss` and `~/GitHub/frappe`).

**A state that only exists after a click.** The same day, the active-filter chip
read 1.09:1 on that dark site, and the catalogue's audit said 0: no filter had
ever been ticked there. `WEBSHOP_CONTRAST_CLICK` clicks, in order, the first
match of each selector separated by `||` (a visible one if there is any), lets
the page settle, then reads. A click that finds nothing fails the page: a state
never shown would otherwise pass for a state that succeeded. The discount filter
only exists if this visitor has one (on a site where only customers get
discounts, the session is needed), and it disappears when the chosen group holds
none: click it first.

```bash
WEBSHOP_SID=<sid> WEBSHOP_CONTRAST_CLICK='#product-filters .discount-filter||#product-filters .field-filter' \
  WEBSHOP_E2E_URL=https://<site> node visual/contrast.mjs /all-products
```

The `13-site-buttons` spec (project `customer`) measures the shop's buttons
against the site's own button: an `<a class="u-btn u-btn--primary">` injected into
a shop page (the chrome's `:where(.u-btn)` rule applies there too) is the
reference, and the buy button, the cart's and the tunnel's must be identical to it
in shape (padding, radius, font) and in colour; the outline buttons are compared
with `.u-btn--outline`. It skips itself on a site with no Builder chrome.
