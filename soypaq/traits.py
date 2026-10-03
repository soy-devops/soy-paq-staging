"""Item traits (product, color, size, collection) - the same four things Medusa calls the product
title, the variant options Color/Size, and the collection. ERPNext keeps them as plain Item fields so
filtering and search need no template/variant setup; item_group goes back to meaning product type."""

import re

import frappe

TRAIT_FIELDS = {
	"soy_product": "Product",
	"soy_color": "Color",
	"soy_size": "Size",
	"soy_collection": "Collection",
}
ACRONYMS = {"AFG"}
COLOR_CODES = {"BLK": "Black", "WHT": "White", "PNK": "Pink", "BLU": "Blue", "RED": "Red", "BLKWHT": "Black/White"}
TYPE_KEYWORDS = (
	("SWEATSHIRT", "Sweatshirts"),
	("HOODIE", "Sweatshirts"),
	("SWEATPANT", "Pants"),
	("PANT", "Pants"),
	("SHORT", "Shorts"),
	("TEE", "Tees"),
	("SHIRT", "Shirts"),
)
SIZES = {"XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL", "OS"}


def ensure_fields() -> None:
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	fields = [
		{"fieldname": "soy_traits_section", "fieldtype": "Section Break", "label": "Product Traits", "insert_after": "item_group"}
	]
	previous = "soy_traits_section"
	for fieldname, label in TRAIT_FIELDS.items():
		fields.append(
			{
				"fieldname": fieldname,
				"fieldtype": "Data",
				"label": label,
				"insert_after": previous,
				"in_standard_filter": 1,
				"search_index": 1,
			}
		)
		previous = fieldname
	fields.append(
		{
			"fieldname": "soy_max_order_qty",
			"fieldtype": "Int",
			"label": "Max Order Qty",
			"insert_after": previous,
			"description": "Store owner's cap on units per order from the portal. Blank/0 means no limit.",
			"non_negative": 1,
		}
	)
	fields += [
		{
			"fieldname": "soy_review_section",
			"fieldtype": "Section Break",
			"label": "Review",
			"insert_after": "soy_max_order_qty",
		},
		{
			"fieldname": "soy_needs_review",
			"fieldtype": "Check",
			"label": "Needs Review",
			"insert_after": "soy_review_section",
			"in_standard_filter": 1,
			"description": "Set when the floor flags this item (new at receive, wrong group, and so on). Untick once Soy Ops has checked it.",
		},
		{
			"fieldname": "soy_review_reason",
			"fieldtype": "Small Text",
			"label": "Review Reason",
			"insert_after": "soy_needs_review",
			"depends_on": "soy_needs_review",
		},
		{
			"fieldname": "soy_flagged_by",
			"fieldtype": "Link",
			"label": "Flagged By",
			"options": "User",
			"insert_after": "soy_review_reason",
			"read_only": 1,
			"depends_on": "soy_needs_review",
		},
	]
	create_custom_fields({"Item": fields}, update=True)


def _title(text: str) -> str:
	"""Title-case, but keep vowel-less acronyms (AFG, NYC, STL) upper."""
	return " ".join(w if w.upper() in ACRONYMS or not re.search(r"[AEIOUaeiou]", w) else w.title() for w in text.split())


def parse_name(item_name: str) -> dict:
	"""Best-effort split of "BASIC LOGO TEE PINK L" into product / color / size. Blanks stay blank."""
	tokens = (item_name or "").split()
	traits = {"soy_product": "", "soy_color": "", "soy_size": "", "soy_collection": ""}
	if tokens and tokens[-1].upper() in SIZES:
		traits["soy_size"] = tokens.pop().upper()
	if "TEE" in [t.upper() for t in tokens]:
		cut = [t.upper() for t in tokens].index("TEE") + 1
		traits["soy_product"] = _title(" ".join(tokens[:cut]))
		traits["soy_color"] = _title(" ".join(tokens[cut:]))
	else:
		traits["soy_product"] = _title(" ".join(tokens))
	return traits


def color_from_code(item_code: str) -> str:
	"""Color from an item code such as EXC-BLK-BT01-L or EXC-TEE-BLU-M (first segment that is a known color)."""
	for part in (item_code or "").upper().split("-")[1:]:
		if part in COLOR_CODES:
			return COLOR_CODES[part]
	return ""


def product_type(name: str) -> str:
	"""Product type an item_group should mean (Tees, Shorts, ...), from the product name."""
	upper = (name or "").upper()
	return next((group for keyword, group in TYPE_KEYWORDS if keyword in upper), "Apparel")


def normalize_item_groups() -> int:
	"""Make item_group mean product type under the tenant's own group (Example Client > Example Client - Tees).

	A season-style group (Summer_2026) moves into the Collection trait instead. Idempotent; only touches
	items still sitting in a group named like <Word>_<year>. Stock, bins and item codes are untouched.
	"""
	moved = 0
	for item in frappe.get_all("Item", fields=["name", "item_name", "item_group", "soy_product", "soy_collection"]):
		if not re.fullmatch(r"[A-Za-z]+_\d{4}", item.item_group or ""):
			continue
		tenant = frappe.db.get_value("Item Group", item.item_group, "parent_item_group")
		if not tenant or tenant == "All Item Groups":
			continue
		group = f"{tenant} - {product_type(item.soy_product or item.item_name)}"
		if not frappe.db.exists("Item Group", group):
			frappe.get_doc(
				{"doctype": "Item Group", "item_group_name": group, "parent_item_group": tenant, "is_group": 0}
			).insert(ignore_permissions=True)
		update = {"item_group": group}
		if not item.soy_collection:
			update["soy_collection"] = item.item_group.replace("_", " ")
		frappe.db.set_value("Item", item.name, update, update_modified=False)
		moved += 1
	return moved


def backfill() -> int:
	"""Fill empty traits from the item name and the old season group. Never overwrites a value."""
	count = 0
	for item in frappe.get_all("Item", fields=["name", "item_name", "item_group"] + list(TRAIT_FIELDS)):
		guess = parse_name(item.item_name)
		guess["soy_collection"] = re.sub(r"_", " ", item.item_group or "") if re.search(r"\d{4}", item.item_group or "") else ""
		if not guess["soy_color"]:
			guess["soy_color"] = color_from_code(item.name)
		update = {k: v for k, v in guess.items() if v and not item.get(k)}
		if update:
			frappe.db.set_value("Item", item.name, update, update_modified=False)
			count += 1
	return count


@frappe.whitelist()
def apply_medusa_products(products) -> dict:
	"""Receive Medusa products and stamp traits on matching Items (variant SKU == Item Code, the Phase 1 rule).

	`products`: [{"title", "collection": {"title"}, "variants": [{"sku", "options": [{"option": {"title"}, "value"}]}]}]
	Option titles are matched case-insensitively (Color/Colour, Size). Unknown SKUs are reported, not created.
	"""
	frappe.only_for(("System Manager", "Stock Manager", "Medusa Bridge"))
	products = frappe.parse_json(products) or []
	updated, unknown = 0, []
	for product in products:
		collection = ((product.get("collection") or {}).get("title")) or ""
		for variant in product.get("variants") or []:
			sku = variant.get("sku")
			if not sku or not frappe.db.exists("Item", sku):
				unknown.append(sku)
				continue
			options = {}
			for opt in variant.get("options") or []:
				title = ((opt.get("option") or {}).get("title") or opt.get("title") or "").lower()
				options[title] = opt.get("value")
			values = {
				"soy_product": product.get("title"),
				"soy_color": options.get("color") or options.get("colour"),
				"soy_size": options.get("size"),
				"soy_collection": collection,
			}
			values = {k: v for k, v in values.items() if v}
			if values:
				frappe.db.set_value("Item", sku, values, update_modified=False)
				updated += 1
	return {"updated": updated, "unknown_skus": unknown}
