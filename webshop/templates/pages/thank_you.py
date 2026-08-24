import frappe
import json
from frappe import _
from webshop.webshop.shopping_cart.cart import decorate_quotation_doc, get_party

no_cache = 1


#//// Neoffice — cette commande est-elle celle de qui la demande ?
#////
#//// La page ne vérifiait RIEN : `frappe.get_doc("Sales Order", …)` ne contrôle
#//// pas la lecture, et les `frappe.get_all` qui suivent ignorent les
#//// permissions par construction. Un visiteur anonyme qui connaissait un
#//// numéro voyait le total, les articles, les quantités, les prix, le moyen et
#//// la référence de paiement — et l'adresse de livraison du client. Les
#//// numéros étant séquentiels (BC-2026-00347), tout l'historique de la
#//// boutique s'énumérait. Constaté le 2026-08-24 sur osiris.
#////
#//// Le checkout impose déjà la connexion (`forceLogin` dans checkout.js) :
#//// l'acheteur qui vient de payer est authentifié et retrouve sa commande.
def _visiteur_a_droit(commande) -> bool:
	if frappe.session.user == "Guest":
		return False
	roles = frappe.get_roles()
	if "System Manager" in roles or "Website Manager" in roles:
		return True
	try:
		moi = get_party()
	except Exception:
		moi = None
	return bool(moi) and commande.customer == moi.name

def get_context(context):
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

		#//// Neoffice — même message que pour une commande inexistante : dire
		#//// « elle existe mais pas pour vous » rendrait l'énumération possible
		#//// malgré le garde-fou.
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
