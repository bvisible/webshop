# //// Neoffice — added file (no upstream equivalent).
"""The shop's pages have English hyphenated addresses (2026-10-25, maintenance#1862, lot 2).

`/thank_you`, `/checkout_b2b`, `/customer_reviews` and `/cgv` were underscores and a French word among
English hyphens. A payment comes back to the thank-you page with its order in the query string, and the
checkout, the gateways and the shop's links name these pages: everything now says the English address, the
old ones lead to it for good with their query string (neoffice_theme.renamed_routes), and the files keep their
names (a module has no hyphen, and the checkout's code and its tests import them).
"""

import re
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.website.page_renderers.not_found_page import NotFoundPage
from frappe.website.path_resolver import PathResolver

# the English address -> the file that serves it (webshop/templates/pages/<name>.html)
ADDRESSES = {
	"thank-you": "thank_you",
	"checkout-b2b": "checkout_b2b",
	"customer-reviews": "customer_reviews",
	"terms-and-conditions": "cgv",
}
ROOT = Path(__file__).resolve().parent.parent.parent  # the app's inner `webshop` folder


class TestThePageAddresses(FrappeTestCase):
	def test_every_english_address_is_a_route_rule_to_its_page(self):
		rules = {rule["from_route"]: rule["to_route"] for rule in frappe.get_hooks("website_route_rules")}
		for address, page in ADDRESSES.items():
			self.assertEqual(rules.get(f"/{address}"), page, address)
			self.assertTrue((ROOT / "templates" / "pages" / f"{page}.html").exists(), page)

	def test_every_english_address_is_a_page_that_exists(self):
		for address in ADDRESSES:
			self.assertNotIsInstance(PathResolver(address).resolve(), NotFoundPage, address)

	def test_the_shop_names_no_old_address_any_more(self):
		# the gateways, the checkout and the shop's templates send the visitor to the English addresses; an
		# old one still works (the redirect) but a payment would return through it
		pattern = re.compile(r"(?<![\w\-])/(thank_you|checkout_b2b|customer_reviews|cgv)(?![\w\-])")
		skipped = ("locale/", "tests/", "seo/robots.py", "patches/", "hooks.py", "public/frontend/", "dist/")
		found = []
		for path in ROOT.rglob("*"):
			if path.suffix not in (".py", ".html", ".js") or not path.is_file():
				continue
			rel = path.relative_to(ROOT).as_posix()
			if any(s in rel for s in skipped):
				continue
			for number, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
				# a fork marker names the upstream address on purpose: it says what was replaced
				if pattern.search(line) and "////" not in line:
					found.append(f"{rel}:{number}: {line.strip()[:90]}")
		self.assertEqual(found, [])

	def test_robots_keeps_both_addresses_of_the_thank_you_page_private(self):
		from webshop.webshop.seo.robots import PRIVATE_PATHS

		self.assertIn("/thank-you", PRIVATE_PATHS)
		self.assertIn("/thank_you", PRIVATE_PATHS)
