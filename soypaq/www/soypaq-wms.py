import frappe

from soypaq.security import require_wms_access


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.throw("Log in to use the SoyPaq WMS app.", frappe.PermissionError)
	require_wms_access()
	context.no_cache = 1
	return context
