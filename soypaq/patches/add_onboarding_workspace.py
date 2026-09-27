import json

import frappe

CARDS = [
	("3PL Clients", [["Customer", "customer_group", "=", "3PL Client"]]),
	("Clients Awaiting Setup", [["Customer", "customer_group", "=", "3PL Client"], ["Customer", "soy_onboarded", "=", 0]]),
]


def execute():
	"""Create the KPI Number Cards for the `Customer Onboarding` workspace, which ships as a
	standard file (soypaq/workspace/customer_onboarding). Idempotent."""
	for label, filters in CARDS:
		if frappe.db.exists("Number Card", label):
			continue
		frappe.get_doc(
			{
				"doctype": "Number Card",
				"label": label,
				"name": label,
				"type": "Document Type",
				"document_type": "Customer",
				"function": "Count",
				"filters_json": json.dumps(filters),
				"is_public": 1,
				"show_percentage_stats": 0,
				"module": "SoyPaq",
			}
		).insert(ignore_permissions=True)
