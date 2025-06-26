import frappe
from frappe import _
from frappe.utils import fmt_money
from erpnext.utilities.product import get_price

def _get_abbr(name):
    """Create abbreviation from name"""
    return ''.join([w[0].upper() for w in (name or '').split()]) if name else ""

def _format_carousel_item(item):
    """Format a single item for carousel display"""
    formatted_item = {
        "name": item.get("name"),
        "web_item_name": item.get("web_item_name"),
        "item_name": item.get("item_name"),
        "item_code": item.get("item_code"),
        "website_image": item.get("website_image"),
        "route": item.get("route"),
        "item_group": item.get("item_group"),
        "brand": item.get("brand"),
        "description": item.get("short_description") or item.get("web_long_description", ""),
        "has_variants": item.get("has_variants"),
        "abbr": _get_abbr(item.get("web_item_name") or item.get("item_name"))
    }
    
    # Add price information if available
    if item.get("formatted_price"):
        formatted_item.update({
            "price": item.get("price_list_rate"),
            "currency": item.get("currency"),
            "formatted_price": item.get("formatted_price")
        })
        
        # Add discount information if available
        if item.get("formatted_mrp"):
            formatted_item.update({
                "formatted_mrp": item.get("formatted_mrp"),
                "compare_at_price": item.get("compare_at_price"),
                "discount": item.get("discount"),
                "discount_percent": item.get("discount_percent", 0),
                "is_promotion": True
            })
    elif item.get("price_list_rate"):
        # For items from direct SQL query
        formatted_item.update({
            "price": item.get("price_list_rate"),
            "currency": item.get("currency", "CHF"),
            "formatted_price": fmt_money(item.get("price_list_rate"), currency=item.get("currency", "CHF"))
        })
    
    return formatted_item

def _get_new_arrivals_optimized(limit, item_group=None, exclude_items=None):
    """Optimized query for new arrivals carousel"""
    # Get settings
    settings = frappe.get_cached_doc("Webshop Settings")
    if not settings.enabled:
        return []
    
    price_list = settings.price_list or frappe.db.get_value("Selling Settings", None, "selling_price_list") or "Standard Selling"
    currency = frappe.get_cached_value("Price List", price_list, "currency") or "CHF"
    
    # Build conditions
    conditions = ["wi.published = 1"]
    params = {
        "price_list": price_list,
        "limit": limit + 10  # Get a few extra in case of filtering
    }
    
    if item_group:
        conditions.append("wi.item_group = %(item_group)s")
        params["item_group"] = item_group
    
    where_clause = " AND ".join(conditions)
    
    # Optimized query for new arrivals with prices
    query = """
        SELECT 
            wi.name,
            wi.web_item_name,
            wi.item_name,
            wi.item_code,
            wi.website_image,
            wi.route,
            wi.item_group,
            wi.brand,
            wi.short_description,
            wi.has_variants,
            wi.creation,
            ip.price_list_rate,
            ip.currency
        FROM `tabWebsite Item` wi
        LEFT JOIN `tabItem Price` ip ON ip.item_code = wi.item_code 
            AND ip.price_list = %(price_list)s
            AND ip.selling = 1
            AND IFNULL(ip.valid_from, '2000-01-01') <= CURDATE()
            AND IFNULL(ip.valid_upto, '2100-01-01') >= CURDATE()
        WHERE {where_clause}
        ORDER BY wi.creation DESC
        LIMIT %(limit)s
    """.format(where_clause=where_clause)
    
    items = frappe.db.sql(query, params, as_dict=True)
    
    # Format items
    formatted_items = []
    for item in items:
        if exclude_items and item.item_code in exclude_items:
            continue
        
        # Add currency for consistent formatting
        if item.price_list_rate:
            item["currency"] = currency
            
        formatted_items.append(_format_carousel_item(item))
        
        # Stop when we have enough items
        if len(formatted_items) >= limit:
            break
    
    return formatted_items

def get_carousel_items(item_group=None, only_promotions=False, limit=20, 
                       sort_by="modified", sort_order="desc", brand=None, 
                       exclude_items=None, search_term=None, use_cache=False,
                       cache_ttl=3600):
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
        use_cache (bool, optional): Whether to use cache (default: False)
        cache_ttl (int, optional): Cache time to live in seconds (default: 3600 = 1 hour)
        
    Returns:
        list: Articles formatted for carousel display
    """
    # Import cache manager
    from webshop.webshop.utils.carousel_cache import CarouselCacheManager
    
    # Check if cache should be used
    if use_cache:
        cache_manager = CarouselCacheManager()
        
        # Generate cache key based on all parameters
        cache_params = {
            "item_group": item_group,
            "only_promotions": only_promotions,
            "limit": limit,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "brand": brand,
            "exclude_items": exclude_items,
            "search_term": search_term
        }
        
        cache_key = cache_manager.generate_cache_key(**cache_params)
        
        # Try to get from cache
        cached_items = cache_manager.get_from_cache(cache_key)
        if cached_items is not None:
            return cached_items
    
    # For new arrivals without promotions, use optimized direct query
    if sort_by in ["creation", "modified"] and not only_promotions and not search_term:
        items = _get_new_arrivals_optimized(limit, item_group, exclude_items)
    else:
        # For all other cases, use ProductQuery
        from webshop.webshop.product_data_engine.query import ProductQuery
        
        # Build field filters
        fields = {}
        if only_promotions:
            fields["discount"] = [10, 90]
        if brand:
            fields["brand"] = brand
        
        # Initialize query engine with optimized limit
        engine = ProductQuery()
        engine.page_length = limit * 2  # Get double to account for post-filtering
        
        # Execute query
        result = engine.query(
            fields=fields,
            search_term=search_term,
            item_group=item_group,
            start=0,
            sort_order={
                "creation": "new_arrivals",
                "modified": "new_arrivals",
                "price": "price_low_to_high",
                "ranking": "relevance"
            }.get(sort_by, "relevance")
        )
        
        # Format and filter items
        items = []
        for item in result.get("items", []):
            # Skip excluded items
            if exclude_items and item.get("item_code") in exclude_items:
                continue
                
            formatted_item = _format_carousel_item(item)
            items.append(formatted_item)
            
            # Stop when we have enough
            if len(items) >= limit:
                break
    
    # Cache the results if cache is enabled
    if use_cache and 'cache_manager' in locals():
        cache_manager.set_cache(cache_key, items, cache_ttl)
    
    return items

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