//// Neoffice — added file (no upstream equivalent): the visits that came from an AI assistant
//// (webshop/webshop/seo/ai_referrals.py, neoffice-maintenance#691 lot 4).
frappe.query_reports["Visits From AI Assistants"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.add_days(frappe.datetime.get_today(), -30), reqd: 1 },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "group_by", label: __("Group By"), fieldtype: "Select", options: "Assistant\nPage\nDay", default: "Assistant" },
	],
};
