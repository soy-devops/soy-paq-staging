"""Access guard for the SoyPaq WMS surface.

The WMS routes in `soypaq.api` read with elevated permissions, so Frappe's normal
DocPerm checks do not protect them. This is the single seam that decides who may
call them or load the WMS page, so portal roles (Customer Admin/Staff) and
finance/HR users never reach warehouse data.

Decision (2026-09-19): the `/soypaq-wms` page shell is static and holds no data, so it
is deliberately left reachable by non-warehouse users and Guests. The data routes above
are the security boundary, not the shell. Do not add shell-level blocking without
revisiting this note.
"""

from __future__ import annotations

import frappe

WMS_ROLES = {"Warehouse Operator", "Stock User", "Stock Manager", "System Manager"}
WMS_API_PREFIX = "/api/method/soypaq.api."


def has_wms_access(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(WMS_ROLES & set(frappe.get_roles(user)))


def require_wms_access() -> None:
	if not has_wms_access():
		frappe.throw("You do not have access to the SoyPaq WMS.", frappe.PermissionError)


def guard_wms_api() -> None:
	"""auth_hook (runs after auth resolves the user). Guests are left to each route's own auth (the Medusa
	bridge authenticates with a shared secret as Guest)."""
	request = getattr(frappe.local, "request", None)
	if not request or not request.path.startswith(WMS_API_PREFIX):
		return
	if frappe.session.user == "Guest":
		return
	require_wms_access()


def medusa_intake_log_query_conditions(user: str | None = None) -> str:
	"""permission_query_condition: a blank `customer` means the intake couldn't be routed to a
	tenant (ambiguous SKU, bridge-level reject). Frappe's automatic User Permission filtering only
	restricts rows where the link field has a value, so a blank customer would otherwise be visible
	to every role that can read the doctype, including a future tenant-scoped role. Restrict those
	rows to System Manager until the row has a customer."""
	user = user or frappe.session.user
	if "System Manager" in frappe.get_roles(user):
		return ""
	return "`tabMedusa Intake Log`.customer is not null and `tabMedusa Intake Log`.customer != ''"
