import frappe

from frappe import _
from frappe.utils import get_link_to_form


class DataValidationError(frappe.ValidationError):
    pass


def execute(doc, method=None, old_name=None, new_name=None, merge=False):
    """
    Block merge if both old and new items have website items against them.
    This is to avoid duplicate website items after merging.
    """
    if not merge:
        return

    web_items = frappe.get_all(
        "Website Item",
        filters={"item_code": ["in", [old_name, new_name]]},
        fields=["item_code", "name"],
    )

    if len(web_items) <= 1:
        return

    old_web_item = [d.get("name") for d in web_items if d.get("item_code") == old_name][0]
    web_item_link = get_link_to_form("Website Item", old_web_item)
    old_name, new_name = frappe.bold(old_name), frappe.bold(new_name)

    # //// Neoffice — upstream built the sentence in an f-string and then called _() on the result: the
    # //// key changed with every item name and never matched a catalogue entry, so the message stayed
    # //// English. The template is the key, the values are formatted in after the translation.
    msg = _("Please delete linked Website Item {0} before merging {1} into {2}").format(
        frappe.bold(web_item_link), old_name, new_name
    )
    frappe.throw(msg, title=_("Cannot Merge"), exc=DataValidationError)

