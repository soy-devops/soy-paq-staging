def execute():
	"""No-op.

	`shipping_label_url` and `shippo_transaction_id` are now real fields declared in
	shipment_task.json, so they ship with the DocType itself. Kept as a no-op so the
	patch entry stays resolvable for sites that already recorded it.
	"""
	pass
