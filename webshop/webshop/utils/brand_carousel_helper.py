import frappe
from frappe import _
import uuid

def get_carousel_brands(limit=10, sort_by="modified", sort_order="desc", featured_only=False, 
                        category=None, exclude_brands=None, search_term=None):
    """
    Helper function to get formatted brands for the carousel.
    
    Args:
        limit (int, optional): Maximum number of brands to retrieve
        sort_by (str, optional): Field for sorting
        sort_order (str, optional): Sorting direction ('asc' or 'desc')
        featured_only (bool, optional): Display only featured brands
        category (str, optional): Filter by category
        exclude_brands (list, optional): List of brand names to exclude
        search_term (str, optional): Search term
        
    Returns:
        list: Brands formatted for carousel display
    """
    try:
        # Check if the Brand table exists
        if not frappe.db.table_exists("Brand"):
            frappe.log_error("Table Brand does not exist")
            return []
            
        # Get metadata of the Brand table to check available fields
        brand_meta = frappe.get_meta("Brand")
        available_fields = [field.fieldname for field in brand_meta.fields]
        
        # Initialize base filters (without published which may not exist)
        filters = {}
        
        # Add featured filter if exists
        if featured_only and "featured" in available_fields:
            filters["featured"] = 1
            
        # Add category filter if exists
        if category and "category" in available_fields:
            filters["category"] = category
        
        # Add show_in_website filter if exists
        if "show_in_website" in available_fields:
            filters["show_in_website"] = 1
        
        # Prepare filters for SQL query
        query_filters = []
        for key, value in filters.items():
            query_filters.append(f"`tabBrand`.`{key}` = {frappe.db.escape(value)}")
            
        # Add search term if provided
        if search_term:
            search_conditions = []
            if "brand" in available_fields:
                search_conditions.append(f"`tabBrand`.`brand` LIKE {frappe.db.escape('%' + search_term + '%')}")
            if "description" in available_fields:
                search_conditions.append(f"`tabBrand`.`description` LIKE {frappe.db.escape('%' + search_term + '%')}")
            
            if search_conditions:
                query_filters.append(f"({' OR '.join(search_conditions)})")
            
        # Combine filters
        where_clause = " AND ".join(query_filters) if query_filters else "1=1"
        
        # Add brand exclusion if provided
        if exclude_brands:
            exclude_clause = ", ".join([frappe.db.escape(brand) for brand in exclude_brands])
            where_clause += f" AND `tabBrand`.`name` NOT IN ({exclude_clause})"
            
        # Check if the sort field exists
        if sort_by not in available_fields and sort_by != "name":
            sort_by = "modified" if "modified" in available_fields else "name"
            
        # Prepare the order by clause
        order_by_clause = f"`tabBrand`.`{sort_by}` {sort_order}"
        
        # Determine fields to select based on available fields
        fields = ["`tabBrand`.`name`"]
        
        # Add fields if they exist
        field_mapping = {
            "brand": "`tabBrand`.`brand`",
            "description": "`tabBrand`.`description`",
            "brand_logo": "`tabBrand`.`brand_logo` as logo",
            "logo": "`tabBrand`.`logo` as logo",
            "route": "`tabBrand`.`route`",
            "modified": "`tabBrand`.`modified`",
            "creation": "`tabBrand`.`creation`"
        }
        
        for field, sql_field in field_mapping.items():
            if field in available_fields or field in ["name", "modified", "creation"]:
                fields.append(sql_field)
        
        # Execute the query
        brands = frappe.db.sql(f"""
            SELECT {', '.join(fields)}
            FROM `tabBrand`
            WHERE {where_clause}
            ORDER BY {order_by_clause}
            LIMIT {int(limit)}
        """, as_dict=1)

        # Format brands for carousel
        formatted_brands = []
        for brand in brands:
            # Get the logo or use a placeholder
            logo = brand.get("logo") or ""
            
            # Get the route or create one
            route = brand.get("route") or f"brands/{frappe.scrub(brand.name)}"
            
            # Format brand for carousel
            formatted_brand = {
                "name": brand.name,
                "brand_name": brand.get("brand") or brand.name,
                "description": brand.get("description") or "",
                "logo": logo,
                "route": route,
                "modified": brand.get("modified"),
                "creation": brand.get("creation")
            }
            
            formatted_brands.append(formatted_brand)
            
        return formatted_brands
    except Exception as e:
        frappe.log_error(f"Error in get_carousel_brands: {str(e)}")
        return []

def render_brand_carousel(limit=10, sort_by="modified", sort_order="desc", 
                          featured_only=False, category=None, carousel_title=None,
                          carousel_id=None, context=None):
    """
    Render a brand carousel with specified filters
    
    Args:
        limit (int, optional): Maximum number of brands to retrieve
        sort_by (str, optional): Field for sorting
        sort_order (str, optional): Sorting direction ('asc' or 'desc')
        featured_only (bool, optional): Display only featured brands
        category (str, optional): Filter by category
        carousel_title (str, optional): Title for the carousel
        carousel_id (str, optional): Custom ID for the carousel
        context (dict, optional): Jinja template context

    Returns:
        str: HTML rendered for the carousel
    """
    # Get carousel brands
    carousel_brands = get_carousel_brands(
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
        featured_only=featured_only,
        category=category
    )
    
    # Generate a unique ID if not provided
    if not carousel_id:
        carousel_id = f"brand-carousel-{str(uuid.uuid4())[:8]}"
    
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
        try:
            context = frappe._dict({k: v for k, v in context.items() if not k.startswith('_')})
        except:
            # If failure, create a new context
            context = frappe._dict({})
    
    # Update context with carousel brands
    context.update({
        "brands": carousel_brands,
        "carousel_title": carousel_title or _("Nos marques"),
        "carousel_id": carousel_id
    })
    
    # Render the template with the correct path
    try:
        # Try first with the relative path
        return frappe.render_template("templates/includes/brand_carousel.html", context)
    except Exception as e:
        try:
            # Try with the absolute path
            return frappe.render_template("webshop/templates/includes/brand_carousel.html", context)
        except Exception as e:
            # Log the error and return an error message
            frappe.log_error(f"Error rendering brand carousel: {str(e)}")
            return f"<div class='alert alert-warning'>Unable to load brand carousel: {str(e)}</div>"
