import frappe


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.throw("Log in to use the SoyPaq WMS app.", frappe.PermissionError)
	context.no_cache = 1
	return context
