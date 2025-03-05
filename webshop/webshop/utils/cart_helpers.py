import frappe

def get_cart_data():
    """
    Fonction helper pour obtenir les données du panier formatées pour l'affichage.
    Cette fonction est exposée via Jinja templates dans Builder.
    """
    # Fonction pour créer des abréviations
    def get_abbr(name):
        return ''.join([w[0].upper() for w in name.split()]) if name else ""
    
    # Importer les fonctions nécessaires de webshop
    from webshop.webshop.shopping_cart.cart import get_cart_quotation
    
    # Liste des champs à inclure, SANS description qui contient du HTML
    SAFE_FIELDS = ['website_image', 'thumbnail', 'route', 'brand', 'web_item_name']
    
    # Informations du panier - initialiser avec des valeurs par défaut
    cart_items = []
    cart_total = 0
    cart_items_count = 0
    cart_currency = "CHF"  # Valeur par défaut
    cart_info_fields = {}
    tax_info = []
    
    try:
        # Récupérer la quotation active (panier) en utilisant la fonction dédiée
        cart_info = get_cart_quotation()
        
        # Vérifier si un document a été trouvé
        if cart_info and cart_info.get('doc'):
            quotation = cart_info.get('doc')
            cart_total = quotation.grand_total
            cart_items_count = quotation.total_qty or 0
            
            # Récupérer les informations générales du panier
            cart_info_fields = {}
            for field in ['currency', 'conversion_rate', 'price_list_currency', 'taxes_and_charges',
                        'total', 'base_total', 'net_total', 'base_net_total', 'total_taxes_and_charges',
                        'discount_amount', 'coupon_code']:
                if hasattr(quotation, field) and getattr(quotation, field) is not None:
                    cart_info_fields[field] = getattr(quotation, field)
            
            # S'assurer que nous avons au moins la devise
            if 'currency' in cart_info_fields:
                cart_currency = cart_info_fields['currency']
            
            # Obtenir les infos de taxes
            tax_info = []
            if hasattr(quotation, 'taxes') and quotation.taxes:
                for tax in quotation.taxes:
                    tax_info.append({
                        'description': tax.description,
                        'tax_amount': tax.tax_amount,
                        'rate': tax.rate if hasattr(tax, 'rate') else None
                    })
            
            # Processus des items du panier
            for item in quotation.get('items', []):
                # Créer un dictionnaire avec les informations de base
                item_dict = {
                    "item_code": item.get('item_code', ''),
                    "item_name": item.get('item_name', ''),
                    "qty": item.get('qty', 1),
                    "rate": item.get('rate', 0),
                    "amount": item.get('amount', 0),
                    "abbr": get_abbr(item.get('item_name', '')),
                }
                
                # Ajouter uniquement les champs sûrs (sans HTML)
                for field in SAFE_FIELDS:
                    if hasattr(item, field) and getattr(item, field):
                        item_dict[field] = getattr(item, field)
                
                cart_items.append(item_dict)
    except Exception as e:
        frappe.log_error(f"Erreur lors de la récupération du panier: {str(e)}", "Cart Error")
    
    # Retourner les données du panier
    return {
        "cart_items": cart_items,
        "cart_total": cart_total,
        "cart_items_count": cart_items_count,
        "currency": cart_currency,
        "cart_info": cart_info_fields,
        "tax_info": tax_info
    }