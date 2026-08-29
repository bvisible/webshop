# Copyright (c) 2026, bVisible and contributors
# License: GNU General Public License v3. See license.txt

"""Fixtures resolved from the site instead of assumed.

The upstream tests name their fixtures in English — "Products", "Standard
Selling", "All Customer Groups" — and ERPNext's own `make_item` defaults to the
"Products" item group. None of those exist on a site installed in French, so
every one of those tests errored on a LinkValidationError before reaching its
first assertion. Whether a test passes should not depend on the language the
shop was installed in.

Ask the site what it actually has, and create a fixture only when it has none.
"""

import frappe

PREFIX = "_WSTEST"


def default_company():
	return frappe.db.get_single_value("Global Defaults", "default_company")


def leaf_item_group():
	"""An item group that can hold items.

	Some sites forbid items in the root group, so never return the root.
	"""
	group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
	if group:
		return group

	nom = f"{PREFIX} Group"
	if not frappe.db.exists("Item Group", nom):
		frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": nom,
				"parent_item_group": root_item_group(),
			}
		).insert(ignore_permissions=True)
	return nom


def root_item_group():
	return frappe.db.get_value("Item Group", {"lft": 1}, "name")


def root_customer_group():
	"""The tree root, by nested-set position rather than by a null parent.

	`{"parent_customer_group": ("in", (None, ""))}` renders as `IN (NULL, '')`,
	and `x IN (NULL)` is NULL — never true — so such a filter silently returns
	nothing, and whatever is compared against the result is compared to null.
	"""
	return frappe.db.get_value("Customer Group", {"lft": 1}, "name") or frappe.db.get_single_value(
		"Webshop Settings", "default_customer_group"
	)


def selling_price_list():
	"""The list the shop sells at, whatever it is called here."""
	nom = frappe.db.get_single_value("Webshop Settings", "price_list")
	if nom and frappe.db.exists("Price List", nom):
		return nom
	return frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name")


def snapshot_webshop_settings(champs):
	"""Current value of each named Webshop Settings field.

	Webshop Settings is a Single: a test that writes to it and relies on
	`frappe.db.rollback()` leaves the change in place once anything in the run
	commits — the shop keeps whatever the last test set. Snapshot before, restore
	in a cleanup.
	"""
	return {champ: frappe.db.get_single_value("Webshop Settings", champ) for champ in champs}


def restore_webshop_settings(valeurs):
	for champ, valeur in valeurs.items():
		frappe.db.set_single_value("Webshop Settings", champ, valeur)
	frappe.db.commit()
	frappe.local.shopping_cart_settings = None
	frappe.clear_cache()


def make_test_item(item_code, **properties):
	"""ERPNext's make_item, with an item group this site will accept."""
	from erpnext.stock.doctype.item.test_item import make_item

	properties.setdefault("item_group", leaf_item_group())
	return make_item(item_code, properties=properties)
