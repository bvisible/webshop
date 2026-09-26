//// Neoffice — added file (no upstream equivalent): see webshop_seo_score_history.py (neoffice-maintenance#691).
frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["Webshop SEO Score History"] = {
	method: "webshop.webshop.dashboard_chart_source.webshop_seo_score_history.webshop_seo_score_history.get",
	filters: [],
};
