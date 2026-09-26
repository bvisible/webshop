# //// Neoffice — added file (no upstream equivalent). neoffice-maintenance#691, plan note 20.
"""A day's SEO figures of one site: how many products, their average score, how many Google
Shopping gets, and how many lack a description, an identifier or picture descriptions.

Written every night by `webshop.webshop.seo.score.refresh_all`, one row per site and day, kept
400 days: the workspace's chart of the average score over time reads them.
"""

from frappe.model.document import Document


class WebshopSEOSnapshot(Document):
	pass
