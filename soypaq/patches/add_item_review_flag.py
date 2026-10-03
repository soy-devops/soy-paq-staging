import json

import frappe

from soypaq import traits

CARD = "Items Needing Review"


def execute():
	"""Add the Item review flag, flag items still in the provisional group, and create the Soy Ops count card.
	Idempotent."""
	traits.ensure_fields()
	frappe.clear_cache(doctype="Item")
	for item in frappe.get_all(
		"Item", filters={"item_group": "Provisional - Needs Review", "soy_needs_review": 0}, pluck="name"
	):
		frappe.db.set_value(
			"Item",
			item,
			{"soy_needs_review": 1, "soy_review_reason": "Not in the catalogue when it was received"},
			update_modified=False,
		)
	if not frappe.db.exists("Number Card", CARD):
		frappe.get_doc(
			{
				"doctype": "Number Card",
				"label": CARD,
				"name": CARD,
				"type": "Document Type",
				"document_type": "Item",
				"function": "Count",
				"filters_json": json.dumps([["Item", "soy_needs_review", "=", 1]]),
				"is_public": 1,
				"show_percentage_stats": 0,
				"module": "SoyPaq",
			}
		).insert(ignore_permissions=True)
