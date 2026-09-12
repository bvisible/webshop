import frappe
import json
from frappe import _
from webshop.webshop.shopping_cart.cart import decorate_quotation_doc

no_cache = 1


# //// Neoffice — is this order the one belonging to whoever is asking for it?
# ////
# //// The page checked NOTHING: `frappe.get_doc("Sales Order", …)` does not control
# //// read access, and the `frappe.get_all` calls that follow ignore
# //// permissions by design. An anonymous visitor who knew an order
# //// number could see the total, the items, the quantities, the prices, the method and
# //// the payment reference — and the customer's delivery address. Since
# //// the numbers are sequential (BC-2026-00347), the whole history of the
# //// shop could be enumerated. Found on 2026-08-24 on osiris.
# ////
# //// Checkout already enforces sign-in (`forceLogin` in checkout.js):
# //// the buyer who just paid is authenticated and retrieves their order.
def _visiteur_a_droit(commande) -> bool:
	if frappe.session.user == "Guest":
		return False
	# Staff see everything — they have access through the desk anyway.
	roles = frappe.get_roles()
	if "System Manager" in roles or "Website Manager" in roles:
		return True
	# //// This relies on ERPNext's mechanism, the same one `/order` already
	# //// uses (`erpnext.controllers.website_list_for_contact.has_website_permission`,
	# //// declared in its hooks for Sales Order, Quotation, Sales Invoice…).
	# //// It resolves the user's customers through their CONTACTS: comparing against
	# //// only the cart's `get_party()` would reject a legitimate contact of a
	# //// company that has several.
	try:
		return bool(frappe.has_website_permission(commande))
	except Exception:
		frappe.log_error("Webshop: droit de lecture d'une commande", frappe.get_traceback())
		return False

def get_context(context):
	context.body_class = "product-page"  # //// Neoffice — the shop's ground (webshop_ground.scss)
	# //// Neoffice — Frappe derives context.title from the route when
	# //// nobody sets it, and never translates it; themes print it as
	# //// the visible page heading, so the page read "thank-you".
	context.title = _("Thank You")
	context.json = json
	try:
		# Retrieve the sales order ID from the form dictionary
		sales_order_id = frappe.form_dict.get('sales_order')
		
		if not sales_order_id:
			frappe.local.flags.redirect_location = '/all-products'
			raise frappe.Redirect
		
		# Check if the Sales Order exists
		if not frappe.db.exists("Sales Order", sales_order_id):
			context.error_message = _("The specified order does not exist.")
			context.show_sidebar = False
			return context
		
		# Load Sales Order
		sales_order = frappe.get_doc("Sales Order", sales_order_id)

		# //// Neoffice — same message as for a non-existent order: saying
		# //// « it exists but not for you » would make enumeration possible
		# //// despite the safeguard.
		if not _visiteur_a_droit(sales_order):
			context.error_message = _("The specified order does not exist.")
			context.show_sidebar = False
			return context

		context.sales_order = sales_order
		context.doc = sales_order
		
		# Decorate the document with web information (images, etc.)
		context.doc = decorate_quotation_doc(context.doc)
		
		# Get linked Sales Invoice
		linked_docs = frappe.get_all(
			"Sales Invoice",
			filters={
				"docstatus": 1,
				"sales_order": sales_order_id
			},
			fields=["name", "outstanding_amount"],
			limit=1
		)
		
		if linked_docs:
			sales_invoice = linked_docs[0]
			
			# Get gift cards for this invoice
			if sales_invoice.outstanding_amount == 0:
				gift_cards = frappe.get_all(
					"Coupon Code",
					filters={
						"sales_invoice": sales_invoice.name
					},
					fields=["coupon_code", "gift_card_amount", "valid_from", "valid_upto"]
				)
				if gift_cards:
					context.gift_cards = gift_cards
					context.sales_invoice = sales_invoice
		
		# Retrieve payment information
		payment_entry = frappe.get_all(
			"Payment Entry",
			filters={
				"reference_name": sales_order_id,
				"docstatus": 1
			},
			fields=["name", "mode_of_payment", "reference_no", "reference_date", "paid_amount", "`tabPayment Entry`.creation"],
			order_by="`tabPayment Entry`.creation desc",
			limit=1
		)
		
		if payment_entry:
			context.payment_info = payment_entry[0]
			context.payment_info.payment_source = "Payment Entry"
			# Retrieve the translated name of the payment method
			mode_of_payment_doc = frappe.get_doc("Mode of Payment", context.payment_info.mode_of_payment)
			context.payment_info.mode_of_payment_label = _(mode_of_payment_doc.mode_of_payment)
		else:
			# If no Payment Entry, try Payment Request
			payment_request = frappe.get_all(
				"Payment Request",
				filters={
					"reference_doctype": "Sales Order",
					"reference_name": sales_order_id,
					"docstatus": 1,
					"status": "Paid"
				},
				fields=["name", "payment_gateway", "grand_total", "transaction_date", "`tabPayment Request`.creation"],
				order_by="`tabPayment Request`.creation desc",
				limit=1
			)
			
			if payment_request:
				context.payment_info = payment_request[0]
				context.payment_info.payment_source = "Payment Request"
				context.payment_info.mode_of_payment_label = _(payment_request[0].payment_gateway.split('-')[0].split()[0].strip())
				context.payment_info.reference_no = payment_request[0].name
				context.payment_info.reference_date = payment_request[0].transaction_date
				context.payment_info.paid_amount = payment_request[0].grand_total

		# Add delivery information if available
		shipping_address_name = sales_order.get("shipping_address_name")
		if shipping_address_name:
			context.shipping_address = frappe.get_doc("Address", shipping_address_name)
		
		context.show_sidebar = False
		return context
		
	except frappe.DoesNotExistError:
		context.error_message = _("The specified order does not exist.")
		context.show_sidebar = False
		return context
	except Exception as e:
		frappe.log_error(f"Error loading thank you page", e)
		context.error_message = _("An error occurred while loading the order.")
		context.show_sidebar = False
		return context
