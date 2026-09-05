# Copyright (c) 2026, bVisible and contributors
# License: GNU General Public License v3. See license.txt

"""Tests for multi-site scoping.

//// Neoffice — added file (no upstream equivalent).

This module decides two things a shop cannot get wrong: **which price is
charged** and **who may buy**. It had no Python test at all — only the Playwright
suite, which cannot run on a fleet that has no browser and no second domain.

Two properties are checked throughout:

1. **Degrade to nothing.** On an installation with no Website Profile resolved —
   every single-site shop — each helper must behave as if the module were not
   there. A regression here breaks shops that never asked for multi-site.
2. **The profile wins.** Where a profile IS resolved, its price list beats both
   the caller's fallback and Webshop Settings. Reading the setting directly is
   how the B2B domain came to advertise 199.00 and invoice 549.00.

A request carries its site in `frappe.local.website_profile` (the name, used by
the SQL paths) and `frappe.local.website_profile_doc` (the document, used for
price list, b2b_only and domain). Both are set here exactly as neoffice_theme's
request hook sets them.
"""

import unittest
from contextlib import contextmanager

import frappe

from webshop.webshop import multi_site
from webshop.webshop.tests.utils import leaf_item_group, root_customer_group

PREFIX = "_WSTEST Site"
PROFIL_A = f"{PREFIX} A"
PROFIL_B = f"{PREFIX} B"

LIBRE = f"{PREFIX} Item Free"
RESTREINT_A = f"{PREFIX} Item A Only"
LES_DEUX = f"{PREFIX} Item Both"


@contextmanager
def profil_resolu(nom=None, doc=None):
	"""Browse as if the request had resolved this Website Profile."""
	nom_avant = getattr(frappe.local, "website_profile", None)
	doc_avant = getattr(frappe.local, "website_profile_doc", None)
	frappe.local.website_profile = nom
	frappe.local.website_profile_doc = doc
	try:
		yield
	finally:
		frappe.local.website_profile = nom_avant
		frappe.local.website_profile_doc = doc_avant


def multi_site_disponible():
	"""Website Profile and the child table ship with neoffice_theme."""
	return bool(frappe.db.exists("DocType", "Website Profile")) and frappe.db.table_exists(
		multi_site.CHILD_TABLE
	)


class TestDegradationSansProfil(unittest.TestCase):
	"""No profile resolved — a single-site shop must not notice this module."""

	def setUp(self):
		self.ctx = profil_resolu(None, None)
		self.ctx.__enter__()
		self.addCleanup(self.ctx.__exit__, None, None, None)

	def test_filtering_is_inactive(self):
		self.assertFalse(multi_site.is_active())
		self.assertIsNone(multi_site.get_current_profile_name())

	def test_no_item_is_excluded(self):
		self.assertEqual(multi_site.excluded_item_names(), [])

	def test_sql_helpers_return_nothing_to_append(self):
		# Callers concatenate these straight into a query: anything other than an
		# empty string would break every single-site shop's catalogue query.
		self.assertEqual(multi_site.site_sql_predicate("wi"), "")
		self.assertEqual(multi_site.site_sql_condition("wi"), "")

	# //// Neoffice — call site updated for the RULE #00 rename to site_is_business_only
	# //// (e646274dd3 "chore: RULE #00 pass on identifiers — multi_site functions and the local variables")
	def test_site_is_not_reserved(self):
		self.assertFalse(multi_site.site_is_business_only())

	def test_a_guest_may_still_shop(self):
		"""The b2b gate must never fire where no professional site is configured."""
		utilisateur = frappe.session.user
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, utilisateur)

		# //// Neoffice — call site updated for the RULE #00 rename to require_login_to_buy (e646274dd3)
		multi_site.require_login_to_buy()  # must not raise

	def test_price_list_falls_back_to_the_settings(self):
		attendu = frappe.db.get_single_value("Webshop Settings", "price_list")

		self.assertEqual(multi_site.effective_price_list(), attendu)

	def test_caller_fallback_is_honoured(self):
		self.assertEqual(multi_site.effective_price_list("Une Liste"), "Une Liste")


@unittest.skipUnless(multi_site_disponible(), "Website Profile requires neoffice_theme")
class TestAvecProfil(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		cls.item_group = leaf_item_group()
		cls.liste_a = cls._creer_liste(f"{PREFIX} List A")
		cls.liste_b = cls._creer_liste(f"{PREFIX} List B")

		cls._creer_profil(PROFIL_A, "wstest-a.example.com", b2b_only=0, price_list=cls.liste_a)
		cls._creer_profil(PROFIL_B, "wstest-b.example.com", b2b_only=1, price_list=cls.liste_b)

		# No rows at all = visible everywhere; that is the convention the whole
		# catalogue relies on, so an existing shop needs no migration.
		cls._creer_article(LIBRE, sites=[])
		cls._creer_article(RESTREINT_A, sites=[PROFIL_A])
		cls._creer_article(LES_DEUX, sites=[PROFIL_A, PROFIL_B])
		frappe.db.commit()

	@classmethod
	def _creer_liste(cls, nom):
		if not frappe.db.exists("Price List", nom):
			frappe.get_doc(
				{
					"doctype": "Price List",
					"price_list_name": nom,
					"enabled": 1,
					"selling": 1,
					"currency": frappe.db.get_value("Company", {}, "default_currency") or "CHF",
				}
			).insert(ignore_permissions=True)
		return nom

	@classmethod
	def _creer_profil(cls, nom, domaine, b2b_only, price_list):
		if frappe.db.exists("Website Profile", nom):
			return
		doc = frappe.new_doc("Website Profile")
		doc.update(
			{
				"title": nom,
				"primary_domain": domaine,
				"site_kind": "B2B" if b2b_only else "B2C",
				"b2b_only": b2b_only,
				"price_list": price_list,
				"enabled": 1,
				"is_default": 0,
			}
		)
		if b2b_only:
			# neoffice_theme refuses a login-restricted site with nobody allowed in.
			doc.append(
				"allowed_customer_groups",
				{"customer_group": root_customer_group()},
			)
		doc.insert(ignore_permissions=True)

	@classmethod
	def _creer_article(cls, code, sites):
		if not frappe.db.exists("Item", code):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": code,
					"item_name": code,
					"item_group": cls.item_group,
					"stock_uom": frappe.db.get_value("UOM", {}, "name"),
					"is_stock_item": 0,
				}
			).insert(ignore_permissions=True)

		nom = frappe.db.get_value("Website Item", {"item_code": code}, "name")
		if not nom:
			doc = frappe.get_doc(
				{
					"doctype": "Website Item",
					"item_code": code,
					"web_item_name": code,
					"item_group": cls.item_group,
					"published": 1,
					"route": f"products/{code.lower().replace(' ', '-')}",
				}
			)
			doc.insert(ignore_permissions=True)
			nom = doc.name

		multi_site.set_website_item_sites(nom, sites)
		return nom

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for code in (LIBRE, RESTREINT_A, LES_DEUX):
			nom = frappe.db.get_value("Website Item", {"item_code": code}, "name")
			if nom:
				frappe.delete_doc("Website Item", nom, force=True, ignore_permissions=True)
			if frappe.db.exists("Item", code):
				frappe.delete_doc("Item", code, force=True, ignore_permissions=True)
		for nom in (PROFIL_A, PROFIL_B):
			if frappe.db.exists("Website Profile", nom):
				frappe.delete_doc("Website Profile", nom, force=True, ignore_permissions=True)
		for nom in (f"{PREFIX} List A", f"{PREFIX} List B"):
			if frappe.db.exists("Price List", nom):
				frappe.delete_doc("Price List", nom, force=True, ignore_permissions=True)
		frappe.db.commit()

	def _sur(self, profil):
		doc = frappe.get_doc("Website Profile", profil).as_dict()
		return profil_resolu(profil, doc)

	def _noms(self, codes):
		return {frappe.db.get_value("Website Item", {"item_code": c}, "name") for c in codes}

	# --- what the shopper is charged -------------------------------------

	def test_the_profile_price_list_wins_over_the_settings(self):
		with self._sur(PROFIL_A):
			self.assertEqual(multi_site.effective_price_list(), self.liste_a)

	def test_the_profile_price_list_wins_over_a_caller_fallback(self):
		"""A caller passing Webshop Settings' list must not override the site.

		This is exactly the shape of the bug that had the B2B domain listing
		199.00 and invoicing 549.00: each caller passed its own default and the
		site's list was never consulted.
		"""
		with self._sur(PROFIL_B):
			self.assertEqual(multi_site.effective_price_list("Vente standard"), self.liste_b)

	def test_two_sites_quote_two_different_lists(self):
		with self._sur(PROFIL_A):
			a = multi_site.effective_price_list()
		with self._sur(PROFIL_B):
			b = multi_site.effective_price_list()

		self.assertNotEqual(a, b)

	def test_a_profile_without_a_price_list_falls_back(self):
		doc = frappe.get_doc("Website Profile", PROFIL_A).as_dict()
		doc["price_list"] = None
		with profil_resolu(PROFIL_A, doc):
			self.assertEqual(multi_site.effective_price_list("Repli"), "Repli")

	# --- who may buy ------------------------------------------------------

	# //// Neoffice — RULE #00 rename to site_is_business_only, this call site updated
	# //// (e646274dd3 "chore: RULE #00 pass on identifiers — multi_site functions and the local variables")
	def test_a_professional_site_is_reserved(self):
		with self._sur(PROFIL_B):
			self.assertTrue(multi_site.site_is_business_only())

	def test_a_consumer_site_is_not(self):
		with self._sur(PROFIL_A):
			# //// Neoffice — call site updated for the RULE #00 rename (e646274dd3)
			self.assertFalse(multi_site.site_is_business_only())

	def test_a_guest_cannot_buy_on_a_professional_site(self):
		utilisateur = frappe.session.user
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, utilisateur)

		with self._sur(PROFIL_B):
			with self.assertRaises(frappe.PermissionError):
				# //// Neoffice — call site updated for the RULE #00 rename to require_login_to_buy (e646274dd3)
				multi_site.require_login_to_buy()

	def test_a_signed_in_user_may_buy_on_a_professional_site(self):
		with self._sur(PROFIL_B):
			# //// Neoffice — call site updated for the RULE #00 rename (e646274dd3)
			multi_site.require_login_to_buy()  # must not raise

	def test_a_guest_may_buy_on_a_consumer_site(self):
		utilisateur = frappe.session.user
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, utilisateur)

		with self._sur(PROFIL_A):
			# //// Neoffice — call site updated for the RULE #00 rename (e646274dd3)
			multi_site.require_login_to_buy()  # must not raise

	# --- which catalogue is served ---------------------------------------

	def test_an_unrestricted_item_is_never_excluded(self):
		for profil in (PROFIL_A, PROFIL_B):
			with self.subTest(profil=profil), self._sur(profil):
				exclus = set(multi_site.excluded_item_names())
				self.assertNotIn(self._noms([LIBRE]).pop(), exclus)

	def test_an_item_restricted_elsewhere_is_excluded(self):
		with self._sur(PROFIL_B):
			exclus = set(multi_site.excluded_item_names())

		self.assertIn(self._noms([RESTREINT_A]).pop(), exclus)

	def test_an_item_restricted_here_is_not_excluded(self):
		with self._sur(PROFIL_A):
			exclus = set(multi_site.excluded_item_names())

		self.assertNotIn(self._noms([RESTREINT_A]).pop(), exclus)

	def test_an_item_listed_on_both_sites_is_excluded_from_neither(self):
		for profil in (PROFIL_A, PROFIL_B):
			with self.subTest(profil=profil), self._sur(profil):
				exclus = set(multi_site.excluded_item_names())
				self.assertNotIn(self._noms([LES_DEUX]).pop(), exclus)

	# --- the SQL paths, run for real --------------------------------------

	def _articles_visibles(self):
		"""Run the predicate the way the catalogue queries do."""
		condition = multi_site.site_sql_condition("wi")
		return set(
			frappe.db.sql_list(
				f"""
				SELECT wi.name FROM `tabWebsite Item` wi
				WHERE wi.item_code LIKE %s {condition}
				""",
				(f"{PREFIX}%",),
			)
		)

	def test_the_sql_predicate_hides_an_item_restricted_elsewhere(self):
		with self._sur(PROFIL_B):
			visibles = self._articles_visibles()

		self.assertEqual(visibles, self._noms([LIBRE, LES_DEUX]))

	def test_the_sql_predicate_shows_an_item_restricted_here(self):
		with self._sur(PROFIL_A):
			visibles = self._articles_visibles()

		self.assertEqual(visibles, self._noms([LIBRE, RESTREINT_A, LES_DEUX]))

	def test_the_sql_paths_agree_with_the_orm_one(self):
		"""Both are used across the codebase; they must never disagree."""
		with self._sur(PROFIL_B):
			via_sql = self._articles_visibles()
			exclus = set(multi_site.excluded_item_names())

		tous = self._noms([LIBRE, RESTREINT_A, LES_DEUX])
		self.assertEqual(via_sql, tous - exclus)

	def test_the_condition_is_the_predicate_prefixed_with_and(self):
		with self._sur(PROFIL_A):
			self.assertEqual(
				multi_site.site_sql_condition("wi"), f" AND {multi_site.site_sql_predicate('wi')}"
			)

	def test_the_predicate_follows_the_alias_it_is_given(self):
		with self._sur(PROFIL_A):
			predicat = multi_site.site_sql_predicate("autre_alias")

		self.assertIn("autre_alias.name", predicat)
		self.assertNotIn("wi.name", predicat)

	def test_the_profile_name_is_escaped(self):
		"""The name reaches the query as a literal, so it must be quoted."""
		with self._sur(PROFIL_A):
			predicat = multi_site.site_sql_predicate("wi")

		self.assertIn(frappe.db.escape(PROFIL_A), predicat)

	# --- URLs --------------------------------------------------------------

	def test_a_url_is_built_on_the_site_domain(self):
		with self._sur(PROFIL_B):
			self.assertEqual(
				multi_site.site_url("/cart"), "https://wstest-b.example.com/cart"
			)

	def test_an_absolute_url_is_left_alone(self):
		with self._sur(PROFIL_A):
			self.assertEqual(
				multi_site.site_url("https://ailleurs.example.com/x"),
				"https://ailleurs.example.com/x",
			)

	def test_an_empty_path_gives_the_bare_domain(self):
		with self._sur(PROFIL_A):
			self.assertEqual(multi_site.site_url(), "https://wstest-a.example.com")

	def test_without_a_profile_the_url_is_the_frappe_one(self):
		from frappe.utils import get_url

		with profil_resolu(None, None):
			self.assertEqual(multi_site.site_url("/cart"), get_url("/cart"))

	# --- the publish dialog ------------------------------------------------

	def test_enabled_profiles_are_offered_for_publishing(self):
		noms = [p["name"] for p in multi_site.get_active_website_profiles()]

		self.assertIn(PROFIL_A, noms)
		self.assertIn(PROFIL_B, noms)

	def test_a_disabled_profile_is_not_offered(self):
		frappe.db.set_value("Website Profile", PROFIL_A, "enabled", 0)
		self.addCleanup(frappe.db.set_value, "Website Profile", PROFIL_A, "enabled", 1)

		noms = [p["name"] for p in multi_site.get_active_website_profiles()]

		self.assertNotIn(PROFIL_A, noms)

	def test_clearing_the_sites_makes_an_item_visible_everywhere(self):
		nom = self._noms([RESTREINT_A]).pop()
		multi_site.set_website_item_sites(nom, [])
		self.addCleanup(multi_site.set_website_item_sites, nom, [PROFIL_A])

		with self._sur(PROFIL_B):
			self.assertNotIn(nom, set(multi_site.excluded_item_names()))

	def test_sites_can_be_passed_as_json(self):
		"""The publish dialog posts them as a JSON string."""
		import json

		nom = self._noms([LIBRE]).pop()
		multi_site.set_website_item_sites(nom, json.dumps([PROFIL_A]))
		self.addCleanup(multi_site.set_website_item_sites, nom, [])

		with self._sur(PROFIL_B):
			self.assertIn(nom, set(multi_site.excluded_item_names()))
