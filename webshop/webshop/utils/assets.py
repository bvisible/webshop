# //// Neoffice — added file (no upstream equivalent).
"""A component's stylesheet, carried by the component itself.

A page Builder renders loads neither `web_include_js` nor `web_include_css` of
this app, so a shop component included in such a page — a product carousel, the
opening hours, a brand strip — would come out unstyled if its CSS lived only in
the shop bundle. Each of those components therefore owns a small bundle
(`public/scss/<name>.bundle.scss`) and prints it inline **once per request**
through `component_css()`; on a shop page that already loads the main bundle the
component's CSS is *not* in that bundle, so nothing is served twice.

The compiled file is read from the build output, never rewritten by hand: the
stylesheet the include prints is the one `bench build` produced.
"""

import os

import frappe
from frappe.utils import get_assets_json


def component_css(bundle):
	"""The compiled CSS of `<bundle>.bundle.css`, once per request.

	Returns "" on later calls within the same request — two carousels on one page
	must not carry the stylesheet twice — and "" when the asset is missing or
	unreadable, so a page never fails for want of a decoration.
	"""
	done = getattr(frappe.local, "webshop_component_css_done", None)
	if done is None:
		done = frappe.local.webshop_component_css_done = set()
	if bundle in done:
		return ""
	done.add(bundle)
	try:
		path = (get_assets_json() or {}).get(f"{bundle}.bundle.css")
		if not path:
			return ""
		# "/assets/webshop/dist/css/x.css" -> <bench>/sites/assets/webshop/dist/css/x.css
		full = os.path.join(frappe.local.sites_path, path.lstrip("/"))
		with open(full, encoding="utf-8") as fh:
			return fh.read()
	except Exception:
		frappe.log_error(f"Component stylesheet unavailable: {bundle}", frappe.get_traceback())
		return ""


def webshop_component_css(bundle):
	"""Jinja-facing name of `component_css`, registered in hooks."""
	return component_css(bundle)
