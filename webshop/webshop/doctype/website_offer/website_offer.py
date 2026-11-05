# -*- coding: utf-8 -*-
# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class WebsiteOffer(Document):
	pass


# //// Neoffice — the product page's "More" link. offer_id took a filter from a JSON body, which walked the
# //// offers of every item: it is a name now, and the offer of an item the shop does not show is not read, by
# //// the staff's preview aside.
# permission-check: ok the offer printed on a product page anyone can open, and only that one
@frappe.whitelist(allow_guest=True)
def get_offer_details(offer_id: str):
	from webshop.webshop.doctype.website_item.website_item import catalogue_is_closed

	offer = frappe.db.get_value("Website Offer", {"name": offer_id}, ["parent", "offer_details"], as_dict=True)
	if not offer:
		return None
	if not frappe.has_permission("Website Item", "read") and (
		catalogue_is_closed() or not frappe.db.get_value("Website Item", offer.parent, "published")
	):
		return None
	return offer.offer_details
