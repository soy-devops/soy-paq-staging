from soypaq import traits


def execute():
	"""Season-style item groups (Summer_2026) become product-type groups; the season lives in Collection."""
	traits.backfill()
	traits.normalize_item_groups()
