import frappe
from frappe import _
from frappe.utils import validate_email_address

@frappe.whitelist(allow_guest=True)
def check_email(email):
    """Check if email already exists"""
    if not email:
        return {"exists": False}

    exists = frappe.db.exists("User", {"email": email})
    login_with_email_link = frappe.db.get_single_value('System Settings', 'login_with_email_link')
    
    first_name = None
    if exists:
        first_name = frappe.db.get_value("User", {"email": email}, "first_name")
    
    return {
        "exists": bool(exists),
        "login_with_email_link": bool(login_with_email_link),
        "first_name": first_name
    }

@frappe.whitelist(allow_guest=True)
def create_account():
    try:
        email = frappe.form_dict.get('email')
        first_name = frappe.form_dict.get('first_name')
        last_name = frappe.form_dict.get('last_name')

        if not email or not first_name or not last_name:
            return {
                "message": "error",
                "reason": "Please fill in all required fields"
            }

        # Create user
        user = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "enabled": 1,
            "user_type": "Website User",
            "send_welcome_email": 1,
            "roles": [{
                "role": "Customer",
                "doctype": "Has Role"
            }]
        })
        
        user.insert(ignore_permissions=True)
        
        return {
            "message": "success",
            "reason": "Account created successfully"
        }
        
    except Exception as e:
        frappe.clear_messages()
        return {
            "message": "error",
            "reason": str(e)
        }

@frappe.whitelist(allow_guest=True)
def get_auth_settings():
    """Get authentication settings including social login providers and email link login"""
    providers = frappe.get_all(
        "Social Login Key",
        filters={"enable_social_login": 1},
        fields=["name", "client_id", "base_url", "provider_name", "icon"],
        order_by="name",
    )

    provider_list = []
    for provider in providers:
        client_secret = frappe.utils.password.get_decrypted_password("Social Login Key", provider.name, "client_secret")
        if not client_secret:
            continue

        icon = None
        if provider.icon:
            if provider.provider_name == "Custom":
                icon = frappe.utils.html_utils.get_icon_html(provider.icon, small=True)
            else:
                icon = f"<img src='{frappe.utils.data.escape_html(provider.icon)}' alt='{frappe.utils.data.escape_html(provider.provider_name)}'>"

        if provider.client_id and provider.base_url:
            provider_list.append({
                "name": provider.name,
                "provider_name": provider.provider_name,
                "auth_url": frappe.utils.oauth.get_oauth2_authorize_url(provider.name),
                "icon": icon
            })

    return {
        "social_login": len(provider_list) > 0,
        "login_with_email_link": frappe.get_system_settings("login_with_email_link"),
        "provider_logins": provider_list,
        "ldap_settings": frappe.db.get_value("LDAP Settings", "LDAP Settings", "enabled")
    }

@frappe.whitelist(allow_guest=True)
def custom_login():
    try:
        usr = frappe.form_dict.get('usr')
        pwd = frappe.form_dict.get('pwd')
        
        login_manager = frappe.auth.LoginManager()
        login_manager.authenticate(usr, pwd)
        login_manager.post_login()
        
        return {
            "message": "success",
            "home_page": frappe.get_hooks().get("home_page", ["/"])[0]
        }
    except frappe.AuthenticationError:
        frappe.clear_messages()
        frappe.local.response.http_status_code = 401
        return {
            "message": "error",
            "reason": "Invalid credentials"
        }
