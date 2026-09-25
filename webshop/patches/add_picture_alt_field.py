# //// Neoffice — added file (no upstream equivalent): the description of each slideshow picture,
# //// for those who cannot see it (webshop/webshop/seo/alt_text.py). neoffice-maintenance#691,
# //// decision D-11 of the SEO plan, 2026-09-25. The website image has its own since upstream
# //// (Website Item.website_image_alt); a slide only had its heading, a caption.

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Website Slideshow Item": [
				{
					"fieldname": "image_alt",
					"fieldtype": "Small Text",
					"label": "Picture description",
					"description": "What someone who cannot see the picture needs to know: read aloud by screen readers, shown when the picture fails to load, read by search engines.",
					"insert_after": "image",
				}
			]
		},
		update=True,
	)
	frappe.clear_cache(doctype="Website Slideshow Item")
