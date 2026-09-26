# //// Neoffice — added file (no upstream equivalent): the workspace's curve of the average SEO score,
# //// day by day. neoffice-maintenance#691, plan note 20 (part 1), 2026-09-26.
"""The shop's average SEO score on each day it was measured (Webshop SEO Snapshot, the night's
pass), over the last 90 days: one point per measured day, the sites of the instance averaged.

Frappe's own timeseries chart fills the days without a snapshot with 0, so the first weeks drew a
score rising from nothing to its value: only the days measured are drawn here."""

import frappe
from frappe import _
from frappe.utils import add_days, formatdate, nowdate
from frappe.utils.dashboard import cache_source

DAYS = 90


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
	rows = frappe.get_list(
		"Webshop SEO Snapshot",
		filters={"date": (">=", add_days(nowdate(), -DAYS)), "products": (">", 0)},
		fields=["date", "avg(average_score) as score"],
		group_by="date",
		order_by="date asc",
	)
	return {
		"labels": [formatdate(row.date) for row in rows],
		"datasets": [{"name": _("Average SEO score"), "values": [round(row.score or 0, 1) for row in rows]}],
		"type": "line",
	}
