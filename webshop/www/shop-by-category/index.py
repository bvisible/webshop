# //// Neoffice — json + quote build the /all-products?field_filters=… link a Select
# //// card points to, in _select_cards() below (ccce63886e "fix(shop-by-category):
# //// un filtre Select ne fait plus tomber la page entière").
import json
from urllib.parse import quote

import frappe
from frappe import _

sitemap = 1


def get_context(context):
	context.body_class = "product-page"
	# //// Neoffice — themes print context.title as the visible heading and as the last
	# //// breadcrumb, and Frappe defaults it to the route name: a French shop read
	# //// "Shop By Category" on screen while its browser tab said "Catégories et marques".
	# //// Same fix as build_listing_context() already carries for /all-products.
	context.title = _("Category and Brands")
	context.parents = [{"name": _("Home"), "route": "/"}]

	settings = frappe.get_cached_doc("Webshop Settings")
	context.categories_enabled = settings.enable_field_filters

	if context.categories_enabled:
		categories = [row.fieldname for row in settings.filter_fields]
		context.tabs = get_tabs(categories)

	if settings.slideshow:
		context.slideshow = get_slideshow(settings.slideshow)
	
	context.no_cache = 1

	# //// Neoffice — a visitor who signs in here keeps the cart they filled as a guest: the
	# //// two carts are merged (e0435e0dd6, 2025-06-26).
	from webshop.webshop.shopping_cart.guest_cart import check_and_merge_guest_cart
	check_and_merge_guest_cart()

def get_slideshow(slideshow):
	values = {"show_indicators": 1, "show_controls": 1, "rounded": 1, "slider_name": "Categories"}
	slideshow = frappe.get_cached_doc("Website Slideshow", slideshow)
	slides = slideshow.get({"doctype": "Website Slideshow Item"})
	for index, slide in enumerate(slides, start=1):
		values[f"slide_{index}_image"] = slide.image
		values[f"slide_{index}_title"] = slide.heading
		values[f"slide_{index}_subtitle"] = slide.description
		values[f"slide_{index}_theme"] = slide.get("theme") or "Light"
		values[f"slide_{index}_content_align"] = slide.get("content_align") or "Centre"
		values[f"slide_{index}_primary_action"] = slide.url

	return values


def get_tabs(categories):
	tab_values = {
		# //// Neoffice — the tab title matches the page title: categories AND brands
		# //// (48e2708353, 2025-03-13).
		"title": _("Category and Brands"),
	}

	categorical_data = get_category_records(categories)
	# //// Neoffice — fetched here so the loop below can read each tab field's own
	# //// label instead of unscrubbing the fieldname (see the marker a few lines down;
	# //// ccce63886e "fix(shop-by-category): un filtre Select ne fait plus tomber la page entière").
	website_item_meta = frappe.get_meta("Website Item", cached=True)
	for index, tab in enumerate(categorical_data, start=1):
		# //// Neoffice — the tab takes the field's own label, translated. Upstream prints
		# //// frappe.unscrub(fieldname), which on a French shop reads "Item Condition"
		# //// next to "Catégorie" and "Marque" — and a fieldname is not a label anyway.
		df = website_item_meta.get_field(tab)
		tab_values[f"tab_{index + 1}_title"] = _(df.label) if df and df.label else frappe.unscrub(tab)
		# pre-render cards for each tab
		tab_values[f"tab_{index + 1}_content"] = frappe.render_template(
			"webshop/www/shop-by-category/category_card_section.html",
			{"data": categorical_data[tab], "type": tab},
		)
	return tab_values


# //// Neoffice — added with the Select branch above.
def _select_cards(fieldname):
	"""Cards for a Select filter field: the values published items actually carry.

	Listing every option of the field would offer "Refurbished" on a shop that has
	never sold one, and the card would lead to an empty catalogue. So the scope is
	the sidebar facet's own (`ProductFiltersBuilder.get_field_filters`): published,
	visible on this site, gift cards out when they are off, variants out when the
	shop hides them. Each card links to the catalogue already filtered on its value.
	"""
	from webshop.webshop.multi_site import excluded_item_names
	from webshop.webshop.product_data_engine.filters import gift_cards_hidden, select_facet_is_useful

	filters = {"published": 1}
	excluded = excluded_item_names()
	if excluded:
		filters["name"] = ["not in", excluded]
	if gift_cards_hidden():
		filters["is_gift_card"] = 0
	if frappe.db.get_single_value("Webshop Settings", "hide_variants"):
		filters["variant_of"] = ["is", "not set"]

	values = {
		value
		for value in frappe.get_all(
			"Website Item", fields=[fieldname], filters=filters, distinct=True, pluck=fieldname
		)
		if value
	}
	# //// Neoffice — the sidebar's own rule: no cards when the field offers no choice,
	# //// so the page and the facets stop disagreeing.
	if not select_facet_is_useful(fieldname, values):
		return []

	# The card reads in the visitor's language; the link carries the value stored on
	# the item, which is what the catalogue filters on.
	return [
		frappe._dict(
			name=_(value),
			value=value,
			route="/all-products?field_filters=" + quote(json.dumps({fieldname: [value]})),
		)
		for value in sorted(values, key=lambda v: _(v))
	]


def get_category_records(categories):
	categorical_data = {}
	website_item_meta = frappe.get_meta("Website Item", cached=True)

	for category in categories:
		df = website_item_meta.get_field(category)
		# //// Neoffice — a filter field that no longer exists on Website Item is skipped
		# //// rather than crashing the page for everyone.
		if df is None and category != "item_group":
			continue
		# //// Neoffice — a Select filter field has no linked doctype: its options ARE the
		# //// values. The Condition field the second-hand feature added (New / Refurbished /
		# //// Second-hand) is one, and this branch used to read `.options` as a doctype name,
		# //// so frappe.get_meta("New\nRefurbished\nSecond-hand") raised DoesNotExistError
		# //// and the whole page answered 403 — "Non autorisé" — to every visitor, signed in
		# //// or not. Reported 2026-09-10 on theleague.neoffice.me, reproduced on osiris.
		# //// The facets already handled Select (product_data_engine/filters.py); this page
		# //// never learned to.
		if df is not None and df.fieldtype == "Select":
			cards = _select_cards(category)
			if cards:
				categorical_data[category] = cards
			continue
		if category == "item_group":
			categorical_data["item_group"] = frappe.db.get_all(
				"Item Group",
				filters={"show_in_website": 1},
				fields=["name", "parent_item_group", "is_group", "image", "route"],
			)
		else:
			# //// Neoffice — `doctype` was read from the loop above without ever being
			# //// initialised: a Table MultiSelect whose child has no mandatory Link left it
			# //// unbound (UnboundLocalError), or carried the PREVIOUS tab's doctype.
			doctype = None
			field_type = df.fieldtype

			# //// Neoffice — see the marker above: `df` replaces the repeated
			# //// get_field(category) calls this branch used to make.
			if field_type == "Table MultiSelect":
				child_doc = df.options
				for field in frappe.get_meta(child_doc, cached=True).fields:
					if field.fieldtype == "Link" and field.reqd:
						doctype = field.options
			else:
				# //// Neoffice — see the marker above: `df` replaces the repeated
				# //// get_field(category) calls this branch used to make.
				doctype = df.options

			fields = ["name"]

			# //// Neoffice — a filter field pointing at a doctype that no longer exists used to
			# //// raise here, OUTSIDE the try below, and the page answered 403 to everyone. One
			# //// misconfigured filter now costs its own tab, not the whole page.
			try:
				meta = frappe.get_meta(doctype, cached=True) if doctype else None
			except frappe.DoesNotExistError:
				meta = None
			if not meta:
				continue
			if meta.get_field("image"):
				fields += ["image"]

			filters = {}
			if meta.get_field("show_in_website"):
				filters = {"show_in_website": 1}

			elif meta.get_field("custom_show_in_website"):
				filters = {"custom_show_in_website": 1}

			try:
				if filters:
					categorical_data[category] = frappe.db.get_all(doctype, fields=fields, filters=filters)
				else:
					categorical_data[category] = frappe.db.get_all(doctype, fields=fields)

			except BaseException:
				frappe.throw(_("DocType {} not found").format(doctype))

	return categorical_data
