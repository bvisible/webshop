#//// Neoffice — added file (no upstream equivalent).
#//// Two indexes on `tabItem Price` (price_list, selling, price_list_rate): our price
#//// slider and discount filter range-scan prices on every listing request, which
#//// upstream's listing never does (8ba1a7ab46, 2025-06-08 "enhance product filtering
#//// with stock availability and discount improvements").
import frappe

def execute():
	"""Add indexes to improve price filtering performance"""
	
	# Check if indexes already exist before creating them
	existing_indexes = frappe.db.sql("""
		SELECT INDEX_NAME 
		FROM INFORMATION_SCHEMA.STATISTICS 
		WHERE TABLE_SCHEMA = DATABASE() 
		AND TABLE_NAME = 'tabItem Price'
		AND INDEX_NAME IN ('idx_price_list_rate', 'idx_price_list_selling')
	""", as_dict=True)
	
	existing_index_names = [idx.INDEX_NAME for idx in existing_indexes]
	
	# Add index on price_list_rate for faster price range queries
	if 'idx_price_list_rate' not in existing_index_names:
		frappe.db.sql("""
			CREATE INDEX idx_price_list_rate 
			ON `tabItem Price` (price_list, selling, price_list_rate)
		""")
		frappe.db.commit()
		print("Added index idx_price_list_rate on Item Price table")
	
	# Add composite index for better query performance
	if 'idx_price_list_selling' not in existing_index_names:
		frappe.db.sql("""
			CREATE INDEX idx_price_list_selling 
			ON `tabItem Price` (price_list, selling, item_code, price_list_rate)
		""")
		frappe.db.commit()
		print("Added index idx_price_list_selling on Item Price table")