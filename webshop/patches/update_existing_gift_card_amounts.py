import frappe

def execute():
    """Update gift card amounts for existing gift cards"""
    gift_cards = frappe.get_all(
        "Coupon Code",
        filters={"coupon_type": "Gift Card", "pricing_rule": ["!=", ""]},
        fields=["name", "pricing_rule"]
    )
    
    for gift_card in gift_cards:
        try:
            doc = frappe.get_doc("Coupon Code", gift_card.name)
            pricing_rule = frappe.get_doc("Pricing Rule", gift_card.pricing_rule)
            doc.gift_card_amount = pricing_rule.discount_amount
            doc.save(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(f"Error updating gift card amount for {gift_card.name}: {str(e)}")
