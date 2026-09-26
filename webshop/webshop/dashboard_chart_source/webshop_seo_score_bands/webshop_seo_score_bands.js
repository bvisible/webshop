//// Neoffice — added file (no upstream equivalent): see webshop_seo_score_bands.py (neoffice-maintenance#691).
frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["Webshop SEO Score Bands"] = {
	method: "webshop.webshop.dashboard_chart_source.webshop_seo_score_bands.webshop_seo_score_bands.get",
	filters: [],
};
