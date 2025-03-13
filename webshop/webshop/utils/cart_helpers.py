import frappe
from frappe import _
import json
from frappe.utils import cint, cstr, flt, get_fullname
from webshop.webshop.shopping_cart.cart import is_gift_card_item, get_cart_quotation

def get_cart_data():
    """
    Function to get cart data.
    This function is exposed via Jinja templates in Builder.
    """
    # Function to create abbreviations
    def get_abbr(name):
        return ''.join([w[0].upper() for w in name.split()]) if name else ""
    
    # List of fields to include, WITHOUT description which contains HTML
    SAFE_FIELDS = ['website_image', 'thumbnail', 'route', 'brand', 'web_item_name', 'stock_uom', 'weight_per_unit', 'weight_uom']
    
    # Cart information - initialize with default values
    cart_items = []
    cart_total = 0
    cart_items_count = 0
    cart_currency = "" 
    cart_info_fields = {}
    tax_info = []
    
    try:
        # Get active quotation (cart) using dedicated function
        cart_info = get_cart_quotation()
               
        # Check if a document was found
        if cart_info and cart_info.get('doc'):
            quotation = cart_info.get('doc')
            cart_total = quotation.grand_total
            cart_items_count = quotation.total_qty or 0
            
            # Get general cart information
            cart_info_fields = {}
            for field in ['currency', 'conversion_rate', 'price_list_currency', 'taxes_and_charges',
                        'total', 'base_total', 'net_total', 'base_net_total', 'total_taxes_and_charges',
                        'discount_amount', 'coupon_code', 'grand_total', 'rounded_total']:
                if hasattr(quotation, field) and getattr(quotation, field) is not None:
                    cart_info_fields[field] = getattr(quotation, field)
            
            # Ensure we have at least the currency
            if 'currency' in cart_info_fields:
                cart_currency = cart_info_fields['currency']
            
            # Get detailed tax information
            tax_info = []
            if hasattr(quotation, 'taxes') and quotation.taxes:
                for tax in quotation.taxes:
                    tax_dict = {
                        'description': tax.description,
                        'tax_amount': tax.tax_amount,
                        'account_head': tax.account_head if hasattr(tax, 'account_head') else None,
                        'rate': tax.rate if hasattr(tax, 'rate') else None
                    }
                    # Add additional information if available
                    for field in ['charge_type', 'included_in_print_rate', 'included_in_paid_amount']:
                        if hasattr(tax, field):
                            tax_dict[field] = getattr(tax, field)
                    
                    tax_info.append(tax_dict)
            
            # Process cart items
            for item in quotation.get('items', []):
                # Create a dictionary with base information
                item_dict = {
                    "item_code": item.item_code,
                    "item_name": item.item_name,
                    "qty": item.qty,
                    "rate": item.rate,
                    "amount": item.amount,
                    "abbr": get_abbr(item.item_name),
                    "stock_qty": item.stock_qty if hasattr(item, 'stock_qty') else item.qty,
                    "uom": item.uom if hasattr(item, 'uom') else '',
                    "is_gift_card": is_gift_card_item(item.item_code)
                }
                
                # Add only safe fields (no HTML)
                for field in SAFE_FIELDS:
                    if hasattr(item, field) and getattr(item, field):
                        item_dict[field] = getattr(item, field)
                
                # Add additional information if available
                if hasattr(item, 'price_list_rate'):
                    item_dict['price_list_rate'] = item.price_list_rate
                
                if hasattr(item, 'discount_percentage'):
                    item_dict['discount_percentage'] = item.discount_percentage
                
                # Add image path if available via web item metadata
                if not item_dict.get('website_image') and not item_dict.get('thumbnail'):
                    web_item = frappe.db.get_value('Website Item', 
                                                {'item_code': item.item_code}, 
                                                ['website_image', 'thumbnail', 'image'], as_dict=1)
                    if web_item:
                        if web_item.website_image:
                            item_dict['website_image'] = web_item.website_image
                        if web_item.thumbnail:
                            item_dict['thumbnail'] = web_item.thumbnail
                        # Utiliser le champ image si disponible et si les autres images ne sont pas présentes
                        elif web_item.image and not item_dict.get('website_image'):
                            item_dict['website_image'] = web_item.image
                    else:
                        # Si aucun Website Item n'est trouvé, essayer de récupérer l'image depuis Item
                        item_img = frappe.db.get_value('Item', 
                                                    item.item_code, 
                                                    ['image'], as_dict=1)
                        if item_img and item_img.image:
                            item_dict['website_image'] = item_img.image
                
                # Add brand metadata if available
                if not item_dict.get('brand'):
                    brand = frappe.db.get_value('Item', item.item_code, 'brand')
                    if brand:
                        item_dict['brand'] = brand
                
                cart_items.append(item_dict)
    
    except Exception as e:
        frappe.log_error("Cart Error", f"Error while getting cart data: {str(e)}")
    
    # Return cart data
    return {
        "cart_items": cart_items,
        "cart_total": cart_total,
        "cart_items_count": cart_items_count,
        "currency": cart_currency,
        "cart_info": cart_info_fields,
        "tax_info": tax_info
    }

def format_cart_response(cart_data):
    """
    Format cart data for consistent AJAX responses.
    This function can be used as middleware to normalize responses.
    """
    try:
        response = {
            "items": [],
            "total": 0,
            "currency": "",
            "total_qty": 0,
            "taxes": []
        }
        
        if not cart_data:
            return response
        
        # Process quotation or document
        doc = None
        if isinstance(cart_data, dict):
            if 'doc' in cart_data:
                doc = cart_data['doc']
            elif 'items' in cart_data:
                response["items"] = cart_data['items']
                doc = cart_data
        
        if doc:
            # Extract basic information
            response["total"] = doc.grand_total if hasattr(doc, 'grand_total') else doc.get('grand_total', 0)
            response["currency"] = doc.currency if hasattr(doc, 'currency') else doc.get('currency', '')
            response["total_qty"] = doc.total_qty if hasattr(doc, 'total_qty') else doc.get('total_qty', 0)
            
            # Extract other useful information
            for field in ['net_total', 'base_total', 'total_taxes_and_charges', 'discount_amount']:
                if hasattr(doc, field):
                    response[field] = getattr(doc, field)
                elif isinstance(doc, dict) and field in doc:
                    response[field] = doc[field]
            
            # Extract taxes
            taxes = []
            if hasattr(doc, 'taxes') and doc.taxes:
                for tax in doc.taxes:
                    tax_dict = {
                        'description': tax.description,
                        'tax_amount': tax.tax_amount
                    }
                    if hasattr(tax, 'rate'):
                        tax_dict['rate'] = tax.rate
                    taxes.append(tax_dict)
            elif 'taxes' in doc and isinstance(doc['taxes'], list):
                taxes = doc['taxes']
            
            response["taxes"] = taxes
            
            # Extract items
            if hasattr(doc, 'items') and not response["items"]:
                items = []
                for item in doc.items:
                    item_dict = {
                        "item_code": item.item_code,
                        "item_name": item.item_name,
                        "qty": item.qty,
                        "rate": item.rate,
                        "amount": item.amount
                    }
                    items.append(item_dict)
                response["items"] = items
        
        return response
    
    except Exception as e:
        frappe.log_error( "Cart Error", f"Error formatting cart data: {str(e)}")
        return {
            "items": [],
            "total": 0,
            "currency": "",
            "total_qty": 0,
            "taxes": [],
            "error": str(e)
        }

@frappe.whitelist(allow_guest=True)
def update_cart(item_code, qty, additional_notes=None, with_items=False, add_qty=False, price_list_rate=None, gift_card_data=None):
    """
    Improved version of the update_cart function that handles errors better and normalizes responses.
    
    Args:
        item_code (str): Code of the item to update
        qty (int): New quantity (0 to remove the item)
        additional_notes (str, optional): Additional notes for the item
        with_items (bool, optional): If True, returns HTML of items, otherwise just the quotation name
        add_qty (bool, optional): If True, adds the specified quantity to the existing quantity
        price_list_rate (float, optional): Price to apply (only for gift cards)
        gift_card_data (str, optional): JSON data for gift cards
        
    Returns:
        dict: Cart data updated or quotation name
    """
    try:
        # Convert gift_card_data from JSON if necessary
        if gift_card_data and isinstance(gift_card_data, str):
            try:
                gift_card_data = frappe.parse_json(gift_card_data)
            except Exception as e:
                frappe.log_error(f"Error parsing JSON", e)
                gift_card_data = None
        
        # Convert qty to integer
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            frappe.throw(_("Quantity must be a valid number"))

        if isinstance(add_qty, str):
            add_qty = add_qty.lower() == 'true'
        
        # Convert price_list_rate to float if provided
        if price_list_rate:
            try:
                price_list_rate = flt(price_list_rate)
            except (TypeError, ValueError):
                price_list_rate = None
        
        # Convert with_items to boolean if it's a string
        if isinstance(with_items, str):
            with_items = with_items.lower() == 'true'
        
        # Use the original update_cart function but handle its response
        from webshop.webshop.shopping_cart.cart import update_cart as original_update_cart
        response = original_update_cart(
            item_code=item_code,
            qty=qty,
            additional_notes=additional_notes,
            with_items=with_items,
            add_qty=add_qty,
            price_list_rate=price_list_rate,
            gift_card_data=gift_card_data
        )
        
        # Normalize and enhance the response
        enhanced_response = prepare_cart_response(response, with_items)
        return enhanced_response
        
    except Exception as e:
        frappe.log_error("Cart Error", f"Error in update_cart: {str(e)}")
        return {
            "error": str(e),
            "success": False,
            "items": [],
            "total_qty": 0,
            "grand_total": 0,
            "currency": ""
        }

def prepare_cart_response(response, with_items=False):
    """
    Prepare a consistent response for the cart API.
    
    Args:
        response: Response from the original update_cart function
        with_items (bool): If True, includes HTML templates
        
    Returns:
        dict: Response formatted for the API
    """
    try:
        # If the response is None, return an empty structure
        if response is None:
            return {
                "name": None,
                "grand_total": 0,
                "total_qty": 0,
                "items": [],
                "currency": "",
                "success": False
            }
        
        # If the response contains just the quotation name
        if isinstance(response, dict) and "name" in response and len(response) == 1:
            # Get the quotation to have all the information
            try:
                quotation = frappe.get_doc("Quotation", response["name"])
                return format_quotation_response(quotation, with_items)
            except Exception as e:
                frappe.log_error("Cart Error", f"Error during quotation retrieval: {str(e)}")
                return {
                    "name": response["name"],
                    "success": True,
                    "items": [],
                    "total_qty": 0,
                    "grand_total": 0,
                    "currency": ""
                }
        
        # If the response contains HTML elements for with_items=True
        if isinstance(response, dict) and "items" in response and isinstance(response["items"], str) and with_items:
            # It's probably HTML, return it as is
            return response
        
        # If the response contains a document 'doc'
        if isinstance(response, dict) and "doc" in response and response["doc"]:
            return format_quotation_response(response["doc"], with_items)
        
        # Fallback: return the response as is
        return response
        
    except Exception as e:
        frappe.log_error("Cart Error", f"Error in prepare_cart_response: {str(e)}")
        return {
            "error": str(e),
            "success": False,
            "items": [],
            "total_qty": 0,
            "grand_total": 0,
            "currency": ""
        }

def format_quotation_response(quotation, with_items=False):
    """
    Format quotation data for the cart API.
    
    Args:
        quotation: Document Quotation
        with_items (bool): If True, includes HTML templates
        
    Returns:
        dict: Formatted quotation data
    """
    try:
        if not quotation:
            return {
                "name": None,
                "grand_total": 0,
                "total_qty": 0,
                "items": [],
                "currency": "",
                "success": False
            }
        
        # Prepare a base structure for the response
        response = {
            "name": quotation.name,
            "grand_total": quotation.grand_total,
            "total_qty": quotation.total_qty,
            "currency": quotation.currency,
            "success": True
        }
        
        # Add useful fields
        for field in ['net_total', 'base_total', 'total_taxes_and_charges', 'discount_amount']:
            if hasattr(quotation, field) and getattr(quotation, field) is not None:
                response[field] = getattr(quotation, field)
        
        # Add taxes
        response["taxes"] = []
        if hasattr(quotation, 'taxes') and quotation.taxes:
            for tax in quotation.taxes:
                tax_dict = {
                    'description': tax.description,
                    'tax_amount': tax.tax_amount
                }
                if hasattr(tax, 'rate'):
                    tax_dict['rate'] = tax.rate
                response["taxes"].append(tax_dict)
                
        # If with_items is True, add HTML templates
        if with_items:
            context = get_cart_quotation(quotation)
            response.update({
                "items": frappe.render_template(
                    "templates/includes/cart/cart_items.html", context
                ),
                "total": frappe.render_template(
                    "templates/includes/cart/cart_items_total.html", context
                ),
                "taxes_and_totals": frappe.render_template(
                    "templates/includes/cart/cart_payment_summary.html", context
                ),
            })
        else:
            # For requests without HTML, include item details
            response["items"] = []
            for item in quotation.items:
                item_dict = {
                    "item_code": item.item_code,
                    "item_name": item.item_name,
                    "qty": item.qty,
                    "rate": item.rate,
                    "amount": item.amount
                }
                # Add other useful properties
                for field in ['website_image', 'thumbnail', 'brand', 'route']:
                    if hasattr(item, field) and getattr(item, field):
                        item_dict[field] = getattr(item, field)
                
                # If the images are not available in the item, retrieve them from Website Item
                if not item_dict.get('website_image') or not item_dict.get('thumbnail'):
                    web_item = frappe.db.get_value('Website Item',
                                                {'item_code': item.item_code},
                                                ['website_image', 'thumbnail', 'image'],
                                                as_dict=1)
                    if web_item:
                        if web_item.website_image:
                            item_dict['website_image'] = web_item.website_image
                        if web_item.thumbnail:
                            item_dict['thumbnail'] = web_item.thumbnail
                        # Use the image field if available and if other images are not present
                        elif web_item.image and not item_dict.get('website_image'):
                            item_dict['website_image'] = web_item.image
                
                # Add the product route (URL)
                if not item_dict.get('route'):
                    item_dict['route'] = get_product_route(item.item_code)
                
                # Add additional data for gift cards if necessary
                if hasattr(item, 'gift_card_data') and item.gift_card_data:
                    try:
                        if isinstance(item.gift_card_data, str):
                            item_dict["gift_card_data"] = frappe.parse_json(item.gift_card_data)
                        else:
                            item_dict["gift_card_data"] = item.gift_card_data
                    except Exception:
                        pass
                
                response["items"].append(item_dict)
        
        return response
        
    except Exception as e:
        frappe.log_error(f"Cart Error: {str(e)}", "Cart Error")
        return {
            "name": quotation.name if quotation else None,
            "error": str(e),
            "success": False,
            "items": [],
            "total_qty": 0,
            "grand_total": 0,
            "currency": ""
        }

def get_product_route(item_code):
    """Retrieve the product route (URL) from its code.
    
    Args:
        item_code (str): Item code
        
    Returns:
        str: Product URL or None if not found
    """
    # Try first to find in Website Item
    route = frappe.db.get_value('Website Item', {'item_code': item_code}, 'route')
    
    if not route:
        # Try to build the route from web_item_name or item_name
        item_name = frappe.db.get_value('Item', item_code, 'item_name')
        if item_name:
            # Convert the name to slug for the URL
            import re
            from frappe.utils import cstr
            slug = re.sub(r'[^\w\s-]', '', cstr(item_name).lower())
            slug = re.sub(r'[-\s]+', '-', slug).strip('-_')
            route = f"/all-products/{slug}"
    
    return route

def cart_info_for_template():
    """
    This function can be used in Jinja templates to retrieve cart information
    without going through get_cart_data which may cause errors.
    
    Returns:
        dict: Cart information formatted for display
    """
    try:
        # Function to create abbreviations
        def get_abbr(name):
            return ''.join([w[0].upper() for w in name.split()]) if name else ""
        
        # List of fields to include, WITHOUT description which contains HTML
        SAFE_FIELDS = ['website_image', 'thumbnail', 'route', 'brand', 'web_item_name']
        
        # Cart information - initialize with default values
        cart_items = []
        cart_total = 0
        cart_items_count = 0
        cart_currency = ""
        cart_info_fields = {}
        tax_info = []
        
        # Retrieve the active quotation (cart) using the dedicated function
        try:
            cart_info = get_cart_quotation()
            
            # Check if a document was found
            if cart_info and cart_info.get('doc'):
                quotation = cart_info.get('doc')
                cart_total = quotation.grand_total or 0
                cart_items_count = quotation.total_qty or 0
                
                # Retrieve general cart information
                cart_info_fields = {}
                for field in ['currency', 'conversion_rate', 'price_list_currency', 'taxes_and_charges',
                            'total', 'base_total', 'net_total', 'base_net_total', 'total_taxes_and_charges',
                            'discount_amount', 'coupon_code']:
                    if hasattr(quotation, field) and getattr(quotation, field) is not None:
                        cart_info_fields[field] = getattr(quotation, field)
                
                # Ensure we have at least the currency
                if 'currency' in cart_info_fields:
                    cart_currency = cart_info_fields['currency']
                
                # Get tax information
                tax_info = []
                if hasattr(quotation, 'taxes') and quotation.taxes:
                    for tax in quotation.taxes:
                        tax_info.append({
                            'description': tax.description,
                            'tax_amount': tax.tax_amount,
                            'rate': tax.rate if hasattr(tax, 'rate') else None
                        })
                
                # Process cart items
                for item in quotation.get('items', []):
                    # Create a dictionary with basic information
                    item_dict = {
                        "item_code": item.item_code,
                        "item_name": item.item_name,
                        "qty": item.qty,
                        "rate": item.rate,
                        "amount": item.amount,
                        "abbr": get_abbr(item.item_name),
                    }
                    
                    # Add only safe fields (no HTML)
                    for field in SAFE_FIELDS:
                        if hasattr(item, field) and getattr(item, field):
                            item_dict[field] = getattr(item, field)
                    
                    cart_items.append(item_dict)
        except Exception as e:
            frappe.log_error("Cart Info Error", f"Error during get_cart_quotation: {str(e)}")
        
        # Return cart data
        return {
            "cart_items": cart_items,
            "cart_total": cart_total,
            "cart_items_count": cart_items_count,
            "currency": cart_currency,
            "cart_info": cart_info_fields,
            "tax_info": tax_info
        }
    except Exception as e:
        frappe.log_error("Cart Info Error", f"Global error in cart_info_for_template: {str(e)}")
        return {
            "cart_items": [],
            "cart_total": 0,
            "cart_items_count": 0,
            "currency": "",
            "cart_info": {},
            "tax_info": []
        }