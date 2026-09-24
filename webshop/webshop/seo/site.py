# //// Neoffice — added file (no upstream equivalent). The name the shop goes by, for the
# //// tags that announce it to other sites.
import frappe

# Framework defaults a site keeps until someone names it: never a shop's name.
FRAMEWORK_NAMES = {"frappe", "erpnext"}


def shop_name() -> str:
	"""The shop's name, as its `<title>` suffix already prints it (Website Settings' app name).

	Upstream's `WebsiteItem.set_metatags` wrote `og:site_name = "ERPNext"` on every product
	page, so a link shared on a social network announced ERPNext instead of the shop.
	Empty when the site was never named: no tag beats a wrong one.
	"""
	name = (frappe.db.get_single_value("Website Settings", "app_name") or "").strip()
	return "" if name.lower() in FRAMEWORK_NAMES else name


def webshop_site_url(path="") -> str:
	"""Jinja method: an absolute address on the domain of the site being browsed.

	`frappe.utils.get_url` answers the instance's `host_name`: on the second domain of a
	multi-site instance, the breadcrumb's structured data pointed at the first one.
	"""
	from webshop.webshop.multi_site import site_url

	return site_url(path or "")
