import frappe
from frappe import _

no_cache = 1

def get_context(context):
    """Get CGV content from Webshop Settings"""
    
    # Get webshop settings
    webshop_settings = frappe.get_cached_doc("Webshop Settings")
    
    # Get CGV content if configured
    if webshop_settings.checkout_cgv:
        # Get the Terms and Conditions document
        cgv_doc = frappe.get_doc("Terms and Conditions", webshop_settings.checkout_cgv)
        
        context.update({
            "title": cgv_doc.title or _("Conditions Générales de Vente"),
            "cgv_title": cgv_doc.title,
            "cgv_content": cgv_doc.terms,
            "show_cgv": True
        })
    else:
        context.update({
            "title": _("Conditions Générales de Vente"),
            "cgv_title": _("Conditions Générales de Vente"),
            "cgv_content": None,
            "show_cgv": False
        })
    
    # Add webshop context
    context.webshop_settings = webshop_settings
    
    return context