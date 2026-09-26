# //// Neoffice — added file (no upstream equivalent): the workspace chart of the products by band of
# //// SEO score. neoffice-maintenance#691, plan note 20 (part 1), 2026-09-26.
"""Published products by band of SEO score (seo/score.py BANDS): how much of the catalogue is
weak, fair or good. It reads the scores stored on the items, the ones the list shows."""

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
	from webshop.webshop.seo.score import BANDS, band_of

	values = [0] * len(BANDS)
	for score in frappe.get_list(
		"Website Item",
		filters={"published": 1, "sold": 0, "seo_score_checked_on": ("is", "set")},
		pluck="seo_score",
	):
		values[band_of(score)] += 1
	return {
		"labels": [f"{low}–{high}" for low, high in BANDS],
		"datasets": [{"name": _("Products"), "values": values}],
		"type": "bar",
	}
