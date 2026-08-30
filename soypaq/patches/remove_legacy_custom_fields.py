import frappe

LEGACY = {
	"Inbound ASN": ["company", "supplier", "purchase_order"],
	"Inbound Package Item": ["received_qty", "assigned_bin"],
	"Pack Task": ["assigned_user", "box_confirmed"],
	"Pack Task Item": ["packed_qty"],
	"Pick Task Item": ["exception_reason"],
	"Shipment Task": ["assigned_user", "shipping_label_url", "shippo_transaction_id"],
}


def execute():
	"""Delete Custom Fields that are now real fields on the DocType itself.

	Runs in pre_model_sync so the Custom Field rows are gone *before* the DocType
	JSON is synced - otherwise the same fieldname would be defined twice. Column data
	is untouched: the DocType sync re-declares the identical column, so values
	already stored in those columns survive.
	"""
	for doctype, fieldnames in LEGACY.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		for fieldname in fieldnames:
			name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname})
			if name:
				frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
	frappe.clear_cache()
