import json

import frappe

CARDS = [
	# label, doctype, filters
	("Open Sales Orders", "Sales Order", [["Sales Order", "docstatus", "=", 1], ["Sales Order", "status", "in", ["To Deliver and Bill", "To Bill", "To Deliver"]]]),
	("Open Pick Tasks", "Pick Task", [["Pick Task", "status", "in", ["Pending", "Picking"]]]),
	("Ready to Ship", "Shipment Task", [["Shipment Task", "status", "=", "Ready to Ship"]]),
	("Rejected Medusa Orders", "Medusa Intake Log", [["Medusa Intake Log", "outcome", "=", "Rejected"]]),
]

SHORTCUTS = [
	("Sales Order", "DocType", "Sales Order"),
	("Delivery Note", "DocType", "Delivery Note"),
	("Sales Invoice", "DocType", "Sales Invoice"),
	("Item", "DocType", "Item"),
	("Pick Task", "DocType", "Pick Task"),
	("Pack Task", "DocType", "Pack Task"),
	("Shipment Task", "DocType", "Shipment Task"),
	("Medusa Intake Log", "DocType", "Medusa Intake Log"),
	("Error Log", "DocType", "Error Log"),
	("API Request Log", "DocType", "API Request Log"),
]

# Shared by role, not by person (see PORTAL_INTERNAL_PROJECT.md). Doctype permissions still
# decide what each role can actually open from a shortcut or card.
ROLES = ["System Manager", "Sales User", "Stock User", "Accounts User", "Warehouse Operator"]


def _block(kind, data):
	return {"id": frappe.generate_hash(length=10), "type": kind, "data": data}


def execute():
	"""Create the KPI Number Cards for the `Soy Ops` workspace, which ships as a standard file
	(soypaq/workspace/soy_ops). Idempotent."""
	for label, doctype, filters in CARDS:
		if frappe.db.exists("Number Card", label):
			continue
		frappe.get_doc(
			{
				"doctype": "Number Card",
				"label": label,
				"name": label,
				"type": "Document Type",
				"document_type": doctype,
				"function": "Count",
				"filters_json": json.dumps(filters),
				"is_public": 1,
				"show_percentage_stats": 0,
				"module": "SoyPaq",
			}
		).insert(ignore_permissions=True)
