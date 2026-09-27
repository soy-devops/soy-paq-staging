import frappe
from frappe.permissions import add_permission, update_permission_property

# doctype -> permissions the Medusa bridge machine user needs, nothing more.
# Tenant scoping (Customer/Company) is done with User Permission on the bridge user.
BRIDGE_PERMS = {
	"Pick Task": ("read", "write", "create"),
	"Item": ("read",),
	"Warehouse": ("read",),
	"Bin": ("read",),
	"Customer": ("read",),
	"Company": ("read",),
}


def execute():
	"""Create the minimal `Medusa Bridge` role. Assigning it to the bridge user is a
	per-site step (IAM map), not done here."""
	if not frappe.db.exists("Role", "Medusa Bridge"):
		frappe.get_doc({"doctype": "Role", "role_name": "Medusa Bridge", "desk_access": 0}).insert(
			ignore_permissions=True
		)
	for doctype, ptypes in BRIDGE_PERMS.items():
		add_permission(doctype, "Medusa Bridge", 0)
		for ptype in ptypes:
			update_permission_property(doctype, "Medusa Bridge", 0, ptype, 1)
