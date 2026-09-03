#//// Neoffice — added file (purchase follow-ups, no upstream equivalent).
from frappe import _


def get_data():
	"""The flow's connections: the customers it enrolled."""
	return {
		"fieldname": "flow",
		"transactions": [{"label": _("Customers"), "items": ["Purchase Follow-up Entry"]}],
	}
