# //// Neoffice — added file (no upstream equivalent).
"""Counting the calls of the endpoints a stranger can reach, per connection.

Frappe's `rate_limit` keys on `frappe.local.request_ip`, which is the FIRST entry of `X-Forwarded-For`. Where nginx
appends to the header (`$proxy_add_x_forwarded_for`, what the shop vhosts of the fleet write) that entry is whatever the
caller sent: a caller who changes it on every request is never counted twice. Measured on a shop vhost, 2026-10-30:
25 requests out of 25 went through a limit of 20.

Here the address counted is the LAST entry: nginx's own under both ways of writing the header (`$remote_addr` leaves
one entry, `$proxy_add_x_forwarded_for` appends the peer after the caller's). The same reading the hub's address guards
make (`neoffice_devops.guards.request_peer_ip`); webshop cannot import it, it is not installed on the instances.

Behind a CDN that nginx does not unwrap, the last entry is the CDN's: every visitor then shares its budget. Put the
real-address handling in nginx (`set_real_ip_from`) before putting a CDN in front of a shop.

A call that is not an HTTP request (a test, a background job) is never counted.
"""

from functools import wraps

import frappe
from frappe import _

PREFIX = "webshop_throttle"


def peer_ip():
	"""The address of the connection nginx accepted, the one entry of X-Forwarded-For a caller cannot write."""
	try:
		forwarded = frappe.get_request_header("X-Forwarded-For") or ""
	except (AttributeError, RuntimeError):  # no request is bound
		forwarded = ""
	entries = [part.strip() for part in forwarded.split(",") if part.strip()]
	if entries:
		return entries[-1]
	return (getattr(frappe.local, "request_ip", None) or "").strip() or "unknown"


def _key(name, identity):
	return frappe.cache().make_key(f"{PREFIX}:{name}:{identity}")


def hit(name, identity, seconds):
	"""Count one call of `identity` under `name`; returns how many the window has seen, this one included.

	The window is written before the count, in one atomic call: a process that dies between the two cannot leave a
	counter that never ends (and blocks an address for good).
	"""
	cache = frappe.cache()
	key = _key(name, identity)
	cache.set(key, 0, ex=seconds, nx=True)
	return int(cache.incr(key))


def reset(name, identity):
	frappe.cache().delete(_key(name, identity))


def throttle(name, limit, seconds, on_refuse=None):
	"""Refuse (429) the call number `limit + 1` of one connection within `seconds`. Stack two for a short and a long window.

	`on_refuse`, when given, is called with no argument just before the refusal: the refusal happens before the endpoint
	runs, so it is the only place that can count it.
	"""

	def decorator(fn):
		@wraps(fn)
		def wrapper(*args, **kwargs):
			if getattr(frappe.local, "request", None) and hit(name, peer_ip(), seconds) > limit:
				if on_refuse:
					on_refuse()
				frappe.throw(
					_("You hit the rate limit because of too many requests. Please try after sometime."),
					frappe.RateLimitExceededError,
				)
			return fn(*args, **kwargs)

		return wrapper

	return decorator
