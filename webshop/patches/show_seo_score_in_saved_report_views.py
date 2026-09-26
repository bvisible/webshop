# //// Neoffice — added file (no upstream equivalent): the SEO score among the saved columns of the
# //// Website Item report view. neoffice-maintenance#691, plan note 20, 2026-09-26.
"""The desk opens the Website Item list in its report view, with the columns each user saved. The
score is one of the view's default columns, but a user who had saved columns before it existed
never saw it: it is added once to what they saved, at the end."""

import json

import frappe

DOCTYPE = "Website Item"
COLUMN = ["seo_score", DOCTYPE]


def execute():
	if not frappe.get_meta(DOCTYPE).has_field("seo_score"):
		return
	from frappe.model.utils.user_settings import sync_user_settings

	# what browsers saved since the last hourly sync is still in the cache: to the table first
	sync_user_settings()
	for row in frappe.db.sql(
		"select `user`, `data` from `__UserSettings` where `doctype` = %s", DOCTYPE, as_dict=True
	):
		data = with_seo_score(row.data)
		if data is None:
			continue
		frappe.db.sql(
			"update `__UserSettings` set `data` = %s where `user` = %s and `doctype` = %s",
			(data, row.user, DOCTYPE),
		)
		# the view reads the cache first
		frappe.cache.hdel("_user_settings", f"{DOCTYPE}::{row.user}")


def with_seo_score(data):
	"""The saved settings with the score among the report view's columns, or None when there is
	nothing to change: no saved columns (the view shows its defaults, the score among them), the
	score already there, or settings nobody can read."""
	try:
		settings = json.loads(data or "{}")
	except ValueError:
		return None
	report = settings.get("Report") if isinstance(settings, dict) else None
	fields = report.get("fields") if isinstance(report, dict) else None
	if not isinstance(fields, list) or not fields:
		return None
	if any(isinstance(field, list | tuple) and field and field[0] == COLUMN[0] for field in fields):
		return None
	fields.append(list(COLUMN))
	return json.dumps(settings)
