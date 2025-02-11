import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

def execute():
    """Add gift_card_amount field to Coupon Code doctype"""
    
    # Vérifier si le champ existe déjà
    if frappe.db.exists('Custom Field', {'dt': 'Coupon Code', 'fieldname': 'gift_card_amount'}):
        return
    
    custom_field = {
        'fieldname': 'gift_card_amount',
        'label': 'Gift Card Amount',
        'fieldtype': 'Currency',
        'insert_after': 'pricing_rule',
        'fetch_from': 'pricing_rule.discount_amount',
        'fetch_if_empty': 1,
        'read_only': 0,
        'translatable': 0,
        'depends_on': 'eval:doc.coupon_type=="Gift Card"',
        'in_list_view': 1,
        'in_standard_filter': 1
    }
    
    create_custom_field('Coupon Code', custom_field)
