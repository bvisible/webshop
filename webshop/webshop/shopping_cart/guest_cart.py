import frappe
from frappe import _
import json
import uuid
from frappe.utils import now_datetime, add_days, cstr, flt
from webshop.webshop.shopping_cart.cart import guess_territory, set_price_list_and_rate, set_taxes, _apply_shipping_rule, get_party, apply_cart_settings, decorate_quotation_doc, get_cart_quotation, _get_cart_quotation, is_gift_card_item
from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings

@frappe.whitelist(allow_guest=True)
def get_guest_session_id():
    """Get or create a guest session ID"""
    guest_session_id = frappe.request.cookies.get('guest_session_id')
    
    if not guest_session_id:
        guest_session_id = str(uuid.uuid4())
        # Cookie expires in 7 days
        expires = add_days(now_datetime(), 7)
        
        # Use Frappe's method to set a cookie
        frappe.local.cookie_manager.set_cookie(
            'guest_session_id',
            guest_session_id,
            expires=expires.strftime('%a, %d-%b-%Y %H:%M:%S GMT'),
            httponly=True,
            secure=True
        )
    
    return guest_session_id

@frappe.whitelist(allow_guest=True)
def create_guest_quotation(items=None):
    """Create or update a quotation for a guest"""
    
    # If items is a JSON string, convert it to a list
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except json.JSONDecodeError:
            frappe.throw(_("Invalid items format"))

    # Get the guest_session_id from the cookie
    guest_session_id = frappe.request.cookies.get('guest_session_id')
    
    if not guest_session_id:
        guest_session_id = str(uuid.uuid4())

    # Check for an existing quotation for this guest_session_id
    existing_quotation = frappe.db.get_value(
        'Quotation',
        {
            'guest_session_id': guest_session_id,
            'docstatus': 0,
            'status': 'Draft'
        },
        'name'
    )

    # If a quotation exists and we don't have any items, return it
    if existing_quotation and not items:
        return {
            'success': True,
            'quotation_id': existing_quotation,
            'guest_session_id': guest_session_id
        }

    # If no quotation and no items, return None
    if not items:
        return None

    # Get required parameters
    company = frappe.db.get_single_value("Webshop Settings", "company")
    settings = frappe.get_doc("Webshop Settings", "Webshop Settings")
    guest_customer = settings.guest_customer
    # Guess the territory
    territory = guess_territory()

    if existing_quotation:
        quotation = frappe.get_doc("Quotation", existing_quotation)
        quotation.items = []
        quotation.territory = territory
    else:
        quotation = frappe.get_doc({
            "doctype": "Quotation",
            "naming_series": settings.quotation_series or "QTN-CART-",
            "quotation_to": "Customer",
            "party_name": guest_customer,
            "customer_name": guest_customer,
            "company": company,
            "territory": territory,
            "order_type": "Shopping Cart",
            "status": "Draft",
            "docstatus": 0,
            "__islocal": 1,
            "guest_session_id": guest_session_id
        })

    # Add items to the quotation
    for item in items:
        item_dict = {
            "doctype": "Quotation Item",
            "item_code": item.get("item_code"),
            "qty": item.get("qty", 1),
            "warehouse": frappe.get_cached_value(
                "Website Item", 
                {"item_code": item.get("item_code")}, 
                "website_warehouse"
            )
        }
        
        # Check if it's a gift card item
        if is_gift_card_item(item.get("item_code")):
            if item.get("rate"):
                item_dict["rate"] = item.get("rate")
            if item.get("price_list_rate"):
                item_dict["price_list_rate"] = item.get("price_list_rate")
            if item.get("gift_card_data"):
                item_dict["gift_card_data"] = item.get("gift_card_data")
            
        quotation.append("items", item_dict)

    apply_cart_settings(guest_customer, quotation)

    # Save the quotation
    quotation.flags.ignore_permissions = True
    quotation.flags.ignore_mandatory = True
    quotation.save(ignore_permissions=True)

    # Set the cookie guest_session_id
    if hasattr(frappe.local, 'cookie_manager'):
        frappe.local.cookie_manager.set_cookie('guest_session_id', guest_session_id)
        # Set quotation name in cookies
        frappe.local.cookie_manager.set_cookie('quotation_name', quotation.name)

    result = {
        'success': True,
        'quotation_id': quotation.name,
        'guest_session_id': guest_session_id,
        'items': items
    }
    return result

@frappe.whitelist(allow_guest=True)
def test_guest_quotation(item_code=None):
    """
    Test endpoint to create a guest quotation
    
    Args:
        item_code (str, optional): Code of the item to add to the cart
    
    Returns:
        dict: Information about the created quotation
    """
    try:
        
        # Check parameters
        settings = frappe.get_doc('Webshop Settings')
        if not settings.enable_guest_cart:
            return {"success": False, "message": "Guest cart is not enabled"}
        
        if not settings.guest_customer:
            return {"success": False, "message": "Guest customer not configured"}
        
        # Create a test quotation
        if item_code:
            items = [{"item_code": item_code, "qty": 1}]
            quotation = create_guest_quotation(items)
            return {
                "success": True,
                "message": "Quotation created successfully",
                "quotation": quotation
            }
        else:
            return {"success": False, "message": "Item code required"}
    except Exception as e:
        frappe.log_error(f"TEST ERROR: {str(e)}\nTraceback: {frappe.get_traceback()}")
        return {"success": False, "message": str(e)}

def check_and_merge_guest_cart():
    """
    Check if a guest cart merge is necessary and possible.
    This function can be called at any time, it will check the necessary conditions.
    """
    try:        
        # If user is Guest, no need to merge
        if frappe.session.user == 'Guest':
            return

        # Check for a guest_session_id in the cookies
        if not hasattr(frappe, 'request') or not frappe.request:
            return
            
        guest_session_id = frappe.request.cookies.get('guest_session_id')
        
        if not guest_session_id:
            return

        # Get customer for logged in user
        try:
            customer = get_party()
        except Exception as e:
            frappe.log_error("DEBUG: Error getting customer", e)
            return
        
        if not customer:
            return

        # Check if customer is guest customer
        try:
            settings = frappe.get_cached_doc("Webshop Settings")
        except Exception as e:
            frappe.log_error("DEBUG: Error getting settings", e)
            return
            
        if customer.name == settings.guest_customer:
            return

        # Check if user already has an active quotation
        try:
            guest_quotation = frappe.get_all(
                'Quotation',
                filters={
                    'guest_session_id': guest_session_id,
                    'party_name': settings.guest_customer,
                    'docstatus': 0,
                    'order_type': 'Shopping Cart'
                },
                limit=1
            )
        except Exception as e:
            frappe.log_error("DEBUG: Error getting guest quotation", e)
            return

        if not guest_quotation:
            if hasattr(frappe.local, "cookie_manager"):
                frappe.local.cookie_manager.delete_cookie("guest_session_id")
            return

        # Get the complete guest quotation
        try:
            guest_doc = frappe.get_doc('Quotation', guest_quotation[0].name)
        except Exception as e:
            frappe.log_error("DEBUG: Error getting guest quotation", e)
            return

        # Check if user already has an active quotation
        try:
            user_quotation = frappe.get_all(
                "Quotation",
                fields=["name"],
                filters={
                    "party_name": customer.name,
                    "contact_email": frappe.session.user,
                    "order_type": "Shopping Cart",
                    "docstatus": 0,
                },
                order_by="modified desc",
                limit_page_length=1,
            )
            
            if user_quotation:
                user_doc = frappe.get_doc("Quotation", user_quotation[0].name)
            else:
                # Create a new quotation
                company = settings.company
                user_doc = frappe.get_doc({
                    "doctype": "Quotation",
                    "naming_series": settings.quotation_series or "QTN-CART-",
                    "quotation_to": customer.doctype,
                    "company": company,
                    "order_type": "Shopping Cart",
                    "status": "Draft",
                    "docstatus": 0,
                    "__islocal": 1,
                    "party_name": customer.name,
                })
                
                user_doc.contact_person = frappe.db.get_value("Contact", {"email_id": frappe.session.user})
                user_doc.contact_email = frappe.session.user
                
                user_doc.flags.ignore_permissions = True
                user_doc.run_method("set_missing_values")
                apply_cart_settings(customer, user_doc)
                            
            # Merge items
            if guest_doc.items:
                existing_items = {item.item_code: item for item in user_doc.items}
                for item in guest_doc.items:
                    if item.item_code in existing_items:
                        existing_items[item.item_code].qty += item.qty
                    else:
                        user_doc.append('items', {
                            'item_code': item.item_code,
                            'qty': item.qty,
                            'rate': item.rate
                        })
            
            user_doc.flags.ignore_permissions = True
            user_doc.save(ignore_permissions=True)
            frappe.db.commit()
            
            # Delete the guest quotation
            guest_doc.flags.ignore_permissions = True
            guest_doc.delete(ignore_permissions=True)
            frappe.db.commit()
            
            # Delete the cookie guest_session_id
            if hasattr(frappe.local, "cookie_manager"):
                frappe.local.cookie_manager.delete_cookie("guest_session_id")
            
            frappe.msgprint(
                _('Your guest cart has been assigned to your account'),
                alert=True
            )
            
        except Exception as e:
            frappe.log_error("Error merging quotations", e)
            return

    except Exception as e:
        frappe.log_error(f"Error merging guest cart", e)
        return
