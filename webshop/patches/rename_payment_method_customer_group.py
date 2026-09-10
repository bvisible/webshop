# //// Neoffice — added file (no upstream equivalent).
"""Move a payment method's audience off a field Frappe fills by itself.

The column started life as `customer_group`, and Frappe fills a Link field of
that name with the session default at insert time (Selling Settings). So the
rule "empty means everyone" could never happen: every row came back naming
whatever group the session defaulted to, and on a shop whose default is a real
group — not the tree's root — every payment method would silently have been
restricted to it.

The field is `only_customer_group` now. This carries over what was already
written, and drops a value that is merely the tree's ROOT: a method aimed at
"all customer groups" is a method aimed at nobody in particular, and saying so
is what makes the settings readable.

Same trap, same fix as `Cross Sell Offer.only_customer_group`.
"""

import frappe


def execute():
	table = "tabWebshop Payment Method"
	if not frappe.db.table_exists(table.replace("tab", "", 1)):
		return
	columns = {row.Field for row in frappe.db.sql(f"DESCRIBE `{table}`", as_dict=True)}
	if "only_customer_group" not in columns:
		# the doctype sync has not run yet; it will, and there is nothing to move
		return

	if "customer_group" in columns:
		frappe.db.sql(
			f"""UPDATE `{table}`
			SET only_customer_group = customer_group
			WHERE IFNULL(only_customer_group, '') = '' AND IFNULL(customer_group, '') != ''"""
		)

	root = frappe.db.get_value("Customer Group", {"lft": 1}, "name")
	if root:
		frappe.db.sql(
			f"UPDATE `{table}` SET only_customer_group = NULL WHERE only_customer_group = %s",
			root,
		)
