# //// Neoffice — added file (no upstream equivalent).
# //// Coupon Code.gift_card_amount: a gift card has a face value, which an ERPNext coupon does not carry — it only knows a
# //// Pricing Rule (73119aae66, 2025-02-11 "feat: Add gift card amount field").
# //// The field used to be fetched from the Pricing Rule's discount at every save of the card. It is not any more: the cards
# //// the shop sells share one rule per amount, so a card spent rewrote the balance of its sisters (maintenance#3239). The
# //// balance is the card's own, and POS Next's patch gift_cards.the_balance_of_a_gift_card_is_its_own clears the fetch on
# //// the sites that still have it.
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

def execute():
    """Add gift_card_amount field to Coupon Code doctype"""
    
    # Check if the field already exists
    if frappe.db.exists('Custom Field', {'dt': 'Coupon Code', 'fieldname': 'gift_card_amount'}):
        return
    
    custom_field = {
        'fieldname': 'gift_card_amount',
        'label': 'Gift Card Amount',
        'fieldtype': 'Currency',
        'insert_after': 'pricing_rule',
        'read_only': 0,
        'translatable': 0,
        'depends_on': 'eval:doc.coupon_type=="Gift Card"',
        'in_list_view': 1,
        'in_standard_filter': 1
    }
    
    create_custom_field('Coupon Code', custom_field)
