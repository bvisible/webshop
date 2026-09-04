#//// Neoffice — added file (no upstream equivalent). Endpoints of the shop sign-in
#//// dialog: check an e-mail, create an account, start an OAuth flow — without
#//// leaving the shop and without losing the cart (3bc2d836f1, 2025-02-11). An
#//// address already taken now signs the visitor in instead of failing (428f770c19,
#//// 2026-04-08 "handle existing users in shop create_account (WI-00297)").
import frappe
from frappe import _
from frappe.utils import validate_email_address
from frappe.utils.oauth import get_oauth2_authorize_url

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
        email = (frappe.form_dict.get('email') or "").strip().lower()
        first_name = (frappe.form_dict.get('first_name') or "").strip()
        last_name = (frappe.form_dict.get('last_name') or "").strip()

        if not email or not first_name or not last_name:
            return {
                "message": "error",
                "reason": _("Please fill in all required fields"),
                "reason_code": "missing_fields",
            }

        # Validate email format
        try:
            validate_email_address(email, throw=True)
        except Exception:
            return {
                "message": "error",
                "reason": _("Please enter a valid email address"),
                "reason_code": "invalid_email",
            }

        # Check if a User already exists with this email.
        # In Frappe, User.name is the email, so checking by name is sufficient
        # and covers both the PRIMARY key constraint and any orphan cases.
        existing_user_type = frappe.db.get_value("User", email, "user_type")
        if existing_user_type:
            if existing_user_type == "System User":
                # Never allow the shop to touch a System User account — this
                # prevents privilege confusion and accidental account hijack.
                return {
                    "message": "error",
                    "reason": _(
                        "This email is already linked to an administrator account. "
                        "Please contact your administrator or use a different email."
                    ),
                    "reason_code": "account_exists_system",
                }
            # Website User already exists — ask the customer to sign in instead.
            return {
                "message": "error",
                "reason": _("An account already exists with this email. Please sign in instead."),
                "reason_code": "account_exists_website",
            }

        # Create user as a Website User (never System User). We disable the
        # built-in welcome email here and send it manually afterwards, so that
        # a misconfigured SMTP server cannot prevent the account from being
        # reported as successfully created.
        user = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "enabled": 1,
            "user_type": "Website User",
            "send_welcome_email": 0,
            "roles": [{
                "role": "Customer",
                "doctype": "Has Role"
            }]
        })

        try:
            user.insert(ignore_permissions=True)
        except frappe.DuplicateEntryError:
            # Race condition: a parallel request created the account between
            # our existence check and the insert. Report cleanly instead of
            # leaking the raw IntegrityError payload.
            frappe.clear_messages()
            return {
                "message": "error",
                "reason": _("An account already exists with this email. Please sign in instead."),
                "reason_code": "account_exists_website",
            }

        # Best-effort welcome email: never block account creation on a mail failure.
        try:
            user.reload()
            user.send_welcome_mail_to_user()
        except Exception:
            frappe.log_error("Webshop welcome email failed", frappe.get_traceback())
            frappe.clear_messages()

        return {
            "message": "success",
            "reason": _("Account created successfully"),
        }

    except Exception as e:
        frappe.log_error("Webshop create_account failed", frappe.get_traceback())
        frappe.clear_messages()
        return {
            "message": "error",
            "reason": _("An error occurred while creating your account. Please try again."),
            "reason_code": "unknown_error",
            "detail": str(e),
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
                "auth_url": get_oauth2_authorize_url(provider.name, redirect_to="/me"),
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
