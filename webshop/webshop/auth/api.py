# //// Neoffice — added file (no upstream equivalent). Endpoints of the shop sign-in
# //// dialog: check an e-mail, create an account, start an OAuth flow — without
# //// leaving the shop and without losing the cart (3bc2d836f1, 2025-02-11). An
# //// address already taken now signs the visitor in instead of failing (428f770c19,
# //// 2026-04-08 "handle existing users in shop create_account (WI-00297)").
import frappe
from frappe import _
from frappe.utils import cint, validate_email_address
from frappe.utils.oauth import get_oauth2_authorize_url

# //// Neoffice — accounts one address may create in an hour (#691 D-9): each sends a welcome
# //// email, and nothing limited them. Generous enough for a shop's own counter, where every
# //// customer signs up from the same connection. Only accounts actually created count: frappe's
# //// rate_limit counted every call, so a typo, a missing name or an address already known used
# //// the allowance up (the browser suite did in one afternoon, 2026-09-25).
SIGN_UPS_PER_HOUR = 20


def _sign_ups_key():
    return f"webshop:sign_ups:{getattr(frappe.local, 'request_ip', None) or 'unknown'}"


def _sign_ups_so_far():
    return cint(frappe.cache().get_value(_sign_ups_key(), expires=True))


def _count_sign_up():
    # an hour after the last account created from this address, the count starts again
    frappe.cache().set_value(_sign_ups_key(), _sign_ups_so_far() + 1, expires_in_sec=60 * 60)

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

# //// Neoffice — reviewed for guests (frappe's semgrep rule guest-whitelisted-method, #691 D-9,
# //// 2026-09-25): it creates a Website User with the Customer role and nothing else, refuses an
# //// address any User already holds, and opens the account at once only for an address the shop
# //// does not know (auth/confirmation.py). Limited per address and per hour (SIGN_UPS_PER_HOUR), and
# //// by frappe's own ceiling on sign-ups.
@frappe.whitelist(allow_guest=True)  # nosemgrep: frappe-semgrep-rules.rules.security.guest-whitelisted-method
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

        # //// Neoffice — frappe's own ceiling on sign-ups, which its sign_up() applies and this
        # //// endpoint skipped (System Settings, 300 an hour by default), and this address's own
        # //// allowance (SIGN_UPS_PER_HOUR)
        ceiling = cint(frappe.db.get_single_value("System Settings", "max_signups_allowed_per_hour")) or 300
        if _sign_ups_so_far() >= SIGN_UPS_PER_HOUR or frappe.db.get_creation_count("User", 60) >= ceiling:
            frappe.local.response.http_status_code = 429
            return {
                "message": "error",
                "reason": _("Too many accounts were created in the last hour. Please try again later."),
                "reason_code": "too_many_signups",
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
            _count_sign_up()  # //// Neoffice — see SIGN_UPS_PER_HOUR
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

        # //// Neoffice — the account is opened and signed in at once, its address confirmed
        # //// afterwards by the welcome email's link (auth/confirmation.py, decision D-9 of the SEO
        # //// plan, #691): a first order no longer waits on a mailbox. Not for an address the shop
        # //// already knows, nor on a site for business accounts only: those keep the link first.
        from webshop.webshop.auth.confirmation import open_account, opens_at_once

        if opens_at_once(email):
            open_account(user.name)
            return {
                "message": "success",
                "signed_in": True,
                "reason": _("Account created successfully"),
                "notice": _(
                    "Your account is open and you are signed in. We sent you an email to confirm your address and choose a password."
                ),
            }

        return {
            "message": "success",
            "reason": _("Account created successfully"),
        }

    except Exception:
        frappe.log_error("Webshop create_account failed", frappe.get_traceback())
        frappe.clear_messages()
        # //// Neoffice — no "detail" any more: the exception's text went to the visitor (#691 D-9)
        return {
            "message": "error",
            "reason": _("An error occurred while creating your account. Please try again."),
            "reason_code": "unknown_error",
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
