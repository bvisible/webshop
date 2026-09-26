# //// Neoffice — added file (no upstream equivalent): every product's first SEO score, in the
# //// background, so that the workspace's cards and charts say something before the first night
# //// (seo/score.py, neoffice-maintenance#691, plan note 20, 2026-09-26).
import frappe


def execute():
	frappe.enqueue(
		"webshop.webshop.seo.score.refresh_all",
		queue="long",
		timeout=3600,
		enqueue_after_commit=True,
	)
