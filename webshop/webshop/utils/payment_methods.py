# //// Neoffice — added file (no upstream equivalent).
"""Which payment methods a given shopper is offered.

Upstream offers every row of `Webshop Settings.payment_methods` to everybody. A
shop that sells to businesses cannot do that: a customer who has just been
approved pays in advance by bank transfer, an established reseller buys on
account, and a consumer pays by card — three different sets of tiles on the same
checkout.

The rule lives on the row: **one row is one method offered to one audience, on
its own terms**. `customer_group` empty means everyone; filled, it covers that
group *and its sub-groups* — customer groups are a tree, and a method offered to
the parent has to reach the children. Add the same gateway on several rows, one
per group, when each group needs its own `payment_terms_template`.

When two rows of the same gateway match, the more specific one wins: the row
naming the shopper's own group beats the row naming its parent, which beats the
row naming nobody. So a shop states the general case once and overrides it where
it differs, instead of listing every group on every method.
"""

import frappe


def group_lineage(customer_group):
	"""The group and every ancestor of it, closest first.

	A method offered to a parent group is offered to its children, so matching
	walks up the tree rather than comparing names. The order is what decides which
	row wins when several match.
	"""
	if not customer_group:
		return []
	bounds = frappe.db.get_value("Customer Group", customer_group, ["lft", "rgt"], as_dict=True)
	if not bounds:
		return []
	ancestors = frappe.get_all(
		"Customer Group",
		filters={"lft": ["<=", bounds.lft], "rgt": [">=", bounds.rgt]},
		fields=["name"],
		order_by="lft desc",
	)
	return [row.name for row in ancestors]


def customer_group_of(doc):
	"""The customer group of the document being paid, or None.

	A Quotation names its party in `party_name`; an order or an invoice in
	`customer`. `customer_name` is the LABEL and matches the id only while
	customers are named after themselves — reading it resolves nothing on a shop
	that names its customers by series.
	"""
	if not doc:
		return None
	party = doc.get("party_name") or doc.get("customer")
	if not party:
		return None
	return frappe.db.get_value("Customer", party, "customer_group")


def rows_for_group(settings=None, customer_group=None):
	"""The payment method rows this shopper may use, in the order the shop set.

	One row per gateway account: when several rows of the same gateway match, the
	one naming the closest group wins, so its own payment terms are the ones that
	apply.
	"""
	settings = settings or frappe.get_cached_doc("Webshop Settings")
	lineage = group_lineage(customer_group)
	# 0 is the shopper's own group, then each ancestor; a row aimed at nobody
	# ranks last, so any group-specific row beats it.
	distance = {name: index for index, name in enumerate(lineage)}
	unaimed = len(lineage) + 1

	best = {}
	for row in settings.get("payment_methods") or []:
		aimed_at = (row.get("customer_group") or "").strip()
		if aimed_at:
			if aimed_at not in distance:
				continue
			score = distance[aimed_at]
		else:
			score = unaimed
		key = row.payment_gateway_account
		if key not in best or score < best[key][0]:
			best[key] = (score, row)
	return [row for _score, row in best.values()]


def row_for_gateway(gateway_account, settings=None, customer_group=None):
	"""The row this shopper would use for one gateway account, or None.

	`payment_handler` needs it to know which payment terms to write on the
	document: reading the first row that mentions the gateway would apply another
	group's terms.
	"""
	for row in rows_for_group(settings, customer_group):
		if row.payment_gateway_account == gateway_account:
			return row
	return None
