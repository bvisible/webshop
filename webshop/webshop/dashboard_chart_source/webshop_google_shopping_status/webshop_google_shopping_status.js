//// Neoffice — added file (no upstream equivalent): see webshop_google_shopping_status.py (neoffice-maintenance#691).
frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["Webshop Google Shopping Status"] = {
	method: "webshop.webshop.dashboard_chart_source.webshop_google_shopping_status.webshop_google_shopping_status.get",
	filters: [],
};
