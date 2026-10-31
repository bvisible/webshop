# //// Neoffice — added file (no upstream equivalent).
"""The small shop the catalogue tests run on: two resellers, a tree of item groups, brands, priced products.

Made once per test module (`make`), committed — a class rolls back only when it ends, and a rollback in
the code under test would take uncommitted fixtures with it — and removed with `purge`, also at the start
of a run, for whatever an interrupted one left behind. Every name carries the tests' prefix.

                                 price on the shop's list   price on the reseller's list
    FIRST    (child group, brand A, a picture)      100                    80
    SECOND   (parent group, brand A, no picture)     50                    40
    THIRD    (other group, brand B)                  30                    30
    MODEL    two variants, 60 and 90                 -                    48 / 72
    HIDDEN   (child group, not published)            10
    SOLD     (child group, sold)                     10
"""

import io

import frappe
from PIL import Image

from webshop.webshop.doctype.website_item.website_item import make_website_item
from webshop.webshop.tests.utils import (
	PREFIX,
	ensure_shop_settings,
	make_test_item,
	portal_customer,
	root_customer_group,
	selling_price_list,
)

RESELLER_GROUP = f"{PREFIX} Cat Resellers"
CONSUMER_GROUP = f"{PREFIX} Cat Consumers"
USER, CUSTOMER = "wstest-cat-a@example.com", f"{PREFIX} Cat Shop A"
OTHER_USER, OTHER_CUSTOMER = "wstest-cat-b@example.com", f"{PREFIX} Cat Shop B"
OUT_USER, OUT_CUSTOMER = "wstest-cat-out@example.com", f"{PREFIX} Cat Outsider"

PARENT_GROUP = f"{PREFIX} Cat Parent"
CHILD_GROUP = f"{PREFIX} Cat Child"
OTHER_GROUP = f"{PREFIX} Cat Other"
BRAND_A, BRAND_B = f"{PREFIX} Cat Brand A", f"{PREFIX} Cat Brand B"
RESELLER_LIST = f"{PREFIX} Cat Reseller List"

FIRST, SECOND, THIRD = f"{PREFIX} Cat First", f"{PREFIX} Cat Second", f"{PREFIX} Cat Third"
MODEL, HIDDEN, SOLD = f"{PREFIX} Cat Model", f"{PREFIX} Cat Hidden", f"{PREFIX} Cat Sold"
ATTRIBUTE = f"{PREFIX} Cat Size"
PICTURE = "wstest-cat-picture.png"
ITEMS = (FIRST, SECOND, THIRD, HIDDEN, SOLD)


def _price(code, price_list, rate):
	if not frappe.db.exists("Item Price", {"item_code": code, "price_list": price_list}):
		frappe.get_doc(
			{"doctype": "Item Price", "item_code": code, "price_list": price_list, "price_list_rate": rate}
		).insert(ignore_permissions=True)


def _publish(item, **fields):
	"""The item's Website Item, made if it is not there yet, with `fields` set."""
	name = frappe.db.get_value("Website Item", {"item_code": item.name}, "name")
	if not name:
		make_website_item(item)
		name = frappe.db.get_value("Website Item", {"item_code": item.name}, "name")
	site = frappe.get_doc("Website Item", name)
	site.published = 1
	for field, value in fields.items():
		site.set(field, value)
	site.save(ignore_permissions=True)
	return site


def _group(name, parent, is_group):
	if not frappe.db.exists("Item Group", name):
		frappe.get_doc(
			{"doctype": "Item Group", "item_group_name": name, "parent_item_group": parent, "is_group": is_group, "show_in_website": 1}
		).insert(ignore_permissions=True)


def make():
	"""Build the shop; returns {"picture_url", "shop_list", ...} for the tests that want them."""
	ensure_shop_settings()
	purge()
	for name in (RESELLER_GROUP, CONSUMER_GROUP):
		if not frappe.db.exists("Customer Group", name):
			frappe.get_doc(
				{"doctype": "Customer Group", "customer_group_name": name, "parent_customer_group": root_customer_group(), "is_group": 0}
			).insert(ignore_permissions=True)
	shop_list = selling_price_list()
	currency = frappe.db.get_value("Price List", shop_list, "currency")
	frappe.get_doc(
		{"doctype": "Price List", "price_list_name": RESELLER_LIST, "currency": currency, "selling": 1, "enabled": 1}
	).insert(ignore_permissions=True)
	for user, customer, group in (
		(USER, CUSTOMER, RESELLER_GROUP),
		(OTHER_USER, OTHER_CUSTOMER, RESELLER_GROUP),
		(OUT_USER, OUT_CUSTOMER, CONSUMER_GROUP),
	):
		portal_customer(user, customer)
		frappe.db.set_value(
			"Customer",
			customer,
			{"customer_group": group, "disabled": 0, "default_price_list": RESELLER_LIST if group == RESELLER_GROUP else ""},
		)

	# the root is asked of the site: a site installed in French has no "All Item Groups"
	root = frappe.db.get_value("Item Group", {"lft": 1}, "name")
	_group(PARENT_GROUP, root, 1)
	_group(CHILD_GROUP, PARENT_GROUP, 0)
	_group(OTHER_GROUP, root, 0)
	for brand in (BRAND_A, BRAND_B):
		if not frappe.db.exists("Brand", brand):
			frappe.get_doc({"doctype": "Brand", "brand": brand}).insert(ignore_permissions=True)

	out = io.BytesIO()
	Image.new("RGB", (800, 600), (200, 80, 40)).save(out, "PNG")
	picture = frappe.get_doc({"doctype": "File", "file_name": PICTURE, "content": out.getvalue(), "is_private": 0}).insert(
		ignore_permissions=True
	)

	for code, group, brand, shop_rate, reseller_rate, image in (
		(FIRST, CHILD_GROUP, BRAND_A, 100, 80, picture.file_url),
		(SECOND, PARENT_GROUP, BRAND_A, 50, 40, None),
		(THIRD, OTHER_GROUP, BRAND_B, 30, 30, None),
		(HIDDEN, CHILD_GROUP, BRAND_A, 10, 10, None),
		(SOLD, CHILD_GROUP, BRAND_A, 10, 10, None),
	):
		item = make_test_item(code, item_name=f"{code} <b>name</b>", item_group=group, brand=brand, is_stock_item=0)
		_price(item.name, shop_list, shop_rate)
		_price(item.name, RESELLER_LIST, reseller_rate)
		fields = {"web_item_name": f"{code} name", "short_description": "<p>A <b>short</b> text.</p>"}
		if image:
			fields["website_image"] = image
		site = _publish(item, **fields)
		if code == HIDDEN:
			frappe.db.set_value("Website Item", site.name, "published", 0)
		if code == SOLD:
			frappe.db.set_value("Website Item", site.name, "sold", 1)

	if not frappe.db.exists("Item Attribute", ATTRIBUTE):
		frappe.get_doc(
			{
				"doctype": "Item Attribute",
				"attribute_name": ATTRIBUTE,
				"item_attribute_values": [{"attribute_value": v, "abbr": v[:3].upper()} for v in ("Small", "Large")],
			}
		).insert(ignore_permissions=True)
	template = make_test_item(
		MODEL, item_name="Cat model", item_group=CHILD_GROUP, brand=BRAND_B, has_variants=1, is_stock_item=0, attributes=[{"attribute": ATTRIBUTE}]
	)
	from erpnext.controllers.item_variant import create_variant

	for size, shop_rate, reseller_rate in (("Small", 60, 48), ("Large", 90, 72)):
		variant = create_variant(template.name, {ATTRIBUTE: size})
		variant.is_stock_item = 0
		variant.insert(ignore_permissions=True)
		_price(variant.name, shop_list, shop_rate)
		_price(variant.name, RESELLER_LIST, reseller_rate)
		_publish(variant)
	_publish(template, web_item_name="Cat model")
	frappe.db.commit()
	return {"picture_url": picture.file_url, "shop_list": shop_list, "currency": currency}


def variants():
	return frappe.get_all("Item", filters={"variant_of": MODEL}, pluck="name")


def purge():
	"""Everything `make` built, in the order that lets the links go."""
	codes = [*ITEMS, *variants(), MODEL]
	for code in codes:
		for name in frappe.get_all("Website Item", filters={"item_code": code}, pluck="name"):
			frappe.delete_doc("Website Item", name, force=True, ignore_permissions=True)
		frappe.db.delete("Item Price", {"item_code": code})
	for code in [*variants(), MODEL, *ITEMS]:
		if frappe.db.exists("Item", code):
			frappe.delete_doc("Item", code, force=True, ignore_permissions=True)
	for doctype in ("Item Attribute",):
		if frappe.db.exists(doctype, ATTRIBUTE):
			frappe.delete_doc(doctype, ATTRIBUTE, force=True, ignore_permissions=True)
	for name in frappe.get_all("File", filters={"file_name": PICTURE}, pluck="name"):
		frappe.delete_doc("File", name, force=True, ignore_permissions=True)
	for customer in (CUSTOMER, OTHER_CUSTOMER, OUT_CUSTOMER):
		if frappe.db.exists("Reseller Catalogue Profile", customer):
			for name in frappe.get_all(
				"File", filters={"attached_to_doctype": "Reseller Catalogue Profile", "attached_to_name": customer}, pluck="name"
			):
				frappe.delete_doc("File", name, force=True, ignore_permissions=True)
			frappe.delete_doc("Reseller Catalogue Profile", customer, force=True, ignore_permissions=True)
		if frappe.db.exists("DocType", "Reseller Catalogue"):
			for name in frappe.get_all("Reseller Catalogue", filters={"customer": customer}, pluck="name"):
				frappe.delete_doc("Reseller Catalogue", name, force=True, ignore_permissions=True)
		if frappe.db.exists("Customer", customer):
			frappe.db.set_value("Customer", customer, "default_price_list", "")
	if frappe.db.exists("Price List", RESELLER_LIST):
		frappe.db.delete("Item Price", {"price_list": RESELLER_LIST})
		frappe.delete_doc("Price List", RESELLER_LIST, force=True, ignore_permissions=True)
	for group in (CHILD_GROUP, OTHER_GROUP, PARENT_GROUP):
		if frappe.db.exists("Item Group", group):
			frappe.delete_doc("Item Group", group, force=True, ignore_permissions=True)
	for brand in (BRAND_A, BRAND_B):
		if frappe.db.exists("Brand", brand):
			frappe.delete_doc("Brand", brand, force=True, ignore_permissions=True)
	frappe.db.commit()
