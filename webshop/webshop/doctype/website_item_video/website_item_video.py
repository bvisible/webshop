# //// Neoffice — added file (no upstream equivalent).
"""A video on a product page: a YouTube or Vimeo address, or a file the shop hosts.

Rows of Website Item's `videos` table. What the shop does with them lives in
`webshop.webshop.utils.videos` (address parsing, embed URLs, posters).
"""

from frappe.model.document import Document


class WebsiteItemVideo(Document):
	pass
