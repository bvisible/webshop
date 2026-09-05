# //// Neoffice — added file (no upstream equivalent). Stores the pairs computed nightly
# //// from past orders and shown on the product page; upstream's "recommended items"
# //// are hand-picked only (3c1e847e26, 2025-06-24).
# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class FrequentlyBoughtTogether(Document):
	pass