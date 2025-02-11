import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice as OriginalSalesInvoice

class SalesInvoice(OriginalSalesInvoice):
    def validate_advance_entries(self):
        """Override to avoid advance message for Shopping Cart payments"""
        
        # Check if invoice is linked to a Shopping Cart Sales Order
        sales_orders = list(set(d.sales_order for d in self.items if d.sales_order))
        if sales_orders:
            for so_name in sales_orders:
                sales_order = frappe.get_doc("Sales Order", so_name)
                if hasattr(sales_order, "order_type") and sales_order.order_type == "Shopping Cart":
                    return
        
        # If it's not a Shopping Cart order, use standard validation
        super().validate_advance_entries()
