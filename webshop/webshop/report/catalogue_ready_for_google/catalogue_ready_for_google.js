// //// Neoffice — added file (no upstream equivalent): see catalogue_ready_for_google.py
// //// (neoffice-maintenance#691, lot 6).
frappe.query_reports["Catalogue Ready for Google"] = {
	filters: [
		{
			fieldname: "site",
			label: __("Site"),
			fieldtype: "Select",
			options: [""],
		},
		{
			fieldname: "show",
			label: __("Show"),
			fieldtype: "Select",
			options: [
				{ value: "All", label: __("All") },
				{ value: "Sent", label: __("Sent to Google") },
				{ value: "Left out", label: __("Left out") },
				{ value: "Suggestions", label: __("With suggestions") },
			],
			default: "All",
		},
		{
			fieldname: "website_item",
			label: __("Website Item"),
			fieldtype: "Link",
			options: "Website Item",
		},
	],
	onload(report) {
		// the sites a feed is written for: one per Website Profile with a domain, else the instance's
		frappe.call("webshop.webshop.report.catalogue_ready_for_google.catalogue_ready_for_google.sites").then((r) => {
			const filter = report.get_filter("site");
			const sites = r.message || [];
			filter.df.options = sites.map((site) => ({ value: site.key, label: site.label }));
			filter.df.hidden = sites.length < 2;
			filter.refresh();
			if (!filter.get_value() && sites.length) filter.set_input(sites[0].key);
		});
	},
};
