# //// Neoffice — added file (no upstream equivalent). The catalogue's scope, in one place:
# //// what a visitor of THIS site can be shown. /shop-by-category built it for its cards,
# //// the sitemaps and the SEO descriptions need the very same answer (2026-09-24), and two
# //// copies of a scope rule are exactly how the category page and the facets had drifted
# //// before (CLAUDE.md, "The category page").
import frappe


def visible_item_filters():
	"""Website Item filters for what the catalogue can show on the site being browsed.

	Published, not sold, visible on this site, gift cards out when the shop does not sell
	them, variants out when the shop hides them — `ProductFiltersBuilder.get_field_filters`
	builds every facet from exactly this.
	"""
	from webshop.webshop.multi_site import excluded_item_names
	from webshop.webshop.product_data_engine.filters import gift_cards_hidden

	filters = {"published": 1, "sold": 0}
	excluded = excluded_item_names()
	if excluded:
		filters["name"] = ["not in", excluded]
	if gift_cards_hidden():
		filters["is_gift_card"] = 0
	if frappe.db.get_single_value("Webshop Settings", "hide_variants"):
		filters["variant_of"] = ["is", "not set"]
	return filters


def groups_carrying_items():
	"""{item group: how many visible items its whole subtree carries}, for groups shown on the website.

	A group counts what its subtree holds, not what sits directly in it: the facet keeps a
	group carrying items AND its ancestors, so a parent whose children hold the products
	answers for them.
	"""
	carried = {
		row.item_group: row.total
		for row in frappe.get_all(
			"Website Item",
			fields=["item_group", "count(name) as total"],
			filters=visible_item_filters(),
			group_by="item_group",
		)
		if row.item_group
	}
	if not carried:
		return {}
	edges = [
		(row.lft, carried[row.name])
		for row in frappe.get_all("Item Group", filters={"name": ("in", list(carried))}, fields=["name", "lft"])
	]
	out = {}
	for group in frappe.get_all(
		"Item Group", filters={"show_in_website": 1}, fields=["name", "lft", "rgt"]
	):
		total = sum(count for lft, count in edges if group.lft <= lft <= group.rgt)
		if total:
			out[group.name] = total
	return out
