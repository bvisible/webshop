# //// Neoffice — added file (second-hand feature, no upstream equivalent).
# //// The shop's second-hand page: the product listing with the Condition
# //// facet locked to used and refurbished units.

from frappe import _

from webshop.webshop.product_data_engine.listing_context import build_listing_context
from webshop.webshop.utils.used_items import SECOND_HAND_CONDITIONS

sitemap = 1


def get_context(context):
	build_listing_context(
		context,
		_("Second-hand products"),
		locked_field_filters={"item_condition": list(SECOND_HAND_CONDITIONS)},
		listing_route="/occasions",
	)
