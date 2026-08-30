import frappe
from frappe.desk.doctype.desktop_icon.desktop_icon import clear_desktop_icons_cache


def after_install():
	"""Run on a fresh `bench install-app soypaq`.

	Patches only run when migrating an *existing* site - on a fresh install Frappe
	marks them as already-executed. Anything the app needs in order to work on a
	brand new site therefore has to live here, not in a patch.
	"""
	setup_desktop_icon()


def setup_desktop_icon():
	"""Create/refresh the SoyPaq WMS desktop icon. Idempotent."""
	values = {
		"label": "SoyPaq WMS",
		"icon_type": "App",
		"app": "soypaq",
		"link_type": "External",
		"link": "/soypaq-wms",
		"link_to": None,
		"logo_url": "/assets/soypaq/images/soypaq-wms-logo.svg",
		"parent_icon": None,
		"icon": None,
		"sidebar": None,
		"idx": 2,
		"standard": 0,
		"hidden": 0,
		"restrict_removal": 1,
	}
	icon_name = frappe.db.exists("Desktop Icon", {"label": "SoyPaq WMS"})
	if icon_name:
		frappe.db.set_value("Desktop Icon", icon_name, values, update_modified=False)
	else:
		frappe.get_doc({"doctype": "Desktop Icon", "name": "SoyPaq WMS", **values}).insert(
			ignore_permissions=True
		)
	clear_desktop_icons_cache()
