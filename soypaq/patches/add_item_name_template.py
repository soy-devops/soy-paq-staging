import frappe

from soypaq import onboarding


def execute():
	"""Customer gains Item Name Template (default `{PRODUCT} {COLOR} {SIZE}`), used when the floor adds an item."""
	onboarding.ensure_fields()
	frappe.clear_cache(doctype="Customer")
