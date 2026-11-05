# //// Neoffice — added file (no upstream equivalent). Endpoints of the shop sign-in
# //// dialog: check an e-mail, create an account, start an OAuth flow — without
# //// leaving the shop and without losing the cart (3bc2d836f1, 2025-02-11). An
# //// address already taken now signs the visitor in instead of failing (428f770c19,
# //// 2026-04-08 "handle existing users in shop create_account (WI-00297)").
import frappe
from frappe import _
from frappe.utils import cint, validate_email_address
from frappe.utils.oauth import get_oauth2_authorize_url

# //// Neoffice — the address nginx saw, and the limit per connection of a door open to strangers
# //// (utils/throttle.py).
from webshop.webshop.utils.throttle import peer_ip, throttle

# //// Neoffice — accounts one address may create in an hour (#691 D-9): each sends a welcome
# //// email, and nothing limited them. Generous enough for a shop's own counter, where every
# //// customer signs up from the same connection. Only accounts actually created count: frappe's
# //// rate_limit counted every call, so a typo, a missing name or an address already known used
# //// the allowance up (the browser suite did in one afternoon, 2026-09-25).
SIGN_UPS_PER_HOUR = 20
# //// Neoffice — the calls of this module's doors, per connection. Generous for the same reason, a shop's
# //// counter signs a queue of customers in from one address: they stop a script, which frappe's lock of an
# //// account does not, when it tries one password on many accounts or asks about one address after
# //// another.
SIGN_INS_PER_MINUTE = 20
SIGN_INS_PER_HOUR = 200
ADDRESS_CHECKS_PER_MINUTE = 20
ADDRESS_CHECKS_PER_HOUR = 200
SIGN_UP_CALLS_PER_HOUR = 200
# //// Neoffice — the length of `User.email` and of `User.full_name`: longer ones failed at the insert (see
# //// create_account).
EMAIL_LENGTH = 140
FULL_NAME_LENGTH = 140


def _sign_ups_key():
    # //// Neoffice — the address nginx saw, not `request_ip`, the first X-Forwarded-For entry: a caller who
    # //// wrote a new one on each call was never counted, and could use up the allowance of somebody else's
    # //// address.
    return f"webshop:sign_ups:{peer_ip()}"


def _sign_ups_so_far():
    return cint(frappe.cache().get_value(_sign_ups_key(), expires=True))


def _count_sign_up():
    # an hour after the last account created from this address, the count starts again
    frappe.cache().set_value(_sign_ups_key(), _sign_ups_so_far() + 1, expires_in_sec=60 * 60)


# //// Neoffice — added helper (#691 D-9, 2026-09-26): create_account honours this setting, as
# //// frappe's own sign_up() does.
def signups_disabled() -> bool:
    """Website Settings' "Disable Signup". Frappe ticks it on a site created from scratch (the
    field's default, the CI's site); the fleet's instances read it unticked (read-only census,
    2026-09-26). A new shop instance must have it unticked to take sign-ups."""
    return bool(cint(frappe.db.get_single_value("Website Settings", "disable_signup")))

# //// Neoffice — extracted from create_account so that complete_sign_up (auth/code_sign_in.py, the account a
# //// code opens) builds the very same user: a Website User with the Customer role and nothing else.
def new_website_user(email, first_name, last_name):
    """The unsaved User the shop opens for a customer. Never a System User."""
    return frappe.get_doc({
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


# //// Neoffice — `email: str`: a JSON body's list went on as an operator (`like`), and a guest walked the
# //// addresses one letter at a time. Limited per connection: it answers strangers, and nothing limited
# //// them.
# permission-check: ok a public door of the sign-in dialog: one address, limited per connection
@frappe.whitelist(allow_guest=True)
@throttle("check_email_minute", ADDRESS_CHECKS_PER_MINUTE, 60)
@throttle("check_email_hour", ADDRESS_CHECKS_PER_HOUR, 3600)
def check_email(email: str):
    """Check if email already exists"""
    if not email:
        return {"exists": False}

    # //// Neoffice — where the shop signs in with a code (auth/code_sign_in.py), nothing tells a known address
    # //// from an unknown one: the dialog no longer asks, and a direct call gets one answer for every address.
    from webshop.webshop.auth.code_sign_in import available

    if available():
        return {"exists": False, "login_with_email_link": False, "first_name": None}

    exists = frappe.db.exists("User", {"email": email})
    login_with_email_link = frappe.db.get_single_value('System Settings', 'login_with_email_link')

    # //// Neoffice — no first name any more: the dialog only greeted with it, and it gave a stranger the
    # //// name of whoever holds an address. Whether the address has an account stays, here and only here:
    # //// without a code to mail, the dialog needs it to choose between the password and the creation form.
    return {
        "exists": bool(exists),
        "login_with_email_link": bool(login_with_email_link),
        "first_name": None
    }

# //// Neoffice — reviewed for guests (frappe's semgrep rule guest-whitelisted-method, #691 D-9,
# //// 2026-09-25): it creates a Website User with the Customer role and nothing else, refuses an
# //// address any User already holds, and opens the account at once only for an address the shop
# //// does not know (auth/confirmation.py). Limited per address and per hour (SIGN_UPS_PER_HOUR), and
# //// by frappe's own ceiling on sign-ups.
# //// Neoffice — the calls are limited too, far above the accounts: only an account created counted, so a
# //// script read for free which addresses are taken.
# permission-check: ok a public door: it opens a Website User, limited per connection and per hour
@frappe.whitelist(allow_guest=True)  # nosemgrep: frappe-semgrep-rules.rules.security.guest-whitelisted-method
@throttle("create_account_hour", SIGN_UP_CALLS_PER_HOUR, 3600)
def create_account():
    try:
        # //// Neoffice — texts, the names as complete_sign_up reads them (auth/code_sign_in.py). A name
        # //// over 140 characters failed at the insert: a free address then answered `unknown_error`, no
        # //// account and nothing counted, a probe for nothing. A list or a dict of a JSON body ended there
        # //// too, with an Error Log row.
        from webshop.webshop.auth.code_sign_in import _clean_name

        email = frappe.form_dict.get('email')
        email = email.strip().lower() if isinstance(email, str) else ""
        first_name = _clean_name(frappe.form_dict.get('first_name'))
        last_name = _clean_name(frappe.form_dict.get('last_name'))
        # //// Neoffice — the two together, and a space: `full_name` holds no more (FULL_NAME_LENGTH).
        last_name = last_name[: FULL_NAME_LENGTH - len(first_name) - 1].strip()

        if not email or not first_name or not last_name:
            return {
                "message": "error",
                "reason": _("Please fill in all required fields"),
                "reason_code": "missing_fields",
            }

        # Validate email format
        try:
            validate_email_address(email, throw=True)
            # //// Neoffice — see EMAIL_LENGTH.
            if len(email) > EMAIL_LENGTH:
                raise ValueError
        except Exception:
            return {
                "message": "error",
                "reason": _("Please enter a valid email address"),
                "reason_code": "invalid_email",
            }

        # //// Neoffice — Website Settings' "Disable Signup" is honoured (#691 D-9, 2026-09-26): frappe's
        # //// own sign_up() refuses, and this endpoint created accounts whatever it said. No instance
        # //// of the fleet had it ticked that day (read-only census), so nothing changes where it
        # //// is not. The dialog shows the reason, as it shows every refusal.
        if signups_disabled():
            return {
                "message": "error",
                "reason": _("New accounts cannot be created on this site. Please contact the shop."),
                "reason_code": "signup_disabled",
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
            # //// Neoffice — one answer for every account: a System User had its own, which told a stranger
            # //// which addresses are staff. The shop still touches no existing account: nothing below this
            # //// runs.
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
        user = new_website_user(email, first_name, last_name)

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

    # //// Neoffice — the code sign-in (auth/code_sign_in.py): on, the dialog asks for a code first and keeps the
    # //// password for whoever has one; off (or stock frappe), it is the dialog it always was.
    from webshop.webshop.auth.code_sign_in import available

    passwordless = available()
    return {
        "passwordless": passwordless,
        "social_login": len(provider_list) > 0,
        "login_with_email_link": False if passwordless else frappe.get_system_settings("login_with_email_link"),
        "provider_logins": provider_list,
        "ldap_settings": frappe.db.get_value("LDAP Settings", "LDAP Settings", "enabled")
    }

# //// Neoffice — added helper for custom_login below.
def _continue_on_the_sign_in_page():
    """The password is right and frappe asks for more: a second factor, or a new password. The shop's
    dialog can do neither, so no session opens and the person goes on where they can. Never a 200: the
    dialog takes any 200 for a signed-in visitor, and answers to 401 and 403 only."""
    target = frappe.local.response.pop("redirect_to", None) or "/login"
    for key in ("verification", "tmp_id"):
        frappe.local.response.pop(key, None)
    reason = _("This account finishes signing in on the sign-in page.")
    frappe.msgprint(f'{reason} <a href="{frappe.utils.escape_html(target)}">{_("Continue")}</a>')
    frappe.local.response.http_status_code = 403
    return {
        "message": "error",
        "reason": reason,
        "reason_code": "use_the_sign_in_page",
        "redirect_to": target,
    }


# //// Neoffice — this door called `authenticate` and `post_login` alone, which leave out what
# //// `LoginManager.login` decides between them: a second factor, an expired password, a site that forbids
# //// passwords. A password alone opened any account, the desk's included. It now runs that very method:
# //// what the normal login refuses is refused here, and what upstream adds to it comes with it. POST only:
# //// a password does not belong in an address, which logs keep.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@throttle("custom_login_minute", SIGN_INS_PER_MINUTE, 60)
@throttle("custom_login_hour", SIGN_INS_PER_HOUR, 3600)
def custom_login():
    try:
        usr = frappe.form_dict.get('usr')
        pwd = frappe.form_dict.get('pwd')
        # //// Neoffice — texts: a list of a JSON body became a filter on User in `find_by_credentials`.
        if not isinstance(usr, str) or not isinstance(pwd, str):
            raise frappe.AuthenticationError
        # //// Neoffice — the second step of frappe's sign-in page, which this door does not have.
        frappe.form_dict.pop("tmp_id", None)
        frappe.form_dict.pop("otp", None)

        login_manager = frappe.auth.LoginManager()
        if login_manager.login() is False:
            return _continue_on_the_sign_in_page()

        return {
            "message": "success",
            # //// Neoffice — where frappe sends this account: the desk for staff, the site for a customer.
            "home_page": (
                frappe.local.response.get("home_page") or frappe.get_hooks().get("home_page", ["/"])[0]
            ),
        }
    # //// Neoffice — frappe's lock of an account or of an address: a 500 until now, and the dialog, which
    # //// answers to 401 and 403 only, kept its button grey. Its message stays in the answer, for the
    # //// person to read.
    except frappe.SecurityException:
        frappe.local.response.http_status_code = 403
        return {
            "message": "error",
            "reason": _("Too many failed attempts. Please try again later."),
            "reason_code": "locked",
        }
    except frappe.AuthenticationError:
        frappe.clear_messages()
        frappe.local.response.http_status_code = 401
        return {
            "message": "error",
            # //// Neoffice — this was a bare English string; it goes through _().
            "reason": _("Invalid credentials")
        }
