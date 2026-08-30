import frappe
from frappe.utils import flt


def execute():
	"""Backfill WMS tracking data on sites that predate these fields.

	The fields themselves (company/supplier/purchase_order, assigned_user,
	box_confirmed, packed_qty, exception_reason, received_qty, assigned_bin) are now
	real DocType fields declared in the app's doctype JSON, so this patch no longer
	creates Custom Fields - it only backfills values for existing records.
	"""
	_initialize_inbound_companies()
	_initialize_pack_quantities()
	_initialize_task_operators()


def _initialize_inbound_companies():
	for asn in frappe.get_all("Inbound ASN", fields=["name", "target_warehouse", "company"]):
		if asn.company or not asn.target_warehouse:
			continue
		company = frappe.db.get_value("Warehouse", asn.target_warehouse, "company")
		if company:
			frappe.db.set_value("Inbound ASN", asn.name, "company", company, update_modified=False)


def _initialize_pack_quantities():
	for task_name in frappe.get_all("Pack Task", pluck="name"):
		task = frappe.get_doc("Pack Task", task_name)
		remaining = flt(task.get("total_packed_qty"))
		for row in task.get("pick_items") or []:
			packed = min(flt(row.get("picked_qty")), remaining)
			frappe.db.set_value("Pack Task Item", row.name, "packed_qty", packed, update_modified=False)
			remaining = max(remaining - packed, 0)


def _initialize_task_operators():
	for task in frappe.get_all("Pack Task", fields=["name", "warehouse", "assigned_user"]):
		if task.assigned_user or not task.warehouse:
			continue
		assigned_user = frappe.db.get_value("Pick Task", task.warehouse, "assigned_to")
		if assigned_user:
			frappe.db.set_value("Pack Task", task.name, "assigned_user", assigned_user, update_modified=False)

	for task in frappe.get_all("Shipment Task", fields=["name", "warehouse", "assigned_user"]):
		if task.assigned_user or not task.warehouse:
			continue
		assigned_user = frappe.db.get_value("Pack Task", task.warehouse, "assigned_user")
		if assigned_user:
			frappe.db.set_value(
				"Shipment Task", task.name, "assigned_user", assigned_user, update_modified=False
			)
