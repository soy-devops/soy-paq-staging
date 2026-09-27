import frappe

from soypaq import onboarding


def execute():
	"""Add the tenant fields to Customer and mark tenants that were set up by hand as onboarded."""
	onboarding.ensure_fields()
	for name in frappe.get_all("Customer", filters={"customer_group": onboarding.TENANT_GROUP}, pluck="name"):
		if frappe.db.exists("Company", name) and frappe.db.exists("Warehouse", {"company": name, "is_group": 1}):
			frappe.db.set_value("Customer", name, "soy_onboarded", 1, update_modified=False)
