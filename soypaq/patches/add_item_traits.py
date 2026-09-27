from soypaq import traits


def execute():
	"""Add Product/Color/Size/Collection to Item and fill them from names and the old season group."""
	traits.ensure_fields()
	traits.backfill()
