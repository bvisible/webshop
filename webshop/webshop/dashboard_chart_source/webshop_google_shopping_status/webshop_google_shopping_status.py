# //// Neoffice — added file (no upstream equivalent): the workspace chart of what Google Shopping gets
# //// of the catalogue. neoffice-maintenance#691, plan note 20 (part 1), 2026-09-26.
"""Published products by what Google Shopping gets of them: sent, or left out and why
(Website Item.seo_google_status, written with the SEO score)."""

import frappe
from frappe import _
from frappe.utils.dashboard import cache_source


@frappe.whitelist()
@cache_source
def get(
	chart_name: str | None = None,
	chart: str | dict | None = None,
	no_cache: int | str | None = None,
	filters: str | dict | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
	timespan: str | None = None,
	time_interval: str | None = None,
	heatmap_year: int | str | None = None,
):
	from webshop.webshop.seo.score import google_status_label

	rows = frappe.get_list(
		"Website Item",
		filters={"published": 1, "sold": 0, "seo_score_checked_on": ("is", "set")},
		fields=["seo_google_status as status", "count(name) as products"],
		group_by="seo_google_status",
		order_by="products desc",
	)
	return {
		"labels": [google_status_label(row.status) for row in rows],
		"datasets": [{"name": _("Products"), "values": [row.products for row in rows]}],
		"type": "donut",
	}
