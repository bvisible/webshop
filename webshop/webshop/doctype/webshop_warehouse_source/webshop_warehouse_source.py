# //// Neoffice — added file (no upstream equivalent). Child table of Webshop
# //// Settings describing one stock source of the multi-warehouse feature:
# //// which warehouse, how it is labelled to shoppers, where its quantity is
# //// read from (real Bin or a synced Item field), its delivery lead time and
# //// its procurement behaviour (supplier, receiving warehouse).

from frappe.model.document import Document


class WebshopWarehouseSource(Document):
	pass
