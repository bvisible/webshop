# //// Neoffice — added file (no upstream equivalent).
"""`/partner/v1/...`: the partner API's door. A page renderer, not a whitelisted method, for three reasons.

- The address is the contract's (`/partner/v1/products`), not `/api/method/<python path>`: a rename of a function
  must never be a break of a reseller's integration, and no nginx rewrite has to exist on every instance.
- Frappe's own authentication runs before any route and answers 401 to an `Authorization` header it does not
  know; the key travels in `X-API-Key`, which only this renderer reads.
- Nothing here is a session: the request is a Guest's, the key says which customer and what they may do, and
  every write goes through the shop's rights (`shop_rights`), never through a user the key could borrow.

Answers are JSON with one error shape, `{"error": {"code", "message", "details"?}}`; the code is what a program
reads. English, whatever the site speaks. `openapi.yaml` (served at `/partner/v1/openapi.yaml`) is the contract.
"""

import json
import os

import frappe
from frappe.website.page_renderers.base_renderer import BaseRenderer
from werkzeug.wrappers import Response

from webshop.webshop.multi_site import site_url
from webshop.webshop.partner_api import access as partner_access
from webshop.webshop.partner_api import v1
from webshop.webshop.partner_api.access import ApiError
from webshop.webshop.utils import throttle

ROOT = "partner/v1"
SPEC = os.path.join(os.path.dirname(__file__), "openapi.yaml")
MAX_BODY = 256 * 1024
ROUTES = {
	# (first path segment, with an id after it?) -> {method: (scope, handler)}
	("products", False): {"GET": ("products", lambda access, args, body, rest: v1.list_products(access, args))},
	("products", True): {"GET": ("products", lambda access, args, body, rest: v1.get_product(access, rest))},
	("orders", False): {
		"GET": ("orders", lambda access, args, body, rest: v1.list_orders(access, args)),
		"POST": ("orders", None),
	},
	("orders", True): {"GET": ("orders", lambda access, args, body, rest: v1.get_order(access, rest))},
}


def _json(status, payload, headers=None):
	response = Response(json.dumps(payload, default=str), status=status, content_type="application/json; charset=utf-8")
	response.headers["Cache-Control"] = "no-store"
	response.headers["X-Content-Type-Options"] = "nosniff"
	response.headers["X-Robots-Tag"] = "noindex"
	for name, value in (headers or {}).items():
		response.headers[name] = value
	return response


def _error(status, code, message, headers=None, details=None):
	body = {"code": code, "message": message}
	if details:
		body["details"] = details
	return _json(status, {"error": body}, headers)


def _body():
	"""The JSON a POST sent, or an ApiError."""
	if (frappe.request.content_length or 0) > MAX_BODY:
		raise ApiError(413, "body_too_large", "The body is limited to 256 KB.")
	data = frappe.request.get_json(silent=True)
	if data is None:
		raise ApiError(400, "invalid_json", "The body is not JSON (send Content-Type: application/json).")
	return data


class PartnerApiRenderer(BaseRenderer):
	def can_render(self):
		return self.path == ROOT or self.path.startswith(ROOT + "/")

	def render(self):
		previous = frappe.local.lang
		frappe.local.lang = "en"  # the contract is in English; ERPNext's own sentences too
		try:
			return self.handle()
		except ApiError as error:
			return _error(error.status, error.code, error.message, error.headers, error.details)
		except Exception:
			frappe.db.rollback()
			frappe.log_error("Partner API failed", frappe.get_traceback())
			return _error(500, "internal_error", "Something went wrong on our side. The team has been told.")
		finally:
			frappe.local.lang = previous

	def handle(self):
		rest = self.path[len(ROOT) :].strip("/")
		method = frappe.request.method
		if rest in ("", "openapi.yaml"):
			return self.public(rest, method)
		parts = rest.split("/", 1)
		route = ROUTES.get((parts[0], len(parts) == 2 and bool(parts[1])))
		if not route:
			raise ApiError(404, "not_found", "No such address. See openapi.yaml.")
		if method not in route:
			raise ApiError(405, "method_not_allowed", f"Use {', '.join(sorted(route))} here.", {"Allow": ", ".join(sorted(route))})
		peer = throttle.peer_ip() if getattr(frappe.local, "request", None) else None
		access = partner_access.authenticate(frappe.get_request_header("X-API-Key"), peer)
		partner_access.check_rate(access)
		scope, handler = route[method]
		if not access.get("scope_" + scope):
			raise ApiError(403, "scope_missing", f"This key may not use {scope}.")
		if method == "POST":
			status, payload, replayed = v1.create_order(access, _body())
			partner_access.record_use(access)
			return _json(status, payload, {"Idempotent-Replayed": "true"} if replayed else None)
		payload = handler(access, frappe.request.args, None, parts[1] if len(parts) == 2 else None)
		partner_access.record_use(access)
		return _json(200, payload)

	def public(self, rest, method):
		"""The two addresses that need no key: the index and the contract."""
		if method != "GET":
			raise ApiError(405, "method_not_allowed", "Use GET here.", {"Allow": "GET"})
		if rest == "":
			return _json(200, {"name": "Neoffice partner API", "version": "v1", "contract": site_url(f"/{ROOT}/openapi.yaml")})
		with open(SPEC, "rb") as handle:  # nosemgrep: frappe-semgrep-rules.rules.security.frappe-security-file-traversal
			content = handle.read()
		response = Response(content, content_type="application/yaml; charset=utf-8")
		response.headers["Cache-Control"] = "public, max-age=300"
		return response
