import frappe
from frappe import _
from frappe.utils import fmt_money
from erpnext.utilities.product import get_price

def get_carousel_items(item_group=None, only_promotions=False, limit=20, 
                       sort_by="modified", sort_order="desc", brand=None, 
                       exclude_items=None, search_term=None):
    """
    Helper function to get formatted products for the carousel.
    
    Args:
        item_group (str, optional): Filter by specific product group
        only_promotions (bool, optional): Display only promotional products
        limit (int, optional): Maximum number of articles to retrieve
        sort_by (str, optional): Field for sorting
        sort_order (str, optional): Sorting direction ('asc' or 'desc')
        brand (str, optional): Filter by brand
        exclude_items (list, optional): List of item codes to exclude
        search_term (str, optional): Search term
        
    Returns:
        list: Articles formatted for carousel display
    """
    # Function to create abbreviations
    def get_abbr(name):
        return ''.join([w[0].upper() for w in name.split()]) if name else ""
    
    # Build filters
    filters = {"published": 1}  # Only published articles
    
    # Add group filter if provided
    if item_group:
        filters["item_group"] = item_group
    
    # Add brand filter if provided
    if brand:
        filters["brand"] = brand
    
    # Exclude articles if necessary
    if exclude_items:
        filters["item_code"] = ["not in", exclude_items]
    
    # Add search term if provided
    if search_term:
        filters.update([
            [
                "Website Item",
                "item_name",
                "like",
                f"%{search_term}%"
            ]
        ])
    
    # Fields to retrieve
    fields = [
        "name", "web_item_name", "item_name", "item_code", 
        "website_image", "route", "item_group", "brand",
        "description", "has_variants"
    ]
    
    # Valider le champ de tri pour éviter des erreurs SQL
    valid_sort_fields = [
        "name", "modified", "creation", "item_name", "item_code", 
        "web_item_name", "ranking", "published"
    ]
    
    if sort_by not in valid_sort_fields:
        # Si le champ de tri demandé n'est pas valide, utiliser modified par défaut
        sort_by = "modified"
    
    # Get website items
    website_items = frappe.db.get_list(
        "Website Item",
        filters=filters,
        fields=fields,
        order_by=f"{sort_by} {sort_order}",
        limit=limit,
        ignore_permissions=True
    )
    
    # Process each item
    for item in website_items:
        # Add abbreviation
        item['abbr'] = get_abbr(item.get('web_item_name') or item.get('item_name') or '')
        
        # Get price details
        if item.get('item_code'):
            try:
                # Get necessary parameters
                settings = frappe.get_doc("Webshop Settings")
                selling_price_list = frappe.db.get_value("Selling Settings", None, "selling_price_list") or "Standard Selling"
                from webshop.webshop.shopping_cart.cart import get_party
                party = get_party()
                
                # Use standard get_price function to retrieve price details
                price_details = get_price(
                    item['item_code'],
                    selling_price_list,
                    settings.default_customer_group,
                    settings.company,
                    party=party
                )
                
                if price_details:
                    # Store formatted price details
                    item['price'] = price_details.get("price_list_rate")
                    item['currency'] = price_details.get("currency", "CHF")
                    item['formatted_price'] = price_details.get("formatted_price")
                    item['formatted_mrp'] = price_details.get("formatted_mrp")
                    
                    # Handle promotion information
                    if item['formatted_mrp']:
                        item['is_promotion'] = True
                        item['compare_at_price'] = price_details.get("mrp")
                        item['discount'] = price_details.get("formatted_discount_percent") or price_details.get("formatted_discount_rate")
                        item['discount_percent'] = price_details.get("discount_percent")
            except Exception as e:
                frappe.log_error(f"Error getting price for {item['item_code']}: {str(e)}", "Carousel Error")
    
    # Filter for promotions if requested
    if only_promotions:
        website_items = [item for item in website_items if item.get('is_promotion', False)]
    
    return website_items

def get_related_items(item_code, limit=4):
    """
    Get related items based on the same item group
    
    Args:
        item_code (str): Current item code
        limit (int): Maximum number of related items to return
        
    Returns:
        list: Related items for the carousel
    """
    try:
        # Get current item details
        current_item = frappe.get_doc("Website Item", {"item_code": item_code})
        
        # Get items from the same group, excluding the current item
        return get_carousel_items(
            item_group=current_item.item_group,
            limit=limit,
            exclude_items=[item_code]
        )
    except Exception as e:
        frappe.log_error( "Carousel Error", f"Error getting related items for {item_code}: {str(e)}")
        return []

def render_product_carousel(carousel_item_group=None, only_promotions=False, limit=20, 
                            sort_by="modified", sort_order="desc", carousel_title=None,
                            brand=None, carousel_id=None, context=None):
    """
    Render a product carousel with specified filters
    
    Args:
        carousel_item_group (str, optional): Filter by specific product group
        only_promotions (bool, optional): Display only promotional products
        limit (int, optional): Maximum number of articles to retrieve
        sort_by (str, optional): Field for sorting
        sort_order (str, optional): Sorting direction ('asc' or 'desc')
        carousel_title (str, optional): Title for the carousel
        brand (str, optional): Filter by brand
        carousel_id (str, optional): Custom ID for the carousel
        context (dict, optional): Jinja template context

    Returns:
        str: HTML rendered for the carousel
    """
    # Get carousel items
    carousel_items = get_carousel_items(
        item_group=carousel_item_group,
        only_promotions=only_promotions,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
        brand=brand
    )
    
    # Generate a unique ID if not provided
    if not carousel_id:
        import uuid
        carousel_id = f"carousel-{str(uuid.uuid4())[:8]}"
    
    # Create or get context for the carousel
    if context is None:
        try:
            # Try to get the current context from Frappe
            context = frappe._dict(frappe.get_hooks("context") or {})
        except:
            # If failure, create an empty context
            context = frappe._dict({})
    else:
        # If a context is provided, copy it to avoid modifying the original
        # We make a shallow copy to avoid errors with non-copyable objects
        try:
            context = frappe._dict({k: v for k, v in context.items() if not k.startswith('_')})
        except:
            # If failure, create a new context
            context = frappe._dict({})
    
    # Update context with carousel items
    context.update({
        "website_items": carousel_items,  # Use website_items for compatibility with existing template
        "carousel_title": carousel_title or _("Produits en vedette"),
        "carousel_id": carousel_id
    })
    
    # Render the template
    return frappe.render_template("webshop/templates/includes/product_carousel.html", context)