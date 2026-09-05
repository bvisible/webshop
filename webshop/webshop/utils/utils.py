# //// Neoffice — added file (no upstream equivalent). Jinja helpers exposed to the
# //// Builder-built templates, chiefly format_currency_value, which honours the shop's
# //// "hide currency symbol" setting — a shop that sells in one currency does not want
# //// "CHF" on every tile (0804898032, 2025-03-05; setting 0134ef756e, 2025-07-03).
import frappe
import json

from frappe import _
from frappe.utils.data import fmt_money

@frappe.whitelist( allow_guest=True )
def format_currency_value(value, currency=None, precision=None):
    """Formats the 'value' with the provided currency and precision.
    
    Webshop setting 'hide_currency_symbol_in_shop' controls currency symbol display:
    - Empty/None: Use global ERPNext setting
    - 'Yes': Hide currency symbol
    - 'No': Show currency symbol
    """
    from frappe.utils import cint, flt, get_number_format_info
    
    # Cache the webshop settings lookup
    cache_key = "webshop_hide_currency_symbol"
    webshop_hide_symbol = frappe.cache().get_value(cache_key)
    
    if webshop_hide_symbol is None:
        # Get from database and cache for 1 hour
        webshop_settings = frappe.get_cached_doc("Webshop Settings")
        webshop_hide_symbol = webshop_settings.get("hide_currency_symbol_in_shop") or ""
        frappe.cache().set_value(cache_key, webshop_hide_symbol, expires_in_sec=3600)
    
    # Determine if we should hide the symbol
    if webshop_hide_symbol:
        # Webshop setting overrides global
        hide_symbol = (webshop_hide_symbol == "Yes")
    else:
        # Use global setting
        hide_symbol = frappe.defaults.get_global_default("hide_currency_symbol") == "Yes"
    
    # If we should hide the symbol, format without currency
    if hide_symbol:
        return fmt_money(value, precision=precision, currency=None)
    
    # If no currency specified, use standard formatting
    if not currency:
        return fmt_money(value, precision=precision, currency=currency)
    
    # Otherwise, we want to show the symbol
    # Format the number without currency first (to avoid double symbol issues)
    formatted_number = fmt_money(value, precision=precision, currency=None)
    
    # Add currency symbol manually
    symbol = frappe.db.get_value("Currency", currency, "symbol", cache=True) or currency
    symbol_on_right = frappe.db.get_value("Currency", currency, "symbol_on_right", cache=True)
    
    if symbol_on_right:
        return f"{formatted_number} {symbol}"
    else:
        return f"{symbol} {formatted_number}"

def get_gateway_configuration(payment_method, payment_gateway_account=None):
    """Gets the JSON configuration for a given payment method
    
    Args:
        payment_method (str): Payment method type (e.g., 'paypal', 'stripe')
        payment_gateway_account (str, optional): Payment Gateway Account name to check for custom template path
    """
    try:
        # Check for custom template path in payment method
        config_path = None
        if payment_gateway_account:
            webshop_method = frappe.get_doc("Webshop Payment Method", {"payment_gateway_account": payment_gateway_account})
            if webshop_method.get("template_path"):
                # Get the JSON file from the same location as the template
                template_path = webshop_method.template_path
                if template_path.startswith('apps/'):
                    # Remove apps/ prefix and .html extension, add .json
                    path_parts = template_path[5:].rsplit('.', 1)[0].split('/')
                    # Remove duplicate app name if present
                    if len(path_parts) > 1 and path_parts[0] == path_parts[1]:
                        path_parts.pop(1)
                    json_path = '/'.join(path_parts) + '.json'
                    config_path = frappe.get_app_path(*json_path.split('/'))
                else:
                    # Default webshop location
                    config_path = frappe.get_app_path("webshop", "templates", "payments", f"{payment_method}.json")
        
        # If no custom path or not found, use default
        if not config_path:
            config_path = frappe.get_app_path("webshop", "templates", "payments", f"{payment_method}.json")
            
        with open(config_path, "r") as f:
            return json.load(f)
    except Exception as e:
        frappe.log_error(f"Error reading payment configuration: {str(e)}")
        return {}

@frappe.whitelist( allow_guest=True )
def get_first_name(user):
    return frappe.db.get_value("User", user, "first_name")

@frappe.whitelist(allow_guest=True)
def get_user_header_info():
    """
    Get user information for the header component.
    This is called via JavaScript to avoid caching user-specific data in the navbar HTML.

    Returns:
        dict: User information including:
            - is_logged_in: bool
            - user: str (email)
            - first_name: str
            - full_name: str
            - avatar: str (HTML for avatar)
            - cart_count: int
    """
    user = frappe.session.user
    is_logged_in = user != "Guest"

    result = {
        "is_logged_in": is_logged_in,
        "user": user,
        "first_name": "",
        "full_name": "",
        "avatar": "",
        "cart_count": 0
    }

    if is_logged_in:
        # Get user details
        user_doc = frappe.get_cached_doc("User", user)
        result["first_name"] = user_doc.first_name or user.split("@")[0]
        result["full_name"] = user_doc.full_name or result["first_name"]

        # Generate avatar HTML
        from frappe.utils.html_utils import get_icon_html
        result["avatar"] = get_user_avatar_html(user)

    # Get cart count from cookie or calculate
    cart_count = "0"
    try:
        if hasattr(frappe, 'request') and frappe.request and hasattr(frappe.request, 'cookies'):
            cart_count = frappe.request.cookies.get("cart_count", "0")
        result["cart_count"] = int(cart_count)
    except (ValueError, TypeError, RuntimeError):
        result["cart_count"] = 0

    return result

def get_user_avatar_html(user):
    """Generate avatar HTML for a user."""
    user_doc = frappe.get_cached_doc("User", user)

    if user_doc.user_image:
        return f'<span class="avatar avatar-small"><span class="avatar-frame" style="background-image: url(\'{user_doc.user_image}\')"></span></span>'
    else:
        # Generate initials
        first_name = user_doc.first_name or ""
        last_name = user_doc.last_name or ""
        initials = (first_name[:1] + last_name[:1]).upper() or user[:1].upper()
        return f'<span class="avatar avatar-small"><div class="standard-image">{initials}</div></span>'

def webshop_fmt_money(value, currency=None, precision=None):
    """
    Template helper function for formatting money in webshop templates.
    This is a wrapper around format_currency_value that can be used directly in Jinja templates.
    """
    return format_currency_value(value, currency=currency, precision=precision)


def description_excerpt(html: str, budget: int = 900) -> dict:
	"""Un extrait qui garde sa mise en forme, parce qu'il coupe entre les blocs.

	Couper du HTML au caractère près, c'est trancher au milieu d'une balise :
	on s'en sort en retirant toutes les balises, et l'extrait perd ses listes,
	son gras, ses paragraphes. Vu à l'écran — une description soignée arrivait
	dans la colonne d'achat en un bloc de texte gris.

	Alors on ne coupe pas dans le texte : on prend les blocs de premier niveau
	— paragraphes, listes, titres — **entiers**, tant qu'on tient dans le
	budget, et on s'arrête au premier qui le dépasse. Le résultat est du HTML
	valide, avec sa mise en forme, et il ne finit jamais au milieu d'une phrase.

	Rend `{"html": ..., "cut": True/False}` : `cut` dit s'il reste quelque
	chose à lire plus bas — c'est lui qui décide d'afficher « Lire la suite »
	ET le bloc pleine largeur, pour que les deux ne se contredisent jamais.
	"""
	texte = (html or "").strip()
	if not texte:
		return {"html": "", "cut": False}

	entier = frappe.utils.strip_html(texte).strip()
	if len(entier) <= budget:
		return {"html": texte, "cut": False}

	from bs4 import BeautifulSoup

	soup = BeautifulSoup(texte, "html.parser")
	# Un éditeur enveloppe souvent tout dans un div : c'est ce div qu'il faut
	# ouvrir, sinon le premier « bloc » est le document entier et on ne coupe
	# jamais rien.
	racine = soup
	while True:
		enfants = [e for e in racine.children if getattr(e, "name", None) or str(e).strip()]
		if len(enfants) == 1 and getattr(enfants[0], "name", None) in ("div", "section", "article"):
			racine = enfants[0]
			continue
		break

	gardes, compte = [], 0
	for bloc in racine.children:
		morceau = str(bloc)
		if not morceau.strip():
			continue
		longueur = len(frappe.utils.strip_html(morceau).strip())
		if gardes and compte + longueur > budget:
			break
		gardes.append(morceau)
		compte += longueur
		if compte >= budget:
			break

	if not gardes:
		# Un seul bloc, plus long que le budget : là, on coupe au mot près et
		# on assume la perte de mise en forme — il n'y a pas de couture ailleurs.
		return {"html": frappe.utils.strip_html(texte)[:budget].rsplit(" ", 1)[0] + "…", "cut": True}

	reste = len(entier) - compte
	return {"html": "".join(gardes), "cut": reste > 0}
