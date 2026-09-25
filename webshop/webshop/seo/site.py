# //// Neoffice — added file (no upstream equivalent). The name the shop goes by, for the
# //// tags that announce it to other sites.
import frappe

# Framework defaults a site keeps until someone names it: never a shop's name.
FRAMEWORK_NAMES = {"frappe", "erpnext"}


def shop_name() -> str:
	"""The name of the site being served, the one every page announces: og:site_name, the
	title suffix, the seller of every offer, the listings' descriptions.

	Upstream's `WebsiteItem.set_metatags` wrote `og:site_name = "ERPNext"` on every product
	page, so a link shared on a social network announced ERPNext instead of the shop. Then the
	home page declared its WebSite under the site chrome's name while these pages announced
	Website Settings' (2026-09-24): Google reads them together to choose the name it prints, so
	the chrome's name comes first, per site, and Website Settings' only without a chrome.
	Empty when the site was never named: no tag beats a wrong one.
	"""
	name = chrome_site_name() or app_name()
	return "" if name.lower() in FRAMEWORK_NAMES else name


def app_name() -> str:
	return (frappe.db.get_single_value("Website Settings", "app_name") or "").strip()


def chrome_site_name() -> str:
	"""The name the site chrome gives the site being served (builder's display_name: the name
	of its home page's WebSite). Empty without builder, or with a builder older than it."""
	if "builder" not in frappe.get_installed_apps():
		return ""
	try:
		from builder.hf_utils.header_footer import get_header_footer_config
		from builder.site_graph import display_name
	except ImportError:
		return ""
	# the chrome's configuration is a document with child tables: read once per request and per
	# site, not once per title, description and breadcrumb that names it (#691 lot 5). Per site:
	# the feed's job serves every site of the instance in one process (seo/feeds/google.py serving)
	names = getattr(frappe.local, "webshop_chrome_site_names", None)
	if names is None:
		# frappe.local's own storage, which each request starts afresh (never its __dict__)
		names = frappe.local.webshop_chrome_site_names = {}
	profile = getattr(frappe.local, "website_profile", None)
	if profile not in names:
		config = get_header_footer_config()
		names[profile] = display_name(config) if config else ""
	return names[profile]


def webshop_site_url(path="") -> str:
	"""Jinja method: an absolute address on the domain of the site being browsed.

	`frappe.utils.get_url` answers the instance's `host_name`: on the second domain of a
	multi-site instance, the breadcrumb's structured data pointed at the first one.
	"""
	from webshop.webshop.multi_site import site_url

	return site_url(path or "")
