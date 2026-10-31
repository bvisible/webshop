# //// Neoffice — added file (no upstream equivalent).
"""The reseller's product feeds: make one, refresh it, change its address, stop it. Up to three.

Open to the customers of the groups the shop allowed (`access.require_reseller` starts every endpoint) and to
nobody else; identity comes from the session, no endpoint takes a customer. A feed is named by `name` (empty:
their first one); a name that is not one of theirs is not told apart from one that does not exist. Each answers
the page's whole state (`catalogue_api._state`, which carries the feeds) or a refusal
`{"ok": false, "field", "message"}`. What a feed is made from is a selection and two options, a markup and a price
mode; the browser sends no price.
"""

import frappe

from webshop.webshop.catalogue import access, catalogue_api, feed
from webshop.webshop.catalogue import api as brand_api
from webshop.webshop.utils import throttle


@frappe.whitelist(methods=["POST"])
@throttle.throttle("feed-save", 20, 3600)
def save_feed(picked=None, options=None, name=None, title=None):
	"""A new feed (no `name`), or what one of theirs is made from (its address stays)."""
	customer = access.require_reseller()
	payload = brand_api._payload(customer)
	refusal = feed.save(customer, payload, catalogue_api._json(picked), catalogue_api._json(options), name=_name(name), title=title)
	return refusal or catalogue_api._state(customer, payload)


@frappe.whitelist(methods=["POST"])
@throttle.throttle("feed-refresh", 20, 3600)
def refresh_feed(name=None):
	customer = access.require_reseller()
	return feed.refresh_now(customer, _name(name)) or catalogue_api._state(customer)


@frappe.whitelist(methods=["POST"])
@throttle.throttle("feed-rotate", 20, 3600)
def new_feed_address(name=None):
	customer = access.require_reseller()
	return feed.rotate(customer, _name(name)) or catalogue_api._state(customer)


@frappe.whitelist(methods=["POST"])
def delete_feed(name=None):
	customer = access.require_reseller()
	feed.delete(customer, _name(name))
	return catalogue_api._state(customer)


def _name(value):
	"""A feed's name as the page sent it: text, or nothing (their first feed)."""
	if value in (None, ""):
		return None
	# anything but a text names no feed: it must not become "their first one"
	return value if isinstance(value, str) else "?"
