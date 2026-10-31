# //// Neoffice — added file (no upstream equivalent).
"""The reseller's product feed: make it, refresh it, change its address, stop it.

Open to the customers of the groups the shop allowed (`access.require_reseller` starts every endpoint) and to
nobody else; identity comes from the session, no endpoint takes a customer. Each answers the page's whole
state (`catalogue_api._state`, which carries the feed) or a refusal `{"ok": false, "field", "message"}`.
What the feed is made from is a selection and two options, a markup and a price mode; the browser sends no price.
"""

import json

import frappe

from webshop.webshop.catalogue import access, catalogue_api, feed
from webshop.webshop.catalogue import api as brand_api
from webshop.webshop.utils import throttle


@frappe.whitelist(methods=["POST"])
@throttle.throttle("feed-save", 20, 3600)
def save_feed(picked=None, options=None):
	customer = access.require_reseller()
	payload = brand_api._payload(customer)
	refusal = feed.save(customer, payload, catalogue_api._json(picked), catalogue_api._json(options))
	return refusal or catalogue_api._state(customer, payload)


@frappe.whitelist(methods=["POST"])
@throttle.throttle("feed-refresh", 20, 3600)
def refresh_feed():
	customer = access.require_reseller()
	return feed.refresh_now(customer) or catalogue_api._state(customer)


@frappe.whitelist(methods=["POST"])
@throttle.throttle("feed-rotate", 20, 3600)
def new_feed_address():
	customer = access.require_reseller()
	return feed.rotate(customer) or catalogue_api._state(customer)


@frappe.whitelist(methods=["POST"])
def delete_feed():
	customer = access.require_reseller()
	feed.delete(customer)
	return catalogue_api._state(customer)
