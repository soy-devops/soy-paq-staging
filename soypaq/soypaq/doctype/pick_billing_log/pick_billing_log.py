from frappe.model.document import Document


class PickBillingLog(Document):
	"""Read-only audit row: what billing did for one completed Pick Task. Written by soypaq.billing only."""
