import frappe
from frappe import _
from webshop.webshop.shopping_cart.cart import remove_loyalty_points
from erpnext.accounts.doctype.loyalty_program.loyalty_program import get_loyalty_program_details_with_points

def validate(doc, method=None):
    """Customise Sales Invoice on validation"""
    # Check whether the invoice is created from a Shopping Cart order
    if doc.items:
        sales_orders = list(set(d.sales_order for d in doc.items if d.sales_order))
        if sales_orders:
            for so_name in sales_orders:
                sales_order = frappe.get_doc("Sales Order", so_name)
                if hasattr(sales_order, "order_type") and sales_order.order_type == "Shopping Cart":
                    handle_loyalty_points(doc, sales_order)
                    break

def on_submit(doc, method=None):
    """Update the Loyalty Point Entry after the invoice has been submitted"""
    if doc.items and doc.loyalty_points:
        update_quotation_loyalty_points(doc)

def update_quotation_loyalty_points(invoice):
    """Update the loyalty points of the quotation with those of the invoice"""
    try:
        # Retrieve the linked order
        sales_orders = list(set(d.sales_order for d in invoice.items if d.sales_order))
        if not sales_orders:
            return

        # Retrieve the quotation linked to the order
        for so_name in sales_orders:
            sales_order = frappe.get_doc("Sales Order", so_name)
            if not hasattr(sales_order, "order_type") or sales_order.order_type != "Shopping Cart":
                continue

            # Retrieve the quotation linked to the order
            quotation_name = None
            if hasattr(sales_order, "quotation"):
                quotation_name = sales_order.quotation
            else:
                for item in sales_order.items:
                    if hasattr(item, "quotation") and item.quotation:
                        quotation_name = item.quotation
                        break
                    elif hasattr(item, "prevdoc_docname") and item.prevdoc_docname:
                        try:
                            doc = frappe.get_doc("Quotation", item.prevdoc_docname)
                            if doc:
                                quotation_name = item.prevdoc_docname
                                break
                        except frappe.DoesNotExistError:
                            continue

            if quotation_name:
                # Retrieve the Loyalty Point Entry for this invoice
                loyalty_entries = frappe.get_all(
                    "Loyalty Point Entry",
                    filters={
                        "invoice_type": "Sales Invoice",
                        "invoice": invoice.name,
                        "docstatus": 0
                    },
                    fields=["name"],
                    limit=1
                )

                if loyalty_entries:
                    # Update the quotation with the Loyalty Point Entry of the invoice
                    quotation = frappe.get_doc("Quotation", quotation_name)
                    if quotation.docstatus == 1:
                        frappe.db.set_value("Quotation", quotation_name, "loyalty_point_entry", loyalty_entries[0].name)
                        frappe.db.commit()

    except Exception as e:
        frappe.log_error("Error updating loyalty points in quotation", e)
        raise

def handle_loyalty_points(invoice, sales_order):
    """Handle loyalty points for a Shopping Cart order"""
    try:
        # Retrieve the quotation linked to the order
        if not sales_order.items:
            return
            
        # Retrieve the quotation linked to the order
        quotation_name = None
        if hasattr(sales_order, "items") and sales_order.items:
            
            # Check standard fields first
            if hasattr(sales_order, "quotation"):
                quotation_name = sales_order.quotation
            
            # Otherwise check items
            if not quotation_name:
                for item in sales_order.items:
                    if hasattr(item, "quotation") and item.quotation:
                        quotation_name = item.quotation
                        break
                    elif hasattr(item, "prevdoc_docname") and item.prevdoc_docname:
                        # Check if prevdoc_docname is a valid quotation    
                        try:
                            doc = frappe.get_doc("Quotation", item.prevdoc_docname)
                            if doc:
                                quotation_name = item.prevdoc_docname
                                break
                        except frappe.DoesNotExistError:
                            continue
        
        if not quotation_name:
            return
            
        # Retrieve the quotation
        quotation = frappe.get_doc("Quotation", quotation_name)
        
        # Check if the quotation has loyalty points
        if quotation.loyalty_points and quotation.loyalty_amount:
            # Configure loyalty points
            invoice.redeem_loyalty_points = 1
            invoice.loyalty_program = quotation.loyalty_program
            invoice.loyalty_points = quotation.loyalty_points
            invoice.loyalty_amount = quotation.loyalty_amount
            
            # Retrieve loyalty program details
            loyalty_program_details = frappe.get_doc("Loyalty Program", quotation.loyalty_program)
            invoice.loyalty_redemption_account = loyalty_program_details.expense_account
            invoice.loyalty_redemption_cost_center = loyalty_program_details.cost_center

            frappe.db.sql("""DELETE FROM `tabLoyalty Point Entry` WHERE name = %s""", quotation.loyalty_point_entry)
            frappe.db.commit()
            quotation.loyalty_point_entry = None
	
            # Remove loyalty points from quotation
            taxes_to_keep = []
            for tax in invoice.taxes:
                if not tax.is_loyalty_points_reduction:
                    taxes_to_keep.append(tax)
            invoice.taxes = taxes_to_keep

            # Let ERPNext handle the calculations and accounting entries
            invoice.run_method('set_missing_values')
            invoice.run_method('calculate_taxes_and_totals')
                        
    except Exception as e:
        frappe.log_error("Error processing loyalty points", e)
        raise
