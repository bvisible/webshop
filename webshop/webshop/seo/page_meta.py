# //// Neoffice — added file (no upstream equivalent). neoffice-maintenance#691, lot 6.
"""What a product's, a category's and a brand's page tell search engines: their title, the title of
the browser tab (with the shop's name), and their description. One place computes it: the page
prints it (WebsiteItem.get_context, WebshopItemGroup.get_context, www/brand), and the desk's
preview of the Search engines fields shows it before the merchant saves (seo_preview).

What the merchant wrote in those fields (seo_title, seo_description) wins; left empty, the page
says what it always computed. Google shows about TITLE_BUDGET characters of a title and
DESCRIPTION_BUDGET of a description: the fields are not cut, the preview says when they are long."""

import frappe
from frappe import _

from webshop.webshop.seo import site
from webshop.webshop.seo.text import one_line

TITLE_BUDGET = 60
DESCRIPTION_BUDGET = 160
# the computed description of a product or a category stops at a word, before this
EXCERPT = 158


def with_shop_name(title, name=None):
	"""The browser tab's title: the page's, then the shop's name, unless the merchant wrote it in."""
	# read at the call: a test replaces seo.site.shop_name, never this module's copy of it
	name = site.shop_name() if name is None else name
	if not title or not name or name.lower() in title.lower():
		return title
	return f"{title} | {name}"


def product_meta(doc, own=True):
	"""A product page: its heading (the name, and the brand after it), its title and description.
	`own=False` leaves out what the merchant wrote: the desk's preview shows it as the default."""
	heading = f"{doc.web_item_name} - {doc.brand}" if doc.get("brand") else doc.web_item_name
	title = (own and (doc.get("seo_title") or "").strip()) or heading
	description = (own and one_line(doc.get("seo_description") or "", DESCRIPTION_BUDGET * 2)) or (
		one_line(doc.get("web_long_description") or doc.get("description") or "", EXCERPT) or doc.web_item_name
	)
	return frappe._dict(heading=heading, title=title, html_title=with_shop_name(title), description=description)


def item_group_meta(doc, own=True):
	"""A category page: the group's name (or its website title), and what it says or holds."""
	from webshop.webshop.seo.meta import catalogue_summary, subtree_groups, summary_description

	heading = doc.get("website_title") or doc.name
	title = (own and (doc.get("seo_title") or "").strip()) or heading
	description = (own and one_line(doc.get("seo_description") or "", DESCRIPTION_BUDGET * 2)) or one_line(
		doc.get("description") or "", EXCERPT
	)
	if not description:
		total, brands = catalogue_summary(subtree_groups(doc.name))
		description = summary_description(heading, total, brands) if total else ""
	return frappe._dict(heading=heading, title=title, html_title=with_shop_name(title), description=description)


def brand_meta(brand, own=True):
	"""A brand's page: the brand, and its own text when it has one (the page's listing description
	otherwise, which build_listing_context writes)."""
	fields = ["description"]
	# the table's columns, not the doctype's meta: a site that has not migrated yet has no such field
	if frappe.db.has_column("Brand", "seo_title"):
		fields += ["seo_title", "seo_description"]
	record = frappe.db.get_value("Brand", brand, fields, as_dict=True) or frappe._dict()
	title = (own and (record.get("seo_title") or "").strip()) or brand
	description = (own and one_line(record.get("seo_description") or "", DESCRIPTION_BUDGET * 2)) or one_line(
		record.get("description") or "", DESCRIPTION_BUDGET
	)
	return frappe._dict(heading=brand, title=title, html_title=with_shop_name(title), description=description)


PREVIEWED = ("Website Item", "Item Group", "Brand")


@frappe.whitelist()
def seo_preview(doctype: str, name: str):
	"""The page's own title, description and address, as the Search engines fields' defaults."""
	if doctype not in PREVIEWED:
		frappe.throw(_("No preview for {0}").format(doctype))
	frappe.has_permission(doctype, "read", name, throw=True)
	from webshop.webshop.multi_site import site_url

	if doctype == "Website Item":
		doc = frappe.get_doc(doctype, name)
		meta, route = product_meta(doc, own=False), doc.route
	elif doctype == "Item Group":
		doc = frappe.get_doc(doctype, name)
		meta, route = item_group_meta(doc, own=False), doc.get("route")
	else:
		from webshop.webshop.product_data_engine.brand_pages import brand_page_routes

		meta, route = brand_meta(name, own=False), (brand_page_routes().get(name) or "")
	return {
		"title": meta.title,
		"description": meta.description,
		"url": site_url("/" + (route or "").lstrip("/")) if route else "",
		"shop": site.shop_name() or "",
		"title_budget": TITLE_BUDGET,
		"description_budget": DESCRIPTION_BUDGET,
	}
