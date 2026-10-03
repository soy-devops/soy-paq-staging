from __future__ import annotations

import json
import re
from urllib.parse import quote

import frappe
from soypaq.billing import bill_completed_pick
from frappe.utils import cint, flt, now_datetime

from soypaq import medusa_client

MOBILE_DOCTYPES = {
	"Inbound ASN",
	"Inbound Package",
	"Pick Task",
	"Pack Task",
	"Shipment Task",
}


def _route(doctype: str, name: str) -> str:
	return f"/desk/{frappe.scrub(doctype).replace('_', '-')}/{quote(name)}"


def _get_doc(doctype: str, filters: dict | None = None):
	name = frappe.db.get_value(doctype, filters or {}, "name", order_by="modified desc")
	return frappe.get_doc(doctype, name) if name else None


DONE_STATUSES = {
	"Pick Task": ["Completed", "Cancelled"],
	"Pack Task": ["Completed", "Cancelled"],
	"Shipment Task": ["Shipped", "Cancelled"],
	"Inbound Package": ["Stored", "Consolidated", "Shipped", "Delivered", "Cancelled"],
}


def _select_doc(doctype: str, name: str | None = None):
	"""Resolve which document the mobile app should show in detail.

	An explicit `name` (the operator picked a specific record from a list) always
	wins. Otherwise prefer the most recently modified *unfinished* record, so a
	just-finished task doesn't keep hogging the "current" slot - falling back to
	the most recent record overall only when nothing is left in progress.
	"""
	if name:
		return frappe.get_doc(doctype, name) if frappe.db.exists(doctype, name) else None
	done = DONE_STATUSES.get(doctype, ["Completed", "Cancelled"])
	unfinished = frappe.db.get_value(doctype, {"status": ["not in", done]}, "name", order_by="modified desc")
	if unfinished:
		return frappe.get_doc(doctype, unfinished)
	return _get_doc(doctype)


def _first_item_images(child_doctype: str, parent_names: list[str]) -> dict[str, str | None]:
	"""First line item's image per parent - a representative thumbnail for task-list rows."""
	if not parent_names:
		return {}
	rows = frappe.get_all(
		child_doctype,
		filters={"parent": ["in", parent_names]},
		fields=["parent", "item_code", "idx"],
		order_by="parent asc, idx asc",
	)
	first_item_by_parent: dict[str, str] = {}
	for row in rows:
		first_item_by_parent.setdefault(row.parent, row.item_code)
	item_codes = list(set(first_item_by_parent.values()))
	images = (
		{
			i.name: i.image
			for i in frappe.get_all("Item", filters={"name": ["in", item_codes]}, fields=["name", "image"])
		}
		if item_codes
		else {}
	)
	return {parent: images.get(item_code) for parent, item_code in first_item_by_parent.items()}


def _list_shipment_tasks(limit: int = 50) -> list[dict]:
	rows = frappe.get_all(
		"Shipment Task",
		filters={"status": ["!=", "Cancelled"]},
		fields=[
			"name",
			"sales_order",
			"customer",
			"status",
			"carrier",
			"tracking_number",
			"modified",
			"creation",
			"warehouse",
			"assigned_user",
			"total_required_qty",
			"total_packed_qty",
			"total_shipped_qty",
		],
		order_by="modified desc",
		limit_page_length=limit,
	)
	images = _first_item_images("Shipment Task Item", [r.name for r in rows])
	return [
		{
			"name": r.name,
			"reference": r.sales_order or r.name,
			"customer": r.customer or "",
			"status": r.status or "Ready to Ship",
			"assigned_to": _user(r.assigned_user),
			"carrier": r.carrier or "",
			"tracking_number": r.tracking_number or "",
			"pack_task": r.warehouse or "",
			"total_required_qty": flt(r.total_required_qty),
			"total_packed_qty": flt(r.total_packed_qty),
			"total_shipped_qty": flt(r.total_shipped_qty),
			"image": images.get(r.name),
			"modified": str(r.modified),
			"created": str(r.creation),
			"route": _route("Shipment Task", r.name),
		}
		for r in rows
	]


def _list_receive_packages(limit: int = 50) -> list[dict]:
	rows = frappe.get_all(
		"Inbound Package",
		filters={"status": ["not in", ["Exception", "Cancelled"]]},
		fields=[
			"name",
			"external_tracking_number",
			"customer",
			"assigned_user",
			"status",
			"carrier",
			"modified",
			"creation",
			"target_warehouse",
			"inbound_asn",
		],
		order_by="modified desc",
		limit_page_length=limit,
	)
	counts = {}
	first_item_by_parent: dict[str, str] = {}
	if rows:
		for child in frappe.get_all(
			"Inbound Package Item",
			filters={"parent": ["in", [r.name for r in rows]]},
			fields=["parent", "item_code", "idx", "quantity", "received_qty", "assigned_bin", "condition"],
			order_by="parent asc, idx asc",
			limit_page_length=0,
		):
			bucket = counts.setdefault(child.parent, {"lines": 0, "confirmed": 0, "staged": 0, "expected": 0})
			bucket["lines"] += 1
			bucket["expected"] += flt(child.quantity)
			if flt(child.received_qty) >= flt(child.quantity) or child.condition == "Missing":
				bucket["confirmed"] += 1
			if child.assigned_bin or child.condition == "Missing":
				bucket["staged"] += 1
			first_item_by_parent.setdefault(child.parent, child.item_code)
	item_codes = list(set(first_item_by_parent.values()))
	item_images = (
		{
			i.name: i.image
			for i in frappe.get_all("Item", filters={"name": ["in", item_codes]}, fields=["name", "image"])
		}
		if item_codes
		else {}
	)
	return [
		{
			"name": r.name,
			"reference": r.external_tracking_number or r.name,
			"customer": r.customer or "",
			"status": r.status or "Received",
			"carrier": r.carrier or "",
			"target_warehouse": r.target_warehouse or "",
			"asn": r.inbound_asn or "",
			"assigned_to": _user(r.assigned_user),
			"lines": counts.get(r.name, {}).get("lines", 0),
			"expected_qty": counts.get(r.name, {}).get("expected", 0),
			"confirmed_lines": counts.get(r.name, {}).get("confirmed", 0),
			"staged_lines": counts.get(r.name, {}).get("staged", 0),
			"image": item_images.get(first_item_by_parent.get(r.name)),
			"modified": str(r.modified),
			"created": str(r.creation),
			"route": _route("Inbound Package", r.name),
		}
		for r in rows
	]


def _shipment_chain(shipment_task) -> dict:
	"""Trace a shipment back through its Pack Task and Pick Task.

	Lets the shipment detail screen show who actually picked, packed and shipped an
	order using real linked records rather than restating the shipment's own fields.
	"""
	if not shipment_task:
		return {}
	pack_name = shipment_task.get("warehouse") or ""
	pack = None
	pick = None
	if pack_name and frappe.db.exists("Pack Task", pack_name):
		pack = frappe.db.get_value(
			"Pack Task",
			pack_name,
			[
				"name",
				"warehouse",
				"assigned_user",
				"completed_by",
				"completed_at",
				"tracking_number",
				"status",
			],
			as_dict=True,
		)
		if pack and pack.warehouse and frappe.db.exists("Pick Task", pack.warehouse):
			pick = frappe.db.get_value(
				"Pick Task",
				pack.warehouse,
				["name", "assigned_to", "completed_by", "completed_at", "status"],
				as_dict=True,
			)
	sales_order = shipment_task.get("sales_order") or ""
	order_date = None
	if sales_order and frappe.db.exists("Sales Order", sales_order):
		order_date = frappe.db.get_value("Sales Order", sales_order, "transaction_date")

	# Real, timestamped audit trail assembled from the linked records themselves -
	# each entry only appears once the underlying document actually recorded it.
	history = []
	if order_date:
		history.append(
			{"label": "Order received", "actor": sales_order, "at": str(order_date), "note": "Online order"}
		)
	else:
		history.append(
			{
				"label": "Task created",
				"actor": shipment_task.name,
				"at": str(shipment_task.get("creation") or ""),
				"note": "Manual entry",
			}
		)
	if pick and pick.completed_at:
		history.append(
			{
				"label": "Picked",
				"actor": _user(pick.completed_by or pick.assigned_to)["name"],
				"at": str(pick.completed_at),
				"note": pick.name,
			}
		)
	if pack and pack.completed_at:
		history.append(
			{
				"label": "Packed",
				"actor": _user(pack.completed_by or pack.assigned_user)["name"],
				"at": str(pack.completed_at),
				"note": pack.tracking_number or pack.name,
			}
		)
	if shipment_task.get("shipped_at"):
		history.append(
			{
				"label": "Shipped",
				"actor": _user(shipment_task.get("shipped_by"))["name"],
				"at": str(shipment_task.get("shipped_at")),
				"note": f"{shipment_task.get('carrier') or 'Carrier'} - {shipment_task.get('tracking_number') or 'no tracking'}",
			}
		)

	# Per-line provenance from the originating Pick Task: short picks, damage and
	# other exceptions recorded during picking travel with the shipment.
	item_notes = {}
	if pick:
		for row in frappe.get_all(
			"Pick Task Item",
			filters={"parent": pick.name},
			fields=["item_code", "required_qty", "picked_qty", "status", "exception_reason"],
			limit_page_length=0,
		):
			short = flt(row.required_qty) - flt(row.picked_qty)
			item_notes[row.item_code] = {
				"pick_status": row.status or "",
				"exception_reason": row.exception_reason or "",
				"short_qty": short if short > 0 else 0,
			}

	return {
		"order_type": "Online order" if sales_order else "Manual entry",
		"sales_order": sales_order,
		"order_route": _route("Sales Order", sales_order) if sales_order else "",
		"pick_task": pick.name if pick else "",
		"pick_route": _route("Pick Task", pick.name) if pick else "",
		"picked_by": _user((pick.completed_by or pick.assigned_to) if pick else None),
		"picked_at": pick.completed_at if pick else None,
		"pack_task": pack.name if pack else "",
		"pack_route": _route("Pack Task", pack.name) if pack else "",
		"packed_by": _user((pack.completed_by or pack.assigned_user) if pack else None),
		"packed_at": pack.completed_at if pack else None,
		"container": pack.tracking_number if pack else "",
		"shipped_by": _user(shipment_task.get("shipped_by")),
		"shipped_at": shipment_task.get("shipped_at"),
		"history": history,
		"item_notes": item_notes,
	}


def _list_pick_tasks(limit: int = 50) -> list[dict]:
	rows = frappe.get_all(
		"Pick Task",
		filters={"status": ["!=", "Cancelled"]},
		fields=[
			"name",
			"sales_order",
			"customer",
			"status",
			"assigned_to",
			"modified",
			"creation",
			"total_required_qty",
			"total_picked_qty",
		],
		order_by="modified desc",
		limit_page_length=limit,
	)
	pack_links = {}
	if rows:
		pack_links = {
			r.warehouse: r.name
			for r in frappe.get_all(
				"Pack Task",
				fields=["name", "warehouse"],
				filters={"warehouse": ["in", [r.name for r in rows]]},
			)
		}
	images = _first_item_images("Pick Task Item", [r.name for r in rows])
	return [
		{
			"name": r.name,
			"reference": r.sales_order or r.name,
			"customer": r.customer or "",
			"status": r.status or "Pending",
			"assigned_to": _user(r.assigned_to),
			"total_required_qty": flt(r.total_required_qty),
			"total_picked_qty": flt(r.total_picked_qty),
			"pack_task": pack_links.get(r.name, ""),
			"image": images.get(r.name),
			"modified": str(r.modified),
			"created": str(r.creation),
			"route": _route("Pick Task", r.name),
		}
		for r in rows
	]


def _list_pack_tasks(limit: int = 50) -> list[dict]:
	rows = frappe.get_all(
		"Pack Task",
		filters={"status": ["!=", "Cancelled"]},
		fields=[
			"name",
			"sales_order",
			"customer",
			"status",
			"warehouse",
			"assigned_user",
			"modified",
			"creation",
			"total_required_qty",
			"total_packed_qty",
		],
		order_by="modified desc",
		limit_page_length=limit,
	)
	ship_links = {}
	if rows:
		ship_links = {
			r.warehouse: r.name
			for r in frappe.get_all(
				"Shipment Task",
				fields=["name", "warehouse"],
				filters={"warehouse": ["in", [r.name for r in rows]]},
			)
		}
	images = _first_item_images("Pack Task Item", [r.name for r in rows])
	return [
		{
			"name": r.name,
			"reference": r.sales_order or r.name,
			"customer": r.customer or "",
			"status": r.status or "Pending",
			"assigned_to": _user(r.assigned_user),
			"total_required_qty": flt(r.total_required_qty),
			"total_packed_qty": flt(r.total_packed_qty),
			"pick_task": r.warehouse or "",
			"shipment_task": ship_links.get(r.name, ""),
			"image": images.get(r.name),
			"modified": str(r.modified),
			"created": str(r.creation),
			"route": _route("Pack Task", r.name),
		}
		for r in rows
	]


def _count(doctype: str) -> int:
	return frappe.db.count(doctype) if frappe.db.exists("DocType", doctype) else 0


def _open_count(doctype: str) -> int:
	"""Count records still needing operator work.

	The home tiles are a worklist, not an archive - counting every record ever
	created made a fully-cleared stage still show a badge.
	"""
	if not frappe.db.exists("DocType", doctype):
		return 0
	done = DONE_STATUSES.get(doctype, ["Completed", "Cancelled"])
	return frappe.db.count(doctype, {"status": ["not in", [*done, "Cancelled"]]})


def _user(user: str | None) -> dict:
	if not user:
		return {"id": "", "name": "Unassigned"}
	return {
		"id": user,
		"name": frappe.db.get_value("User", user, "full_name") or user,
	}


def _operator_info() -> dict:
	"""Real signed-in identity for the header - not a hardcoded placeholder.

	`role` picks the WMS-relevant role out of the user's full role list (Administrator
	holds nearly every role in the system, so "first role" isn't meaningful) rather than
	always claiming "Warehouse Operator" regardless of who is actually logged in.
	"""
	user = frappe.session.user
	name = frappe.db.get_value("User", user, "full_name") or user
	roles = frappe.get_roles(user)
	if "Warehouse Operator" in roles:
		role = "Warehouse Operator"
	elif "System Manager" in roles:
		role = "System Manager"
	else:
		role = "No WMS role assigned"
	return {"id": user, "name": name, "role": role}


def _warehouse_company(warehouse: str | None) -> str:
	return frappe.db.get_value("Warehouse", warehouse, "company") if warehouse else ""


DEFAULT_COMPANY = "Example Company"


def _setting(fieldname: str):
	"""Read one SoyPaq Settings value; None if unset or the doctype is not migrated yet."""
	try:
		return frappe.db.get_single_value("SoyPaq Settings", fieldname) or None
	except Exception:
		return None


_DEFAULT_WAREHOUSE_EXCLUDE = ("Damaged", "Returns")


def _default_warehouse(zone: str | None = None) -> str | None:
	"""Pick a real, working leaf warehouse under the default company.

	`zone` narrows to a specific area by warehouse_name substring (e.g. "Receiving",
	"Storage"). Without it, exception zones (Damaged/Returns) are skipped - they are
	never a sensible default source or destination for a manually created task.
	"""
	filters = {"is_group": 0, "disabled": 0, "company": _setting("default_company") or DEFAULT_COMPANY}
	if zone:
		filters["warehouse_name"] = ["like", f"%{zone}%"]
		return frappe.db.get_value("Warehouse", filters, "name", order_by="name asc")
	for row in frappe.get_all(
		"Warehouse", filters=filters, fields=["name", "warehouse_name"], order_by="name asc"
	):
		if not any(exclude in (row.warehouse_name or "") for exclude in _DEFAULT_WAREHOUSE_EXCLUDE):
			return row.name
	return None


def _create_stock_entry(entry_type: str, items: list[dict], company: str | None = None):
	"""Post a real, submitted Stock Entry. This is where inventory actually moves.

	`items` rows: item_code, qty, uom (optional), s_warehouse (optional), t_warehouse (optional).
	Raises frappe.ValidationError (e.g. insufficient stock in a source bin) exactly like any
	other ERPNext stock move - callers are not expected to swallow that, a blocked stock move
	should block the operator action that triggered it.
	"""
	if not items:
		return None
	ref_warehouse = items[0].get("t_warehouse") or items[0].get("s_warehouse")
	doc = frappe.new_doc("Stock Entry")
	doc.stock_entry_type = entry_type
	doc.company = company or _warehouse_company(ref_warehouse)
	if not doc.company:
		frappe.throw("Could not determine which company this stock move belongs to.")
	for item in items:
		row = {
			"item_code": item["item_code"],
			"qty": item["qty"],
			"uom": item.get("uom") or frappe.db.get_value("Item", item["item_code"], "stock_uom"),
			"s_warehouse": item.get("s_warehouse"),
			"t_warehouse": item.get("t_warehouse"),
		}
		# Received stock is the client's, not Soy's: an item with no cost yet (a new item, price 0 by
		# default) is received at zero value instead of blocking the receipt. Same rule as adjust_bin_qty.
		if entry_type == "Material Receipt" and not flt(frappe.db.get_value("Item", item["item_code"], "valuation_rate")):
			row["allow_zero_valuation_rate"] = 1
		doc.append("items", row)
	doc.insert()
	doc.submit()
	return doc


def _create_delivery_note(
	customer: str, items: list[dict], company: str | None = None, sales_order: str | None = None
):
	"""Post a real, submitted Delivery Note. This is the actual stock-out and shipment record.

	`items` rows: item_code, qty, warehouse, uom (optional). When `sales_order` is given
	and a matching Sales Order Item line exists for that item, the row links to it
	(against_sales_order / so_detail) so the source order's delivered-qty stays in sync.
	"""
	if not items:
		frappe.throw("Nothing was packed on this shipment - nothing to ship.")
	ref_warehouse = items[0].get("warehouse")
	doc = frappe.new_doc("Delivery Note")
	doc.customer = customer
	doc.company = company or _warehouse_company(ref_warehouse)
	if not doc.company:
		frappe.throw("Could not determine which company this shipment belongs to.")
	for item in items:
		rate = flt(frappe.db.get_value("Item", item["item_code"], "valuation_rate"))
		row = {
			"item_code": item["item_code"],
			"qty": item["qty"],
			"uom": item.get("uom") or frappe.db.get_value("Item", item["item_code"], "stock_uom"),
			"warehouse": item["warehouse"],
			"rate": rate,
		}
		if not rate:
			# No valuation rate exists yet for this item (common for test/demo stock that was
			# never bought through a real Purchase Receipt) - ERPNext blocks a zero-rate line by
			# default, so explicitly allow it rather than silently failing at ship time. Once real
			# Sales Orders carry real pricing (see PROJECT.md roadmap), rate should come from there.
			row["allow_zero_valuation_rate"] = 1
		if sales_order:
			so_detail = frappe.db.get_value(
				"Sales Order Item", {"parent": sales_order, "item_code": item["item_code"]}, "name"
			)
			if so_detail:
				row["against_sales_order"] = sales_order
				row["so_detail"] = so_detail
		doc.append("items", row)
	doc.insert()
	doc.submit()
	return doc


def _suffix_bin(code: str, company: str | None = None) -> str | None:
	"""A short bin code (A01) as a bin's suffix. The same code exists per customer, so more than one
	match is ambiguous: say so rather than pick a tenant's bin at random."""
	filters = {"name": ["like", f"%- {code} -%"], "is_group": 0}
	if company:
		filters["company"] = company
	matches = frappe.get_all("Warehouse", filters=filters, pluck="name")
	if len(matches) > 1:
		companies = ", ".join(sorted({frappe.db.get_value("Warehouse", m, "company") for m in matches}))
		frappe.throw(f"Bin {code} exists for several customers ({companies}). Scan or type the full bin name.")
	return matches[0] if matches else None


def _resolve_bin(code: str, company: str | None = None) -> str:
	"""Resolve a scanned/typed bin code to a real, stock-holding Warehouse.

	Accepts the full Warehouse name, its warehouse_name, or a short suffix code
	(e.g. "A1" resolving to a matching storage bin) so an operator can type
	a short code instead of the full internal warehouse name.
	"""
	code = (code or "").strip()
	if not code:
		frappe.throw("Scan or enter a bin code.")
	name = None
	if frappe.db.exists("Warehouse", code):
		name = code
	if not name:
		name = frappe.db.get_value("Warehouse", {"warehouse_name": code}, "name")
	if not name:
		name = _suffix_bin(code, company)
	if not name:
		# Bin codes are zero-padded (A01) so they sort correctly past A09, but printed
		# labels and habit both say "A1". Accept either, in both directions, so a
		# relabelling programme never has to be finished before scanning works.
		padded = re.sub(r"^([A-Za-z]+)(\d+)$", lambda m: f"{m.group(1)}{m.group(2).zfill(2)}", code)
		unpadded = re.sub(r"^([A-Za-z]+)0*(\d+)$", r"\1\2", code)
		for variant in {padded, unpadded} - {code}:
			name = frappe.db.get_value(
				"Warehouse", {"warehouse_name": variant}, "name"
			) or _suffix_bin(variant, company)
			if name:
				break
	if not name:
		frappe.throw(f"Bin {code} was not found in ERPNext.")
	if frappe.db.get_value("Warehouse", name, "is_group"):
		frappe.throw(f"{code} is a warehouse zone, not a specific bin - choose a leaf bin.")
	return name


DEFAULT_TEST_CUSTOMER = "Example Customer"


def _resolve_customer(customer: str | None) -> str:
	"""Validate a Customer link, or fall back to the designated default customer.

	`customer` must always resolve to a genuine Customer doctype row - there is no
	"Manual Entry" placeholder, since these test records still have to pass the
	same doctype validation real orders would.

	The fallback is pinned to `DEFAULT_TEST_CUSTOMER` rather than "whichever Customer
	sorts first", because an alphabetical fallback can attribute manually created
	tasks to the wrong account. If that customer is missing we raise instead of
	guessing.
	"""
	customer = (customer or "").strip()
	if customer:
		if not frappe.db.exists("Customer", customer):
			frappe.throw(f"Customer {customer} was not found in ERPNext.")
		return customer
	if _setting("customer_mode") == "Manual":
		frappe.throw("Choose a customer for this task.")
	default_name = _setting("default_customer") or DEFAULT_TEST_CUSTOMER
	default_customer = frappe.db.get_value("Customer", {"name": default_name, "disabled": 0}, "name")
	if not default_customer:
		frappe.throw(
			f"Default customer '{default_name}' was not found (or is disabled). "
			"Pick a customer explicitly, or set the Default Customer in SoyPaq Settings."
		)
	return default_customer


def _parse_manual_items(items) -> list[dict]:
	"""Validate a manually entered item list against real ERPNext Item records.

	Used by the `create_*` endpoints so a task built without a source order still
	only ever references items that genuinely exist and are enabled.
	"""
	if isinstance(items, str):
		try:
			items = json.loads(items)
		except (TypeError, ValueError):
			frappe.throw("Items must be valid JSON.")
	if not items:
		frappe.throw("Add at least one item line.")

	rows = []
	for entry in items:
		item_code = (entry.get("item_code") or "").strip()
		quantity = flt(entry.get("quantity"))
		if not item_code:
			frappe.throw("Every line needs an item code.")
		# A scanned barcode is as valid as an item code. Unresolved values fall through so the
		# "not found" / "disabled" errors below stay exactly as they were.
		item_code = _resolve_scanned_item(item_code) or item_code
		if quantity <= 0:
			frappe.throw(f"Quantity for {item_code} must be greater than zero.")
		item = frappe.db.get_value("Item", item_code, ["item_name", "stock_uom", "disabled"], as_dict=True)
		if not item:
			frappe.throw(f"Item {item_code} was not found in ERPNext.")
		if item.disabled:
			frappe.throw(f"Item {item_code} is disabled in ERPNext.")
		rows.append(
			{
				"item_code": item_code,
				"item_name": item.item_name,
				"uom": item.stock_uom,
				"quantity": quantity,
				# Optional per-line bin (used by create_pick_task to split one task per bin).
				"warehouse": _resolve_bin(entry["warehouse"]) if entry.get("warehouse") else None,
			}
		)
	return rows


def _sales_order_context(name: str | None) -> dict:
	if not name or not frappe.db.exists("Sales Order", name):
		return {}

	order = frappe.db.get_value(
		"Sales Order",
		name,
		[
			"name",
			"company",
			"customer",
			"customer_name",
			"transaction_date",
			"delivery_date",
			"status",
			"po_no",
			"owner",
		],
		as_dict=True,
	)
	rows = frappe.get_all(
		"Sales Order Item",
		filters={"parent": name},
		fields=["item_code", "item_name", "qty", "stock_qty", "warehouse"],
		order_by="idx asc",
	)
	return {
		"doctype": "Sales Order",
		"name": order.name,
		"company": order.company,
		"party": order.customer,
		"party_name": order.customer_name or order.customer,
		"transaction_date": order.transaction_date,
		"due_date": order.delivery_date,
		"status": order.status,
		"external_reference": order.po_no,
		"owner": _user(order.owner),
		"route": _route("Sales Order", order.name),
		"items": [
			{
				"item_code": row.item_code,
				"item_name": row.item_name,
				"quantity": flt(row.stock_qty or row.qty),
				"warehouse": row.warehouse,
			}
			for row in rows
		],
	}


def _purchase_order_context(name: str | None) -> dict:
	if not name or not frappe.db.exists("Purchase Order", name):
		return {}

	order = frappe.db.get_value(
		"Purchase Order",
		name,
		[
			"name",
			"company",
			"supplier",
			"supplier_name",
			"transaction_date",
			"schedule_date",
			"status",
			"supplier_order_reference",
			"owner",
		],
		as_dict=True,
	)
	return {
		"doctype": "Purchase Order",
		"name": order.name,
		"company": order.company,
		"party": order.supplier,
		"party_name": order.supplier_name or order.supplier,
		"transaction_date": order.transaction_date,
		"due_date": order.schedule_date,
		"status": order.status,
		"external_reference": order.supplier_order_reference,
		"owner": _user(order.owner),
		"route": _route("Purchase Order", order.name),
	}


def _line_totals(rows, quantity_field: str) -> dict[str, float]:
	totals: dict[str, float] = {}
	for row in rows or []:
		item_code = row.get("item_code")
		if item_code:
			totals[item_code] = totals.get(item_code, 0) + flt(row.get(quantity_field))
	return totals


def _source_integrity(doc, order: dict) -> dict:
	if not doc or not order:
		return {"status": "unlinked", "label": "Source order not linked", "details": []}
	if order.get("source_kind") == "medusa":
		# No Sales Order lines to compare against; the Medusa intake log is the record.
		return {"status": "external", "label": "Medusa order", "details": []}

	task_lines = _line_totals(doc.get("pick_items"), "required_qty")
	order_lines = _line_totals(order.get("items"), "quantity")
	details = []
	for item_code in sorted(set(task_lines) | set(order_lines)):
		task_qty = task_lines.get(item_code, 0)
		order_qty = order_lines.get(item_code, 0)
		if task_qty != order_qty:
			details.append(
				{
					"item_code": item_code,
					"task_qty": task_qty,
					"order_qty": order_qty,
				}
			)
	return {
		"status": "match" if not details else "mismatch",
		"label": "Task matches source order" if not details else "Task lines differ from source order",
		"details": details,
	}


def _origin_pick(doc):
	"""The Pick Task at the start of a task's lineage (Pack.warehouse = pick, Shipment.warehouse = pack)."""
	if not doc:
		return None
	if doc.doctype == "Pick Task":
		return doc
	if doc.doctype == "Shipment Task":
		doc = _origin_pick_link(doc, "Pack Task")
	if doc and doc.doctype == "Pack Task":
		return _origin_pick_link(doc, "Pick Task")
	return None


def _origin_pick_link(doc, doctype: str):
	name = doc.get("warehouse")
	return frappe.get_doc(doctype, name) if name and frappe.db.exists(doctype, name) else None


def _medusa_context(doc) -> dict:
	"""Where an order came from when it entered through Medusa (no Sales Order exists for these yet)."""
	pick = _origin_pick(doc)
	order_id = pick.get("medusa_order_id") if pick else None
	if not order_id:
		return {}
	number = pick.get("medusa_order_number")
	intake = frappe.db.get_value(
		"Medusa Intake Log", {"medusa_order_id": order_id, "outcome": "Created"}, ["name", "creation"], as_dict=True
	)
	return {
		"doctype": "Medusa order",
		"name": f"#{number}" if number else order_id,
		"party_name": pick.get("customer"),
		"external_reference": f"#{number}" if number else order_id,
		"reference_label": "Medusa",
		"medusa_order_id": order_id,
		"transaction_date": str(intake.creation.date()) if intake else "",
		"route": _route("Medusa Intake Log", intake.name) if intake else "",
		"source_kind": "medusa",
	}


def _task_source(doc) -> dict:
	"""Source order for a task: the linked Sales Order, else the Medusa order it came from."""
	if not doc:
		return {}
	return _sales_order_context(doc.get("sales_order")) or _medusa_context(doc)


def _task(doc, label: str) -> dict | None:
	if not doc:
		return None

	order = (
		_purchase_order_context(doc.get("purchase_order"))
		if doc.doctype == "Inbound ASN"
		else _task_source(doc)
	)
	warehouse = doc.get("target_warehouse") if doc.doctype == "Inbound ASN" else doc.get("warehouse")
	assigned_user = doc.get("assigned_to") if doc.doctype == "Pick Task" else doc.get("assigned_user")
	reference = (
		doc.get("sales_order")
		or doc.get("external_tracking_number")
		or doc.get("tracking_number")
		or doc.name
	)
	return {
		"doctype": doc.doctype,
		"name": doc.name,
		"kind": label,
		"title": f"{label} {reference}",
		"reference": reference,
		"status": doc.get("status") or "Ready",
		"customer": doc.get("customer") or "SoyPaq demo",
		"company": order.get("company") or _warehouse_company(warehouse),
		"assigned_to": _user(assigned_user),
		"source": order,
		"source_integrity": _source_integrity(doc, order)
		if doc.doctype in ("Pick Task", "Pack Task")
		else {},
		"route": _route(doc.doctype, doc.name),
	}


def _item_rows(doc, fieldname: str, quantity_field: str) -> list[dict]:
	if not doc:
		return []
	rows = []
	for row in doc.get(fieldname) or []:
		item_code = row.get("item_code") or row.get("barcode") or "Item"
		item = frappe.db.get_value(
			"Item",
			item_code,
			["item_name", "image", "stock_uom", "disabled", "modified", "item_group", "soy_needs_review"],
			as_dict=True,
		)
		rows.append(
			{
				"sku": item_code,
				"name": (item.item_name if item else None) or row.get("item_name") or item_code,
				"image": item.image if item else None,
				"uom": (item.stock_uom if item else None) or row.get("uom"),
				"disabled": bool(item.disabled) if item else False,
				"item_modified": item.modified if item else None,
				"quantity": row.get(quantity_field) or row.get("quantity") or 0,
				"picked": row.get("picked_qty") or 0,
				"packed": row.get("packed_qty") or 0,
				"shipped": row.get("shipped_qty") or 0,
				"received": row.get("received_qty") or 0,
				"item_group": item.item_group if item else "",
				"needs_review": bool(item.soy_needs_review) if item else False,
				"assigned_bin": row.get("assigned_bin") or "",
				"source_warehouse": row.get("source_warehouse") or "",
				"source_bin": row.get("source_bin") or "",
				"bin_confirmed": bool(cint(row.get("bin_confirmed"))),
				"status": row.get("status") or row.get("condition") or "Expected",
				"exception_reason": row.get("exception_reason") or "",
				"exception_note": row.get("exception_note") or "",
				"exception_image": row.get("exception_image") or "",
			}
		)
	return rows


def _inventory_snapshot() -> dict:
	"""Build a current stock and storage snapshot from ERPNext Item/Bin data."""
	items = frappe.get_all(
		"Item",
		filters={"is_stock_item": 1, "disabled": 0},
		fields=["name", "item_name", "item_group", "stock_uom", "image", "modified", "soy_product", "soy_color", "soy_size", "soy_collection"],
		order_by="item_name asc",
		limit_page_length=500,
	)
	bins = frappe.get_all(
		"Bin",
		fields=[
			"item_code",
			"warehouse",
			"actual_qty",
			"reserved_qty",
			"projected_qty",
			"ordered_qty",
			"valuation_rate",
		],
		limit_page_length=5000,
	)
	warehouses = frappe.get_all(
		"Warehouse",
		filters={"is_group": 0, "disabled": 0},
		fields=["name", "warehouse_name", "parent_warehouse", "company"],
		order_by="warehouse_name asc",
		limit_page_length=500,
	)

	bins_by_item: dict[str, list[dict]] = {}
	warehouse_totals: dict[str, dict] = {
		warehouse.name: {"item_count": 0, "on_hand": 0.0, "reserved": 0.0} for warehouse in warehouses
	}
	stock_value = 0.0
	for stock_bin in bins:
		actual = float(stock_bin.actual_qty or 0)
		reserved = float(stock_bin.reserved_qty or 0)
		stock_value += actual * float(stock_bin.valuation_rate or 0)
		location = {
			"warehouse": stock_bin.warehouse,
			"on_hand": actual,
			"reserved": reserved,
			"available": actual - reserved,
			"projected": float(stock_bin.projected_qty or 0),
			"incoming": float(stock_bin.ordered_qty or 0),
		}
		if actual != 0:
			# A Bin doc persists after it's been emptied out - skip zero-qty rows so
			# the item detail's location list doesn't accumulate dead bins forever.
			# Negative rows stay in: that's a real ledger discrepancy worth surfacing.
			bins_by_item.setdefault(stock_bin.item_code, []).append(location)
		if stock_bin.warehouse in warehouse_totals:
			warehouse_totals[stock_bin.warehouse]["item_count"] += 1
			warehouse_totals[stock_bin.warehouse]["on_hand"] += actual
			warehouse_totals[stock_bin.warehouse]["reserved"] += reserved

	warehouse_company = {warehouse.name: warehouse.company for warehouse in warehouses}
	rows = []
	for item in items:
		locations = sorted(
			bins_by_item.get(item.name, []),
			key=lambda row: (-row["on_hand"], row["warehouse"]),
		)
		on_hand = sum(row["on_hand"] for row in locations)
		reserved = sum(row["reserved"] for row in locations)
		projected = sum(row["projected"] for row in locations)
		rows.append(
			{
				"item_code": item.name,
				"item_name": item.item_name or item.name,
				"item_group": item.item_group,
				"product": item.get("soy_product") or "",
				"color": item.get("soy_color") or "",
				"size": item.get("soy_size") or "",
				"collection": item.get("soy_collection") or "",
				"company": warehouse_company.get(locations[0]["warehouse"], "") if locations else "",
				"uom": item.stock_uom,
				"image": item.image,
				"modified": item.modified,
				"on_hand": on_hand,
				"reserved": reserved,
				"available": on_hand - reserved,
				"projected": projected,
				"primary_location": locations[0]["warehouse"] if locations else "Unassigned",
				"locations": locations,
				"route": _route("Item", item.name),
			}
		)

	location_rows = []
	for warehouse in warehouses:
		totals = warehouse_totals[warehouse.name]
		location_rows.append(
			{
				"name": warehouse.name,
				"label": warehouse.warehouse_name or warehouse.name,
				"parent": warehouse.parent_warehouse,
				"company": warehouse.company,
				"item_count": totals["item_count"],
				"on_hand": totals["on_hand"],
				"reserved": totals["reserved"],
				"available": totals["on_hand"] - totals["reserved"],
				"route": _route("Warehouse", warehouse.name),
			}
		)

	# "Staged" view: only leaf bins that sit under a parent zone (real put-away
	# locations), each with the items physically inside it. Coarse top-level
	# warehouses are excluded - they are zones, not bins an operator walks to.
	item_names = {item.name: item for item in items}
	bin_contents: dict[str, list[dict]] = {}
	for stock_bin in bins:
		if float(stock_bin.actual_qty or 0) <= 0:
			continue
		item = item_names.get(stock_bin.item_code)
		bin_contents.setdefault(stock_bin.warehouse, []).append(
			{
				"item_code": stock_bin.item_code,
				"item_name": (item.item_name if item else None) or stock_bin.item_code,
				"image": item.image if item else None,
				"on_hand": float(stock_bin.actual_qty or 0),
				"reserved": float(stock_bin.reserved_qty or 0),
			}
		)
	# Fetch recent activity per bin
	bin_activity_map = {}
	for action in frappe.get_all(
		"Inventory Action",
		fields=["warehouse", "item_code", "reason_code", "created_by_user", "creation"],
		order_by="creation desc",
		limit_page_length=500,
	):
		key = action.warehouse
		if key not in bin_activity_map:
			bin_activity_map[key] = []
		if len(bin_activity_map[key]) < 3:
			bin_activity_map[key].append(
				{
					"reason": action.reason_code,
					"user": _user(action.created_by_user)["name"],
					"timestamp": str(action.creation),
					"item": action.item_code,
				}
			)

	bin_rows = []
	for warehouse in warehouses:
		if not warehouse.parent_warehouse:
			continue
		contents = sorted(bin_contents.get(warehouse.name, []), key=lambda row: row["item_name"])
		bin_rows.append(
			{
				"name": warehouse.name,
				"label": warehouse.warehouse_name or warehouse.name,
				"parent": warehouse.parent_warehouse,
				"company": warehouse.company,
				"sku_count": len(contents),
				"on_hand": sum(row["on_hand"] for row in contents),
				"items": contents,
				"action_history": bin_activity_map.get(warehouse.name, []),
				"route": _route("Warehouse", warehouse.name),
			}
		)
	bin_rows.sort(key=lambda row: (-row["on_hand"], row["label"]))

	return {
		"items": rows,
		"locations": location_rows,
		"bins": bin_rows,
		"summary": {
			"sku_count": len(rows),
			"on_hand": sum(row["on_hand"] for row in rows),
			"reserved": sum(row["reserved"] for row in rows),
			"available": sum(row["available"] for row in rows),
			"assigned": len([row for row in rows if row["locations"]]),
			"location_count": len(location_rows),
			"stocked_bin_count": len([row for row in bin_rows if row["on_hand"] > 0]),
			"staged_on_hand": sum(row["on_hand"] for row in bin_rows),
			"stock_value": stock_value,
		},
	}


CLAIM_FIELD = {
	"Pick Task": "assigned_to",
	"Pack Task": "assigned_user",
	"Shipment Task": "assigned_user",
	"Inbound Package": "assigned_user",
}


def _claimable_task(doctype: str, name: str):
	if doctype not in CLAIM_FIELD:
		frappe.throw(f"{doctype} tasks cannot be claimed.")
	if not name or not frappe.db.exists(doctype, name):
		frappe.throw(f"{doctype} {name or ''} was not found.")
	doc = frappe.get_doc(doctype, name)
	if not doc.has_permission("write"):
		frappe.throw(f"You do not have permission to claim {doctype} {name}.", frappe.PermissionError)
	if doc.get("status") in ("Completed", "Cancelled", "Shipped", "Stored", "Consolidated", "Delivered"):
		frappe.throw(f"{doctype} {name} is already {doc.get('status')}.")
	return doc


def _other_active_claim(user: str, exclude_doctype: str, exclude_name: str) -> dict | None:
	"""Does this user already have a different, unfinished task claimed?

	One operator can only physically do one job at a time - claiming a second task while
	the first is still open would let someone start Picking while mid-Pack, which is
	exactly the "two jobs at once" state the claim system exists to prevent.
	"""
	checks = [
		("Pick Task", "assigned_to", "Pick", ("Completed", "Cancelled")),
		("Pack Task", "assigned_user", "Pack", ("Completed", "Cancelled")),
		("Shipment Task", "assigned_user", "Ship", ("Shipped", "Cancelled")),
		("Inbound Package", "assigned_user", "Receive", DONE_STATUSES["Inbound Package"]),
	]
	for doctype, field, kind, done_statuses in checks:
		rows = frappe.get_all(
			doctype,
			filters={field: user, "status": ["not in", done_statuses]},
			fields=["name", "sales_order"] if doctype != "Inbound Package" else ["name", "external_tracking_number"],
			limit_page_length=2,
		)
		for row in rows:
			if doctype == exclude_doctype and row.name == exclude_name:
				continue
			reference = row.get("sales_order") or row.get("external_tracking_number") or row.name
			return {"kind": kind, "reference": reference, "name": row.name}
	return None


@frappe.whitelist()
def claim_task(doctype: str, name: str) -> dict:
	"""Claim an open task for the current user - this is what tapping Start actually does.

	Re-claiming a task you already hold (Continue) is a no-op, not an error. Claiming
	something someone else is actively holding is blocked outright - two operators must
	never end up working the same task at once. Claiming a *second, different* task while
	you already hold one unfinished is blocked the same way - one operator, one active job.
	"""
	doc = _claimable_task(doctype, name)
	field = CLAIM_FIELD[doctype]
	current = doc.get(field)
	if current and current != frappe.session.user:
		frappe.throw(f"{doc.name} is already being worked by {_user(current)['name']}.")
	if current != frappe.session.user:
		conflict = _other_active_claim(frappe.session.user, doctype, name)
		if conflict:
			frappe.throw(
				f"You already have an active task: {conflict['kind']} {conflict['reference']}. "
				"Finish or release it before starting another."
			)
		doc.set(field, frappe.session.user)
		if doctype == "Pick Task":
			doc.claimed_at = now_datetime()
		doc.save()
		_publish_task_update(doc)
	return {"name": doc.name, "assigned_to": _user(frappe.session.user)}


@frappe.whitelist()
def release_task(doctype: str, name: str) -> dict:
	"""Release a claimed task back to the open queue.

	This is a manual hand-back (the "Cancel" action from the task drawer), distinct from
	the doctype's real Cancelled status - the task itself is untouched, just unclaimed.
	"""
	doc = _claimable_task(doctype, name)
	field = CLAIM_FIELD[doctype]
	if doc.get(field) != frappe.session.user:
		frappe.throw("You can only release a task you currently have claimed.")
	doc.set(field, None)
	doc.save()
	_publish_task_update(doc)
	return {"name": doc.name}


@frappe.whitelist()
def cancel_task(doctype: str, name: str) -> dict:
	"""Cancel a task outright - claimed or not, unlike release_task, which only hands
	back an existing claim and leaves the task sitting open."""
	doc = _claimable_task(doctype, name)
	doc.status = "Cancelled"
	doc.save(ignore_permissions=True)
	_publish_task_update(doc)
	return {"name": doc.name, "status": doc.status}


_MY_TASKS_DONE_STATUS = {
	"Pick Task": ("Completed",),
	"Pack Task": ("Completed",),
	"Shipment Task": ("Shipped",),
	"Inbound Package": ("Stored", "Consolidated", "Shipped", "Delivered"),
}
_MY_TASKS_KIND_DOCTYPE = {
	"Pick": "Pick Task",
	"Pack": "Pack Task",
	"Ship": "Shipment Task",
	"Receive": "Inbound Package",
}


def _my_tasks_buckets() -> dict:
	"""Split every WMS task across all four stages into open / active / history.

	"Active" means a real person has claimed it (assigned_to/assigned_user is set) and it
	isn't finished yet - not a specific status string, since each doctype uses its own
	status vocabulary. "Open" is unclaimed, unfinished work. "History" is finished work,
	globally, regardless of who did it. Inbound Package has no claim field yet, so it can
	only ever land in "open" or "history", never "active".
	"""
	sources = [
		("Pick", _list_pick_tasks(100)),
		("Pack", _list_pack_tasks(100)),
		("Ship", _list_shipment_tasks(100)),
		("Receive", _list_receive_packages(100)),
	]
	open_bucket, active_bucket, history_bucket = [], [], []
	for kind, rows in sources:
		doctype = _MY_TASKS_KIND_DOCTYPE[kind]
		for row in rows:
			row = dict(row)
			row["kind"] = kind
			row["doctype"] = doctype
			if row.get("status") in _MY_TASKS_DONE_STATUS[doctype]:
				history_bucket.append(row)
			elif (row.get("assigned_to") or {}).get("id"):
				active_bucket.append(row)
			else:
				open_bucket.append(row)
	open_bucket.sort(key=lambda r: r["modified"], reverse=True)
	active_bucket.sort(key=lambda r: r["modified"], reverse=True)
	history_bucket.sort(key=lambda r: r["modified"], reverse=True)
	return {"open": open_bucket, "active": active_bucket, "history": history_bucket}


_TASK_PREVIEW_FIELDS = {
	"Pick Task": ("pick_items", "required_qty"),
	"Pack Task": ("pick_items", "required_qty"),
	"Shipment Task": ("shipment_items", "required_qty"),
	# "quantity" is an expected-qty field that blind receiving deliberately leaves at 0
	# ("nothing was expected" - see _package_row). received_qty is the truth for what's
	# actually in the package, so that's what the preview should show.
	"Inbound Package": ("package_items", "received_qty"),
}


def _pick_activity_rows(task_name: str, limit: int = 50) -> list[dict]:
	rows = frappe.get_all(
		"Pick Action",
		filters={"pick_task": task_name},
		fields=[
			"name",
			"item_code",
			"item_name",
			"action_type",
			"exception_reason",
			"quantity",
			"warehouse",
			"note",
			"image",
			"created_by_user",
			"creation",
		],
		order_by="creation desc",
		limit_page_length=limit,
	)
	return [
		{
			"item_code": r.item_code or "",
			"item_name": r.item_name or "",
			"action_type": r.action_type,
			"exception_reason": r.exception_reason or "",
			"quantity": flt(r.quantity),
			"warehouse": r.warehouse or "",
			"note": r.note or "",
			"image": r.image or "",
			"user": _user(r.created_by_user)["name"],
			"timestamp": str(r.creation),
			"route": _route("Pick Action", r.name),
		}
		for r in rows
	]


@frappe.whitelist()
def get_pick_activity(task_name: str, limit: int = 50) -> list[dict]:
	"""Per-scan audit trail for a Pick Task - powers the live activity view and,
	once completed, the same task's History drawer."""
	if not task_name or not frappe.db.exists("Pick Task", task_name):
		frappe.throw(f"Pick Task {task_name or ''} was not found.")
	return _pick_activity_rows(task_name, limit)


@frappe.whitelist()
def get_task_preview(doctype: str, name: str) -> dict:
	"""Full item breakdown (with images) for the My Tasks preview drawer.

	Fetched on demand when a task card is opened, not eagerly for every row in every
	bucket - most tasks in a list are never previewed in a given session.
	"""
	if doctype not in _TASK_PREVIEW_FIELDS:
		frappe.throw(f"{doctype} has no preview available.")
	if not name or not frappe.db.exists(doctype, name):
		frappe.throw(f"{doctype} {name or ''} was not found.")
	doc = frappe.get_doc(doctype, name)
	if not doc.has_permission("read"):
		frappe.throw(f"You do not have permission to view {doctype} {name}.", frappe.PermissionError)
	fieldname, quantity_field = _TASK_PREVIEW_FIELDS[doctype]

	source: dict = {}
	source_integrity: dict = {}
	if doctype in ("Pick Task", "Pack Task"):
		source = _task_source(doc)
		source_integrity = _source_integrity(doc, source) if source.get("doctype") == "Sales Order" else {}
	elif doctype == "Shipment Task":
		# Same lineage as Pick/Pack, but _source_integrity compares against a
		# "pick_items" fieldname that Shipment Task doesn't have - showing origin
		# here without a (meaningless) match/mismatch verdict.
		source = _task_source(doc)
	elif doctype == "Inbound Package" and doc.get("inbound_asn"):
		source = {
			"doctype": "Inbound ASN",
			"name": doc.get("inbound_asn"),
			"route": _route("Inbound ASN", doc.get("inbound_asn")),
		}

	extra: dict = {}
	if doctype == "Pick Task":
		extra["claimed_at"] = str(doc.claimed_at) if doc.get("claimed_at") else ""
		extra["assigned_to"] = _user(doc.get("assigned_to"))
		extra["activity"] = _pick_activity_rows(doc.name)

	return {
		"name": doc.name,
		"items": _item_rows(doc, fieldname, quantity_field),
		"source": source,
		"source_integrity": source_integrity,
		"created": str(doc.creation),
		"modified": str(doc.modified),
		**extra,
	}


def _writable_task(doctype: str, name: str):
	if not name or not frappe.db.exists(doctype, name):
		frappe.throw(f"{doctype} {name or ''} was not found.")
	doc = frappe.get_doc(doctype, name)
	if not doc.has_permission("write"):
		frappe.throw(f"You do not have permission to update {doctype} {name}.", frappe.PermissionError)
	if doc.get("status") in ("Completed", "Cancelled", "Shipped"):
		frappe.throw(f"{doctype} {name} is already {doc.get('status')}.")
	return doc


def _row_bin(row) -> str:
	return row.get("source_bin") or row.get("source_warehouse") or ""


def _pick_bins(doc) -> list[str]:
	"""The distinct bins a Pick Task walks through, in row order."""
	bins: list[str] = []
	for row in doc.get("pick_items") or []:
		bin_name = _row_bin(row)
		if bin_name and bin_name not in bins:
			bins.append(bin_name)
	return bins


def _bin_confirmed(doc, row) -> bool:
	"""Has the picker confirmed the bin this row sits in?

	A single-bin task keeps the original task-level gate (`pick_state`). A multi-bin task confirms
	each bin on its own (`bin_confirmed` on the rows), so being at one bin unlocks only its rows.
	"""
	if len(_pick_bins(doc)) <= 1:
		return doc.get("pick_state") == "Waiting for Item"
	return bool(cint(row.get("bin_confirmed")))


def _require_bin_confirmed(doc, row, message: str) -> None:
	if _bin_confirmed(doc, row):
		return
	if len(_pick_bins(doc)) > 1:
		frappe.throw(f"Confirm bin {_row_bin(row)} first. {message}")
	frappe.throw(message)


def _task_row(doc, item_code: str):
	item_code = (item_code or "").strip()
	if not item_code:
		frappe.throw("Scan or enter an item barcode.")

	resolved_code = item_code
	if not frappe.db.exists("Item", resolved_code):
		resolved_code = frappe.db.get_value("Item Barcode", {"barcode": item_code}, "parent") or item_code
	row = next((row for row in doc.get("pick_items") or [] if row.get("item_code") == resolved_code), None)
	if not row:
		frappe.throw(f"Item {item_code} is not expected on {doc.doctype} {doc.name}.")
	if frappe.db.get_value("Item", resolved_code, "disabled"):
		frappe.throw(f"Item {resolved_code} is disabled in ERPNext.")
	return row


def _log_pick_action(
	pick_task,
	action_type: str,
	item_code: str = "",
	quantity: float = 0,
	exception_reason: str = "",
	note: str = "",
	image: str = "",
) -> None:
	"""Append one immutable event to the Pick Action log.

	Mirrors Inventory Action's role for stock adjustments: pick_item/unpick_item/
	flag_pick_item/complete_pick all call this so the History drawer and the live
	timer have a real per-event trail instead of the single `last_scan_action`
	string the Pick Task doc itself overwrites on every scan.
	"""
	warehouse = ""
	if item_code:
		row = next((r for r in pick_task.get("pick_items") or [] if r.get("item_code") == item_code), None)
		warehouse = (row.get("source_bin") or row.get("source_warehouse")) if row else ""
	frappe.get_doc(
		{
			"doctype": "Pick Action",
			"pick_task": pick_task.name,
			"item_code": item_code or None,
			"item_name": frappe.db.get_value("Item", item_code, "item_name") if item_code else "",
			"action_type": action_type,
			"exception_reason": exception_reason,
			"quantity": quantity,
			"warehouse": warehouse or pick_task.get("warehouse"),
			"note": note,
			"image": image,
			"created_by_user": frappe.session.user,
		}
	).insert(ignore_permissions=True)


def _publish_task_update(doc) -> None:
	frappe.publish_realtime(
		"soypaq_wms_update",
		{"doctype": doc.doctype, "name": doc.name, "modified": str(doc.modified)},
		after_commit=True,
	)


def _update_pick_totals(doc) -> None:
	total_required = sum(flt(row.get("required_qty")) for row in doc.get("pick_items") or [])
	total_picked = sum(flt(row.get("picked_qty")) for row in doc.get("pick_items") or [])
	doc.total_items = len(doc.get("pick_items") or [])
	doc.total_required_qty = total_required
	doc.total_picked_qty = total_picked
	doc.current_status = f"Picked {total_picked:g} of {total_required:g} units"


def _update_pack_totals(doc) -> None:
	total_required = sum(flt(row.get("required_qty")) for row in doc.get("pick_items") or [])
	total_packed = sum(flt(row.get("packed_qty")) for row in doc.get("pick_items") or [])
	doc.total_items = len(doc.get("pick_items") or [])
	doc.total_required_qty = total_required
	doc.total_packed_qty = total_packed
	doc.current_status = f"Packed {total_packed:g} of {total_required:g} units"


def _sync_pack_from_pick(pick_task) -> None:
	picked_by_item = {row.item_code: flt(row.picked_qty) for row in pick_task.get("pick_items") or []}
	pack_names = frappe.get_all(
		"Pack Task",
		filters={"warehouse": pick_task.name, "status": ["not in", ["Completed", "Cancelled"]]},
		pluck="name",
	)
	if not pack_names and pick_task.status == "Completed":
		_create_pack_task_from_pick(pick_task)
		return
	for name in pack_names:
		pack_task = frappe.get_doc("Pack Task", name)
		for row in pack_task.get("pick_items") or []:
			row.picked_qty = picked_by_item.get(row.item_code, 0)
		_update_pack_totals(pack_task)
		pack_task.current_status = (
			"Ready for packing" if pick_task.status == "Completed" else "Awaiting remaining picked items"
		)
		pack_task.save(ignore_permissions=True)
		_publish_task_update(pack_task)


def _create_pack_task_from_pick(pick_task) -> None:
	"""Give a completed Pick Task its Pack Task - the handoff `_sync_pack_from_pick`
	never performed on its own, only ever updating a Pack Task that already existed."""
	rows = [row for row in pick_task.get("pick_items") or [] if flt(row.picked_qty) > 0]
	if not rows:
		return
	doc = frappe.new_doc("Pack Task")
	doc.naming_series = "PACK-MIA-.#####"
	doc.status = "Pending"
	doc.customer = pick_task.get("customer")
	doc.sales_order = pick_task.get("sales_order")
	doc.warehouse = pick_task.name
	doc.assigned_to = "Carton Box"
	doc.pack_state = "Waiting for Item"
	doc.scan_item_barcode = rows[0].item_code
	doc.current_status = f"Ready for packing - from {pick_task.name}"
	for row in rows:
		doc.append(
			"pick_items",
			{
				"item_code": row.item_code,
				"item_name": row.item_name,
				"uom": row.get("uom"),
				"required_qty": row.picked_qty,
				"picked_qty": row.picked_qty,
				"packed_qty": 0,
				"source_warehouse": row.get("source_warehouse"),
				"source_bin": row.get("source_bin"),
				"status": "Pending",
			},
		)
	_update_pack_totals(doc)
	doc.insert(ignore_permissions=True)
	_publish_task_update(doc)


@frappe.whitelist()
def get_mobile_bootstrap(
	pick_task_name: str = None,
	pack_task_name: str = None,
	shipment_task_name: str = None,
	package_name: str = None,
) -> dict:
	"""Return the live local WMS state consumed by the Vue operator app.

	The `*_name` arguments let the app ask for a *specific* record's detail (picked
	from the real task list) instead of always getting whichever record happened to
	be touched most recently.
	"""
	inbound_package = _select_doc("Inbound Package", package_name)
	inbound_asn = (
		frappe.get_doc("Inbound ASN", inbound_package.inbound_asn)
		if inbound_package
		and inbound_package.get("inbound_asn")
		and frappe.db.exists("Inbound ASN", inbound_package.inbound_asn)
		else _get_doc("Inbound ASN")
	)
	pick_task = _select_doc("Pick Task", pick_task_name)
	pack_task = _select_doc("Pack Task", pack_task_name)
	shipment_task = _select_doc("Shipment Task", shipment_task_name)

	pick_order = _task_source(pick_task)
	pack_order = _task_source(pack_task)
	shipment_order = _task_source(shipment_task)
	inbound_order = _purchase_order_context(inbound_asn.get("purchase_order")) if inbound_asn else {}

	receive_task_data = _task(inbound_asn, "Receive")
	pick_task_data = _task(pick_task, "Pick")
	pack_task_data = _task(pack_task, "Pack")
	shipment_task_data = _task(shipment_task, "Ship")
	tasks = [task for task in [receive_task_data, pick_task_data, pack_task_data, shipment_task_data] if task]

	package_rows = _item_rows(inbound_package, "package_items", "quantity")
	pick_rows = _item_rows(pick_task, "pick_items", "required_qty")
	pack_rows = _item_rows(pack_task, "pick_items", "required_qty")
	ship_rows = _item_rows(shipment_task, "shipment_items", "required_qty")
	shipment_context = _shipment_chain(shipment_task)
	for row in ship_rows:
		note = (shipment_context.get("item_notes") or {}).get(row["sku"]) or {}
		row["pick_status"] = note.get("pick_status", "")
		row["pick_exception"] = note.get("exception_reason", "")
		row["short_qty"] = note.get("short_qty", 0)
	issues = [
		{
			"type": "Waiting for item scan",
			"detail": inbound_package.get("scan_state") or "Package requires item confirmation",
			"record": inbound_package.name,
			"severity": "Medium",
			"route": _route("Inbound Package", inbound_package.name),
		}
		if inbound_package and inbound_package.get("scan_state") not in (None, "Complete")
		else None,
		{
			"type": "Pick in progress",
			"detail": pick_task.get("current_status") or "Pick task needs completion",
			"record": pick_task.name,
			"severity": "High",
			"route": _route("Pick Task", pick_task.name),
		}
		if pick_task and pick_task.get("status") not in ("Completed", "Cancelled")
		else None,
		{
			"type": "Source order mismatch",
			"detail": "Pick task item lines differ from the linked Sales Order.",
			"record": pick_task.name,
			"severity": "High",
			"route": _route("Pick Task", pick_task.name),
		}
		if pick_task and _source_integrity(pick_task, pick_order)["status"] == "mismatch"
		else None,
	]

	return {
		"operator": _operator_info(),
		"stats": {
			"receive": _open_count("Inbound Package"),
			"pick": _open_count("Pick Task"),
			"pack": _open_count("Pack Task"),
			"ship": _open_count("Shipment Task"),
			"exceptions": len([issue for issue in issues if issue]),
		},
		"tasks": tasks,
		"my_tasks": _my_tasks_buckets(),
		"receive": {
			"asn": {
				"name": inbound_asn.name if inbound_asn else "",
				"reference": inbound_asn.get("external_tracking_number") if inbound_asn else "",
				"customer": inbound_asn.get("customer") if inbound_asn else "",
				"carrier": inbound_asn.get("carrier") if inbound_asn else "",
				"status": inbound_asn.get("status") if inbound_asn else "",
				"company": (
					inbound_asn.get("company")
					or inbound_order.get("company")
					or _warehouse_company(inbound_asn.get("target_warehouse"))
					if inbound_asn
					else ""
				),
				"supplier": inbound_asn.get("supplier") if inbound_asn else "",
				"purchase_order": inbound_asn.get("purchase_order") if inbound_asn else "",
				"source": inbound_order,
				"route": _route("Inbound ASN", inbound_asn.name) if inbound_asn else "",
			},
			"package": {
				"name": inbound_package.name if inbound_package else "",
				"customer": inbound_package.get("customer") if inbound_package else "",
				"stock_entry": inbound_package.get("stock_entry_reference") if inbound_package else "",
				"stock_entry_route": _route("Stock Entry", inbound_package.stock_entry_reference)
				if inbound_package and inbound_package.get("stock_entry_reference")
				else "",
				"tracking": inbound_package.get("external_tracking_number") if inbound_package else "",
				"warehouse": inbound_package.get("target_warehouse") if inbound_package else "",
				"bin": inbound_package.get("scan_bin") if inbound_package else "",
				"status": inbound_package.get("status") if inbound_package else "",
				"route": _route("Inbound Package", inbound_package.name) if inbound_package else "",
				"items": package_rows,
			},
			"packages": _list_receive_packages(),
		},
		"pick": {
			"task": pick_task_data,
			"context": {
				**pick_order,
				# A Medusa order has no document of its own to title the screen with; keep the task name.
				**({"name": pick_task.name} if pick_order.get("source_kind") == "medusa" else {}),
				"task_customer": pick_task.get("customer") if pick_task else "",
				"warehouse": pick_task.get("warehouse") if pick_task else "",
				"assigned_to": _user(pick_task.get("assigned_to") if pick_task else None),
				"claimed_at": str(pick_task.get("claimed_at"))
				if pick_task and pick_task.get("claimed_at")
				else "",
				"created": str(pick_task.creation) if pick_task else "",
				"source_integrity": _source_integrity(pick_task, pick_order),
				"pack_task_name": (
					frappe.db.get_value("Pack Task", {"warehouse": pick_task.name}, "name")
					if pick_task
					else ""
				),
			},
			"bin": pick_task.get("scan_bin") if pick_task else "",
			"location_confirmed": bool(
				pick_task
				and (
					pick_task.get("pick_state") == "Waiting for Item"
					or flt(pick_task.get("total_picked_qty")) > 0
				)
			),
			"status": pick_task.get("status") if pick_task else "",
			"items": pick_rows,
			"tasks": _list_pick_tasks(),
		},
		"pack": {
			"task": pack_task_data,
			"context": {
				**pack_order,
				"sales_order": pack_task.get("sales_order") if pack_task else "",
				"task_customer": pack_task.get("customer") if pack_task else "",
				"pick_task": pack_task.get("warehouse") if pack_task else "",
				"container": pack_task.get("tracking_number") if pack_task else "",
				"package_type": pack_task.get("assigned_to") if pack_task else "",
				"order_status": pack_order.get("status"),
				"assigned_to": _user(
					pack_task.get("assigned_user") or (pick_task.get("assigned_to") if pick_task else None)
					if pack_task
					else None
				),
				"status": pack_task.get("pack_state") if pack_task else "",
				"current_status": pack_task.get("current_status") if pack_task else "",
				"total_items": pack_task.get("total_items") if pack_task else 0,
				"required_qty": pack_task.get("total_required_qty") if pack_task else 0,
				"packed_qty": pack_task.get("total_packed_qty") if pack_task else 0,
				"box_confirmed": bool(pack_task.get("box_confirmed")) if pack_task else False,
				"source_integrity": _source_integrity(pack_task, pack_order),
				"shipment_task_name": (
					frappe.db.get_value("Shipment Task", {"warehouse": pack_task.name}, "name")
					if pack_task
					else ""
				),
			},
			"status": pack_task.get("status") if pack_task else "",
			"items": pack_rows,
			"tasks": _list_pack_tasks(),
		},
		"ship": {
			"task": shipment_task_data,
			"context": {
				**shipment_order,
				"pack_task": shipment_task.get("warehouse") if shipment_task else "",
				"assigned_to": _user(shipment_task.get("assigned_user") if shipment_task else None),
			},
			"status": shipment_task.get("status") if shipment_task else "",
			"carrier": shipment_task.get("carrier") if shipment_task else "",
			"tracking_number": shipment_task.get("tracking_number") if shipment_task else "",
			"label_url": shipment_task.get("shipping_label_url") if shipment_task else "",
			**(_ship_form(shipment_task) if shipment_task else {"ship_to": {}, "ship_to_source": "", "parcel": {}}),
			"name": shipment_task.name if shipment_task else "",
			"customer": shipment_task.get("customer") if shipment_task else "",
			"reference": (shipment_task.get("sales_order") or shipment_task.name) if shipment_task else "",
			"route": _route("Shipment Task", shipment_task.name) if shipment_task else "",
			"chain": shipment_context,
			"items": ship_rows,
			"tasks": _list_shipment_tasks(),
		},
		"issues": [issue for issue in issues if issue],
		"inventory": _inventory_snapshot(),
		"sync": {"status": "Online", "pending": 0, "last_sync": "Just now"},
	}


@frappe.whitelist()
def create_inbound_asn(
	customer: str = None, target_warehouse: str = None, carrier: str = "Other", items=None
) -> dict:
	"""Create a real, standalone Inbound ASN + Inbound Package for testing when no
	purchase order / shop integration exists yet.

	Both records are genuine rows - the returned package immediately works with
	receive_item / receive_all / stage_package / complete_receipt.
	"""
	rows = _parse_manual_items(items)
	target_warehouse = target_warehouse or _default_warehouse("Receiving")
	if not target_warehouse:
		frappe.throw("No warehouse is configured in ERPNext.")
	customer = _resolve_customer(customer)
	carrier = carrier or "Other"

	asn = frappe.new_doc("Inbound ASN")
	asn.naming_series = "ASN-MIA-.#####"
	asn.customer = customer
	asn.status = "Expected"
	asn.target_warehouse = target_warehouse
	asn.carrier = carrier
	asn.external_tracking_number = f"ASN-{frappe.generate_hash(length=6).upper()}"
	for row in rows:
		asn.append("asn_item", {"item_code": row["item_code"], "expected_qty": row["quantity"]})
	asn.insert()

	package = frappe.new_doc("Inbound Package")
	package.naming_series = "SPQ-MIA-.#####"
	package.inbound_asn = asn.name
	package.customer = customer
	package.target_warehouse = target_warehouse
	package.carrier = carrier
	package.external_tracking_number = f"1Z-{frappe.generate_hash(length=8).upper()}"
	package.status = "Received"
	package.scan_state = "Waiting for Item"
	for row in rows:
		package.append(
			"package_items",
			{
				"item_code": row["item_code"],
				"item_name": row["item_name"],
				"quantity": row["quantity"],
				"target_warehouse": target_warehouse,
			},
		)
	package.insert()

	_publish_task_update(asn)
	_publish_task_update(package)
	return {"asn": asn.name, "package": package.name, "route": _route("Inbound Package", package.name)}


@frappe.whitelist()
def start_receiving_session(customer: str, target_warehouse: str = None, tracking_number: str = None) -> dict:
	"""Open a blank receiving session for a box that arrived with no advance notice.

	No ASN is created and no tracking number is invented. `customer` is required and
	deliberately has no default: in a multi-client 3PL, silently assigning a box to the
	wrong owner is the error that surfaces months later at reconciliation.

	Scanning a tracking number that already has an open package RESUMES it rather than
	forking a second one.
	"""
	customer = (customer or "").strip()
	if not customer:
		frappe.throw("Choose which client this package belongs to before receiving it.")
	if not frappe.db.exists("Customer", customer):
		frappe.throw(f"Customer {customer} was not found in ERPNext.")

	tracking_number = (tracking_number or "").strip()
	if tracking_number:
		existing = frappe.db.get_value(
			"Inbound Package",
			{
				"external_tracking_number": tracking_number,
				"status": ["not in", DONE_STATUSES["Inbound Package"]],
			},
			"name",
		)
		if existing:
			claim_task("Inbound Package", existing)
			return {
				"name": existing,
				"resumed": True,
				"route": _route("Inbound Package", existing),
			}

	# Resolved by zone, not via DEFAULT_COMPANY: the company must be resolvable per
	# package, never assumed site-wide, and the public build's placeholder company
	# matches nothing on a real site.
	# The client's own Receiving zone (tenant Company shares the Customer's name); never another client's.
	tenant_company = customer if frappe.db.exists("Company", customer) else None
	target_warehouse = (target_warehouse or "").strip() or _zone_warehouse("Receiving", company=tenant_company)
	if not target_warehouse:
		frappe.throw(
			f"{customer} has no Receiving warehouse yet. Finish its setup, or create a "
			"leaf warehouse whose name contains 'Receiving'."
		)

	package = frappe.new_doc("Inbound Package")
	package.naming_series = "SPQ-MIA-.#####"
	package.customer = customer
	package.target_warehouse = target_warehouse
	package.status = "Received"
	package.scan_state = "Waiting for Item"
	if tracking_number:
		package.external_tracking_number = tracking_number
	package.insert()
	claim_task("Inbound Package", package.name)
	return {"name": package.name, "resumed": False, "route": _route("Inbound Package", package.name)}


def _resolve_scanned_item(code: str) -> str | None:
	"""Tier 1 resolution: a scanned code -> a real Item, by barcode then by item code.

	Deliberately an exact lookup with no parsing. Interpreting a structured code such as
	`RED-DRG-S` is Tier 2, needs Item Variants and a per-client rule, and is Phase 2.
	"""
	code = (code or "").strip()
	if not code:
		return None
	parent = frappe.db.get_value("Item Barcode", {"barcode": code}, "parent")
	if parent and not frappe.db.get_value("Item", parent, "disabled"):
		return parent
	if frappe.db.exists("Item", code) and not frappe.db.get_value("Item", code, "disabled"):
		return code
	return None


def _warehouse_label(warehouse: str) -> str:
	return frappe.db.get_value("Warehouse", warehouse, "warehouse_name") or warehouse


@frappe.whitelist()
def resolve_scan(code: str, warehouse: str = None) -> dict:
	"""Resolve one scanned/typed code for the pick builder: an item (barcode or item code) or a bin.

	Item: every bin holding stock, with `available` = on hand minus what open Pick Tasks already
	intend to take (the same figure create_pick_task enforces), plus `default_warehouse` - the
	caller's `warehouse` if it holds stock, else the bin with the most available.
	Bin: the items physically in it.
	An unknown code is `resolved: False`, never an error, so a bad scan does not interrupt scanning.
	"""
	code = (code or "").strip()
	if not code:
		frappe.throw("Scan or enter an item barcode or bin code.")

	item_code = _resolve_scanned_item(code)
	if item_code:
		item = frappe.db.get_value("Item", item_code, ["item_name", "stock_uom", "image"], as_dict=True)
		locations = []
		for row in frappe.get_all(
			"Bin", filters={"item_code": item_code, "actual_qty": [">", 0]}, fields=["warehouse", "actual_qty"]
		):
			committed = _open_pick_reserved_qty(item_code, row.warehouse)
			locations.append(
				{
					"warehouse": row.warehouse,
					"label": _warehouse_label(row.warehouse),
					"on_hand": flt(row.actual_qty),
					"committed": committed,
					"available": flt(row.actual_qty) - committed,
				}
			)
		locations.sort(key=lambda loc: (-loc["available"], loc["warehouse"]))
		default_warehouse = None
		if locations:
			preferred = next((loc for loc in locations if loc["warehouse"] == warehouse), None)
			default_warehouse = (preferred or locations[0])["warehouse"]
		return {
			"resolved": True,
			"kind": "item",
			"item_code": item_code,
			"item_name": item.item_name or item_code,
			"uom": item.stock_uom,
			"image": item.image,
			"locations": locations,
			"default_warehouse": default_warehouse,
		}

	try:
		bin_name = _resolve_bin(code)
	except frappe.ValidationError:
		return {"resolved": False, "code": code}

	items = []
	for row in frappe.get_all(
		"Bin", filters={"warehouse": bin_name, "actual_qty": [">", 0]}, fields=["item_code", "actual_qty"]
	):
		info = frappe.db.get_value("Item", row.item_code, ["item_name", "stock_uom", "image", "disabled"], as_dict=True)
		if not info or info.disabled:
			continue
		committed = _open_pick_reserved_qty(row.item_code, bin_name)
		items.append(
			{
				"item_code": row.item_code,
				"item_name": info.item_name or row.item_code,
				"uom": info.stock_uom,
				"image": info.image,
				"on_hand": flt(row.actual_qty),
				"committed": committed,
				"available": flt(row.actual_qty) - committed,
			}
		)
	items.sort(key=lambda entry: entry["item_name"])
	return {
		"resolved": True,
		"kind": "bin",
		"warehouse": bin_name,
		"label": _warehouse_label(bin_name),
		"items": items,
	}


@frappe.whitelist()
def receive_scan(package_name: str, code: str, quantity: float = 1) -> dict:
	"""Scan an item into a receiving session.

	Tier 1 (known barcode) confirms the quantity straight away - a repeat scan of the
	same code simply increments. Anything unresolved comes back `resolved: False` so the
	caller can offer provisional capture; it is never an error.
	"""
	doc = _writable_package(package_name)
	code = (code or "").strip()
	if not code:
		frappe.throw("Scan or enter an item barcode.")

	item_code = _resolve_scanned_item(code)
	if not item_code:
		return {"resolved": False, "code": code, "package": doc.name}
	# Item codes are global, but an item belongs to one client (through its item group). Never receive
	# another client's item into this client's package.
	owner = _item_client(item_code)
	if owner and doc.get("customer") and owner != doc.get("customer"):
		frappe.throw(f"{code} is {owner}'s item ({item_code}), but this package is for {doc.get('customer')}.")

	result = receive_item(doc.name, item_code, quantity)
	result["resolved"] = True
	result["tier"] = 1
	return result


# --- New items at receive: naming standard and prefill (RECEIVE_WORKFLOW_PROJECT.md) ---------------
DEFAULT_ITEM_NAME_TEMPLATE = "{PRODUCT} {COLOR} {SIZE}"
SIZE_ORDER = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL", "OS"]


def _item_client(item_code: str) -> str | None:
	"""The client an item belongs to: the Customer whose item group sits above the item's group."""
	group = frappe.db.get_value("Item", item_code, "item_group")
	seen = set()
	while group and group not in seen and group != "All Item Groups":
		if frappe.db.exists("Customer", group):
			return group
		seen.add(group)
		group = frappe.db.get_value("Item Group", group, "parent_item_group")
	return None


def _client_groups(customer: str) -> list[str]:
	"""The client's product-type groups (leaf groups under the client's own item group)."""
	if not customer or not frappe.db.exists("Item Group", customer):
		return []
	bounds = frappe.db.get_value("Item Group", customer, ["lft", "rgt"], as_dict=True)
	return frappe.get_all(
		"Item Group",
		filters={"lft": [">", bounds.lft], "rgt": ["<", bounds.rgt], "is_group": 0},
		pluck="name",
		order_by="name asc",
	)


def _client_items(customer: str) -> list[dict]:
	groups = _client_groups(customer)
	if not groups:
		return []
	return frappe.get_all(
		"Item",
		filters={"item_group": ["in", groups]},
		fields=["name", "item_name", "item_group", "soy_product", "soy_color", "soy_size", "soy_collection"],
		order_by="name asc",
		limit_page_length=0,
	)


def _name_template(customer: str | None) -> str:
	template = customer and frappe.db.get_value("Customer", customer, "soy_item_name_template")
	return template or DEFAULT_ITEM_NAME_TEMPLATE


def _render_item_name(template: str, product: str, color: str, size: str) -> str:
	name = template.replace("{PRODUCT}", product or "").replace("{COLOR}", color or "").replace("{SIZE}", size or "")
	return re.sub(r"\s+", " ", name).strip().upper()


def _related_item(code: str, items: list[dict]) -> tuple[dict | None, int | None]:
	"""An existing item whose code differs from `code` in exactly one dash-separated segment
	(EXC-BT-PNK-XXL vs EXC-BT-PNK-L). Prefers a difference in the last segment (a new size)."""
	parts = code.upper().split("-")
	if len(parts) < 2:
		return None, None
	best = None
	for item in items:
		other = item.name.upper().split("-")
		if len(other) != len(parts):
			continue
		diffs = [i for i, (a, b) in enumerate(zip(parts, other, strict=True)) if a != b]
		if len(diffs) != 1:
			continue
		if diffs[0] == len(parts) - 1:
			return item, diffs[0]
		best = best or (item, diffs[0])
	return best or (None, None)


@frappe.whitelist()
def receive_item_suggestion(package_name: str, code: str) -> dict:
	"""What the confirm sheet needs for a barcode that is not in the catalogue: the client's existing
	products, colors, sizes and groups to pick from, and a prefill from a related item when one exists."""
	from soypaq.traits import COLOR_CODES

	doc = _writable_package(package_name)
	code = (code or "").strip()
	customer = doc.get("customer")
	items = _client_items(customer)
	products = {}
	for item in items:
		if item.soy_product and item.soy_product not in products:
			products[item.soy_product] = {
				"product": item.soy_product,
				"group": item.item_group,
				"collection": item.soy_collection or "",
			}
	colors = sorted({item.soy_color for item in items if item.soy_color})
	sizes = sorted(
		{item.soy_size for item in items if item.soy_size},
		key=lambda s: (SIZE_ORDER.index(s) if s in SIZE_ORDER else 99, s),
	)
	# Offer product types only: not the holding group, nor a leftover season group (Summer_2026).
	groups = [g for g in _client_groups(customer) if not g.endswith(" - Unsorted") and not re.fullmatch(r"[A-Za-z]+_\d{4}", g)]
	prefill = {"product": "", "color": "", "size": "", "group": "", "collection": ""}
	related, position = _related_item(code, items)
	if related:
		prefill = {
			"product": related.soy_product or "",
			"color": related.soy_color or "",
			"size": related.soy_size or "",
			"group": related.item_group,
			"collection": related.soy_collection or "",
		}
		segment = code.upper().split("-")[position]
		if position == len(code.split("-")) - 1:
			prefill["size"] = segment
		else:
			prefill["color"] = COLOR_CODES.get(segment, segment.title())
	return {
		"code": code,
		"barcode_type": _barcode_type(code),
		"template": _name_template(customer),
		"prefill": prefill,
		"related": related.name if related else "",
		"products": list(products.values()),
		"colors": colors,
		"sizes": sizes,
		"groups": groups,
	}


@frappe.whitelist()
def receive_new_item(
	package_name: str,
	code: str,
	product: str,
	color: str = "",
	size: str = "",
	item_group: str = "",
	collection: str = "",
	quantity: float = 1,
	flag: int = 0,
	note: str = "",
) -> dict:
	"""Create the item for an unknown barcode the way the catalogue is built, then receive it.

	Code = the barcode; name from the client's template (`{PRODUCT} {COLOR} {SIZE}`, capitals); traits set;
	group must be one of the client's own. Flagged for review when the worker asks, or when the product
	type, color or size is missing.
	"""
	doc = _writable_package(package_name)
	code = (code or "").strip()
	product = re.sub(r"\s+", " ", product or "").strip()
	color = re.sub(r"\s+", " ", color or "").strip()
	size = (size or "").strip().upper()
	if not code:
		frappe.throw("Scan or enter the item barcode.")
	if not product:
		frappe.throw("Pick or type the product.")
	if _resolve_scanned_item(code):
		return receive_scan(doc.name, code, quantity)
	if frappe.db.exists("Item", code):
		frappe.throw(f"Item code {code} already exists but is disabled. Enable it in Desk to receive it.")
	customer = doc.get("customer")
	groups = _client_groups(customer)
	group = item_group if item_group in groups else _unsorted_item_group(customer)
	missing = [label for label, value in (("type", item_group in groups), ("color", color), ("size", size)) if not value]
	needs_review = cint(flag) or bool(missing)

	item = frappe.new_doc("Item")
	item.item_code = code
	item.item_name = _render_item_name(_name_template(customer), product, color, size)
	item.item_group = group
	item.stock_uom = "Nos"
	item.is_stock_item = 1
	item.soy_product = product
	item.soy_color = color
	item.soy_size = size
	item.soy_collection = (collection or "").strip()
	item.append("barcodes", {"barcode": code, "barcode_type": _barcode_type(code)})
	if needs_review:
		item.soy_needs_review = 1
		reasons = [note.strip()] if (note or "").strip() else []
		if missing:
			reasons.append(f"Created at receive without {', '.join(missing)}")
		item.soy_review_reason = "; ".join(reasons) or "Flagged at receive"
		item.soy_flagged_by = frappe.session.user
	item.insert(ignore_permissions=True)

	result = receive_item(doc.name, item.name, quantity)
	result.update(
		{"resolved": True, "created": item.name, "item_name": item.item_name, "needs_review": bool(needs_review)}
	)
	return result


@frappe.whitelist()
def set_received_qty(package_name: str, item_code: str, quantity: float) -> dict:
	"""Set a line's counted quantity directly (the line's number field). 0 removes an unstaged line."""
	doc = _writable_package(package_name)
	row = _package_row(doc, item_code)
	if row.get("assigned_bin"):
		frappe.throw(f"{row.item_code} is already staged - its quantity can no longer change.")
	quantity = flt(quantity)
	if quantity < 0:
		frappe.throw("Quantity cannot be negative.")
	if quantity == 0:
		doc.remove(row)
		doc.last_scan_action = f"Removed {item_code}"
	else:
		row.received_qty = quantity
		row.condition = row.get("condition") or "Good"
		doc.last_scan_action = f"Set {item_code} to {quantity:g}"
	doc.status = "Inspecting"
	doc.save()
	_publish_task_update(doc)
	return {"name": doc.name, "item_code": item_code, "received_qty": quantity}


@frappe.whitelist()
def set_item_group(package_name: str, item_code: str, item_group: str) -> dict:
	"""Floor correction of an item's product type, limited to the package client's own groups.
	Flags the item so Soy Ops sees the change (old and new group in the reason)."""
	doc = _writable_package(package_name)
	_package_row(doc, item_code)
	if item_group not in _client_groups(doc.get("customer")):
		frappe.throw(f"{item_group} is not one of {doc.get('customer')}'s item groups.")
	old = frappe.db.get_value("Item", item_code, "item_group")
	if old == item_group:
		return {"item_code": item_code, "item_group": item_group}
	frappe.db.set_value(
		"Item",
		item_code,
		{
			"item_group": item_group,
			"soy_needs_review": 1,
			"soy_review_reason": f"Group changed on the floor from {old} to {item_group}",
			"soy_flagged_by": frappe.session.user,
		},
	)
	return {"item_code": item_code, "item_group": item_group, "previous": old}


@frappe.whitelist()
def flag_item(package_name: str, item_code: str, reason: str = "") -> dict:
	"""Floor flag: something about this item needs Soy Ops to look (color, size, name...)."""
	doc = _writable_package(package_name)
	_package_row(doc, item_code)
	frappe.db.set_value(
		"Item",
		item_code,
		{
			"soy_needs_review": 1,
			"soy_review_reason": (reason or "").strip() or f"Flagged at receive on {doc.name}",
			"soy_flagged_by": frappe.session.user,
		},
	)
	return {"item_code": item_code, "needs_review": True}


@frappe.whitelist()
def capture_provisional_item(
	package_name: str, code: str, item_name: str, quantity: float = 1, notes: str = ""
) -> dict:
	"""Tier 3: record something nobody can identify, and keep the box moving.

	Creates a real Item (stock cannot be posted against a non-existent one) in a clearly
	marked group, attaches the scanned code as its barcode, and logs an Inventory Action
	so the item lands in a review queue instead of quietly becoming permanent catalogue
	data. The worker never blocks waiting for someone with catalogue access.
	"""
	doc = _writable_package(package_name)
	code = (code or "").strip()
	item_name = (item_name or "").strip()
	if not code or not item_name:
		frappe.throw("A scanned code and a description are both required.")

	existing = _resolve_scanned_item(code)
	if existing:
		return receive_scan(doc.name, code, quantity)

	if frappe.db.exists("Item", code):
		frappe.throw(f"Item code {code} already exists but is disabled. Enable it in Desk to receive it.")

	# Standard naming: the item code IS the scanned barcode (what every catalogue item already does), so a
	# later scan of the same code resolves to this item. It lands in the client's own "Unsorted" group
	# (under the client's item group, which is what ties an item to its client), with Needs Review set.
	item = frappe.new_doc("Item")
	item.item_code = code
	item.item_name = item_name
	item.item_group = _unsorted_item_group(doc.get("customer"))
	item.stock_uom = "Nos"
	item.is_stock_item = 1
	item.append("barcodes", {"barcode": code, "barcode_type": _barcode_type(code)})
	item.soy_needs_review = 1
	item.soy_review_reason = "Not in the catalogue when it was received"
	item.soy_flagged_by = frappe.session.user
	item.insert(ignore_permissions=True)

	action = frappe.new_doc("Inventory Action")
	action.item_code = item.name
	action.warehouse = doc.get("target_warehouse")
	action.action_type = "Provisional Item"
	action.reason_code = "Provisional"
	action.notes = notes or f"Captured during receiving on {doc.name} as '{item_name}'"
	action.source_document_type = "Inbound Package"
	action.source_document_name = doc.name
	action.created_by_user = frappe.session.user
	action.insert(ignore_permissions=True)

	result = receive_item(doc.name, item.name, quantity)
	result.update({"resolved": True, "tier": 3, "provisional": True, "action_id": action.name})
	return result


def _writable_package(name: str):
	if not name or not frappe.db.exists("Inbound Package", name):
		frappe.throw(f"Inbound Package {name or ''} was not found.")
	doc = frappe.get_doc("Inbound Package", name)
	if not doc.has_permission("write"):
		frappe.throw(f"You do not have permission to update Inbound Package {name}.", frappe.PermissionError)
	if doc.get("status") in ("Stored", "Consolidated", "Shipped", "Delivered", "Cancelled"):
		frappe.throw(f"Inbound Package {name} is already {doc.get('status')}.")
	return doc


PROVISIONAL_ITEM_GROUP = "Provisional - Needs Review"


def _barcode_type(code: str) -> str:
	"""Barcode type from the code itself: retail digits by length, otherwise CODE-39 like the catalogue."""
	if code.isdigit():
		return {13: "EAN-13", 12: "UPC-A", 8: "EAN-8"}.get(len(code), "CODE-39")
	return "CODE-39"


def _unsorted_item_group(customer: str | None) -> str:
	"""The client's own group for items nobody has classified yet; the old shared group if the client has none."""
	tenant_group = customer if customer and frappe.db.exists("Item Group", customer) else None
	if not tenant_group:
		if not frappe.db.exists("Item Group", PROVISIONAL_ITEM_GROUP):
			group = frappe.new_doc("Item Group")
			group.item_group_name = PROVISIONAL_ITEM_GROUP
			group.parent_item_group = "All Item Groups"
			group.is_group = 0
			group.insert(ignore_permissions=True)
		return PROVISIONAL_ITEM_GROUP
	name = f"{tenant_group} - Unsorted"
	if not frappe.db.exists("Item Group", name):
		group = frappe.new_doc("Item Group")
		group.item_group_name = name
		group.parent_item_group = tenant_group
		group.is_group = 0
		group.insert(ignore_permissions=True)
	return name


def _zone_warehouse(zone: str, company: str | None = None) -> str | None:
	"""Resolve a named zone (e.g. "Damaged", "Receiving") to a leaf Warehouse."""
	filters = {"is_group": 0, "disabled": 0, "warehouse_name": ["like", f"%{zone}%"]}
	if company:
		filters["company"] = company
	return frappe.db.get_value("Warehouse", filters, "name", order_by="name asc")


def _package_row(doc, item_code: str, create: bool = False, item_name: str = None, barcode: str = None):
	"""Find a line on the package, optionally adding one that was never expected.

	Receiving here is *discovery*: nobody tells the warehouse what is arriving, so an
	item that is not already on the package is the normal case, not an error. Callers
	that are genuinely correcting an existing line pass create=False.
	"""
	item_code = (item_code or "").strip()
	if not item_code:
		frappe.throw("Scan or enter an item barcode.")
	row = next((row for row in doc.get("package_items") or [] if row.get("item_code") == item_code), None)
	if row:
		return row
	if not create:
		frappe.throw(f"Item {item_code} is not on Inbound Package {doc.name}.")
	if not frappe.db.exists("Item", item_code):
		frappe.throw(f"Item {item_code} does not exist - capture it as a provisional item first.")
	return doc.append(
		"package_items",
		{
			"item_code": item_code,
			"item_name": item_name or frappe.db.get_value("Item", item_code, "item_name") or item_code,
			"barcode": barcode or item_code,
			"quantity": 0,  # nothing was "expected" - received_qty is the truth
			"received_qty": 0,
			"condition": "Good",
			"target_warehouse": doc.get("target_warehouse"),
		},
	)


@frappe.whitelist()
def receive_item(package_name: str, item_code: str, quantity: float = 1) -> dict:
	"""Confirm a quantity of a single expected item was physically counted."""
	doc = _writable_package(package_name)
	row = _package_row(doc, item_code, create=True)
	if row.get("assigned_bin"):
		frappe.throw(f"{row.item_code} is already staged - it can no longer be re-confirmed.")
	quantity = flt(quantity)
	if quantity <= 0:
		frappe.throw("Confirm quantity must be greater than zero.")
	# No cap. In blind receiving there is no expected quantity to over-receive against -
	# received_qty *is* the truth. Any `quantity` on the row is advisory only.
	row.received_qty = flt(row.get("received_qty")) + quantity
	row.condition = row.get("condition") or "Good"
	doc.status = "Inspecting"
	doc.scan_item_barcode = item_code
	doc.last_scanned_row = row.name
	doc.last_scan_action = f"Confirmed {quantity:g} x {row.item_code}"
	doc.save()
	_publish_task_update(doc)
	return {"name": doc.name, "item_code": row.item_code, "received_qty": row.received_qty}


@frappe.whitelist()
def unreceive_item(package_name: str, item_code: str, quantity: float = 1) -> dict:
	"""Reduce a confirmed quantity on an Inbound Package row."""
	doc = _writable_package(package_name)
	row = _package_row(doc, item_code)
	if row.get("assigned_bin"):
		frappe.throw(f"{row.item_code} is already staged - it can no longer be re-confirmed.")
	quantity = flt(quantity)
	if quantity <= 0:
		frappe.throw("Confirm quantity must be greater than zero.")
	if flt(row.get("received_qty")) <= 0:
		frappe.throw(f"No confirmed quantity remains to remove for {row.item_code}.")
	row.received_qty = max(flt(row.get("received_qty")) - quantity, 0)
	doc.status = "Inspecting"
	doc.scan_item_barcode = item_code
	doc.last_scanned_row = row.name
	doc.last_scan_action = f"Removed {quantity:g} x {row.item_code} from confirmed count"
	doc.save()
	_publish_task_update(doc)
	return {"name": doc.name, "item_code": row.item_code, "received_qty": row.received_qty}


@frappe.whitelist()
def receive_all(package_name: str) -> dict:
	"""Demo helper that confirms every expected item at its full expected quantity."""
	doc = _writable_package(package_name)
	for row in doc.get("package_items") or []:
		if row.get("assigned_bin") or row.get("condition") == "Missing":
			continue
		row.received_qty = flt(row.get("quantity"))
		row.condition = row.get("condition") or "Good"
	doc.status = "Inspecting"
	doc.last_scan_action = "Confirmed all expected items"
	doc.save()
	_publish_task_update(doc)
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def flag_receive_item(package_name: str, item_code: str, reason: str) -> dict:
	"""Set a received line's condition: an exception (Damaged / Missing / Hold / Unknown SKU), or Good to clear one."""
	allowed = {"Good", "Damaged", "Missing", "Hold", "Unknown SKU"}
	if reason not in allowed:
		frappe.throw("Choose a valid receiving exception reason.")
	doc = _writable_package(package_name)
	row = _package_row(doc, item_code)
	if row.get("assigned_bin"):
		frappe.throw(f"{row.item_code} is already staged - it can no longer be flagged.")
	row.condition = reason
	if reason == "Missing":
		row.received_qty = 0
	doc.status = "Inspecting"
	doc.last_scan_action = f"Flagged {row.item_code}: {reason}"
	doc.save()
	_publish_task_update(doc)
	return {"name": doc.name, "item_code": row.item_code, "condition": row.condition}


@frappe.whitelist()
def stage_item(package_name: str, item_code: str, bin_code: str) -> dict:
	"""Assign a confirmed item to a real bin.

	This no longer posts stock. Staging one Stock Entry per item made a 40-line box
	produce 40 vouchers; the whole package now posts a single Stock Entry when the
	session is finished (see complete_receipt). The row is saved as it is scanned, so
	nothing is lost if the session is interrupted - only the stock posting is deferred.
	"""
	doc = _writable_package(package_name)
	row = _package_row(doc, item_code)
	if row.get("assigned_bin"):
		frappe.throw(f"{row.item_code} is already staged at {row.assigned_bin}.")
	if flt(row.get("received_qty")) <= 0:
		frappe.throw(f"Confirm {row.item_code} before staging it.")
	# Resolved inside the package's own client, so a short code like A01 can never land in another client's bin.
	package_company = doc.get("customer") if frappe.db.exists("Company", doc.get("customer") or "") else None
	bin_warehouse = _resolve_bin(bin_code, package_company)

	# Damaged stock must not land in normal storage counting as available. Route it to
	# the Damaged warehouse so the condition flag has an actual stock consequence.
	routed = False
	if row.get("condition") == "Damaged":
		company = _warehouse_company(bin_warehouse) or _warehouse_company(doc.get("target_warehouse"))
		damaged = _zone_warehouse("Damaged", company)
		if damaged and damaged != bin_warehouse:
			bin_warehouse = damaged
			routed = True

	row.assigned_bin = bin_warehouse
	doc.status = "Inspecting"
	doc.last_scan_action = f"Staged {row.item_code} to {bin_warehouse}" + (
		" (damaged - rerouted)" if routed else ""
	)
	doc.save()
	_publish_task_update(doc)
	return {
		"name": doc.name,
		"item_code": row.item_code,
		"assigned_bin": bin_warehouse,
		"rerouted_as_damaged": routed,
	}


@frappe.whitelist()
def complete_receipt(package_name: str) -> dict:
	"""Post the whole package as ONE Stock Entry, then close out the session.

	This is the commit point. Rows were saved as they were scanned, but no stock moved
	until now - so a 40-line package produces one Material Receipt instead of forty.
	"""
	doc = _writable_package(package_name)
	pending = [
		row.item_code
		for row in doc.get("package_items") or []
		if not row.get("assigned_bin") and row.get("condition") != "Missing"
	]
	if pending:
		frappe.throw(f"Stage every item into a bin before storing: {', '.join(pending)}")

	postable = [
		{
			"item_code": row.item_code,
			"qty": flt(row.get("received_qty")),
			"uom": row.get("uom"),
			"t_warehouse": row.get("assigned_bin"),
		}
		for row in doc.get("package_items") or []
		if row.get("assigned_bin") and flt(row.get("received_qty")) > 0
	]
	if postable:
		company = _warehouse_company(postable[0]["t_warehouse"]) or _warehouse_company(
			doc.get("target_warehouse")
		)
		entry = _create_stock_entry("Material Receipt", postable, company=company)
		doc.stock_entry_reference = entry.name

	doc.status = "Stored"
	doc.received_by = frappe.session.user
	doc.received_at = now_datetime()
	doc.save()
	_publish_task_update(doc)
	if doc.get("inbound_asn") and frappe.db.exists("Inbound ASN", doc.inbound_asn):
		asn = frappe.get_doc("Inbound ASN", doc.inbound_asn)
		asn.status = "Received"
		asn.save(ignore_permissions=True)
		_publish_task_update(asn)
	return {
		"name": doc.name,
		"status": doc.status,
		"stock_entry": doc.get("stock_entry_reference") or "",
		"lines": [
			{"item_code": row.item_code, "qty": flt(row.get("received_qty")), "bin": row.get("assigned_bin")}
			for row in doc.get("package_items") or []
			if row.get("assigned_bin") and flt(row.get("received_qty")) > 0
		],
	}


def _open_pick_reserved_qty(item_code: str, warehouse: str) -> float:
	"""Sum of qty other open Pick Tasks still intend to take for this item/warehouse.

	Not ERPNext's native `Bin.reserved_qty` - that field is only ever populated by
	Sales-Order-driven Stock Reservation Entry (erpnext/stock/doctype/stock_reservation_entry),
	which requires a Sales Order voucher. Pick Tasks created here have no source order
	(see create_pick_task docstring), so that native mechanism has nothing to attach to
	until Medusa order ingestion makes Pick Tasks order-backed. This is the interim stand-in -
	swap it for get_sre_reserved_qty_details_for_voucher once that lands.
	"""
	rows = frappe.get_all(
		"Pick Task Item",
		filters={
			"item_code": item_code,
			"source_warehouse": warehouse,
			"parenttype": "Pick Task",
			"parent": [
				"in",
				frappe.get_all(
					"Pick Task", filters={"status": ["not in", ["Completed", "Cancelled"]]}, pluck="name"
				),
			],
		},
		fields=["required_qty", "picked_qty"],
	)
	return sum(max(flt(row.required_qty) - flt(row.picked_qty), 0) for row in rows)


PICK_NAMING_SERIES = "PICK-MIA-.#####"


@frappe.whitelist()
def preview_pick_task_names(count: int = 8) -> list[str]:
	"""The next Pick Task names, for the builder sheet to label each pending task.

	A preview only: the real name is assigned when the task is inserted, so another operator
	creating a task in between makes the actual name differ. create_pick_task returns the real ones.
	"""
	prefix = PICK_NAMING_SERIES.split(".")[0]
	digits = PICK_NAMING_SERIES.count("#")
	# `tabSeries` has no `creation` column, so get_value (which orders by it) cannot be used.
	row = frappe.db.sql("select `current` from `tabSeries` where name = %s", prefix)
	current = cint(row[0][0]) if row else 0
	return [f"{prefix}{current + i + 1:0{digits}d}" for i in range(max(1, min(cint(count), 20)))]


@frappe.whitelist()
def create_pick_task(customer: str = None, warehouse: str = None, items=None) -> dict:
	"""Create a real, standalone Pick Task for testing when no Sales Order exists yet.

	One task, even when the items sit in different bins: each line carries its own bin (the
	line's `warehouse`, else the `warehouse` argument, else the default Storage zone) and the
	picker confirms each bin as they reach it (see confirm_pick_location). A task holds an item in
	one bin, so the same item on two lines in different bins is rejected; repeats in the same bin
	merge. Availability is checked per bin before anything is created.

	The record is a genuine Pick Task (not a mock) - it immediately works with
	confirm_pick_location / pick_item / unpick_item / flag_pick_item / complete_pick.
	Returns `name`/`route` plus a one-entry `tasks` list (the shape the builder expects).
	"""
	rows = _parse_manual_items(items)
	# Zone-resolved, not DEFAULT_COMPANY-resolved: the sanitized public-mirror constant
	# matches nothing on a real site, which made this throw for every real caller.
	default_warehouse = warehouse or _zone_warehouse("Storage")

	lines: dict[str, dict] = {}
	for row in rows:
		bin_name = row.get("warehouse") or default_warehouse
		if not bin_name:
			frappe.throw("No warehouse is configured in ERPNext.")
		line = lines.get(row["item_code"])
		if not line:
			lines[row["item_code"]] = {**row, "bin": bin_name}
		elif line["bin"] != bin_name:
			frappe.throw(
				f"{row['item_code']} is on this pick from two bins ({line['bin']} and {bin_name}). "
				"A pick task holds an item in one bin - use one line per item."
			)
		else:
			line["quantity"] = flt(line["quantity"]) + flt(row["quantity"])

	# Available = on-hand minus what other open Pick Tasks already intend to take -
	# without this, two pickers (or one picker starting two tasks) could both be told
	# there's enough stock for the same physical units.
	for item_code, line in lines.items():
		on_hand = flt(
			frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": line["bin"]}, "actual_qty") or 0
		)
		already_reserved = _open_pick_reserved_qty(item_code, line["bin"])
		available_qty = on_hand - already_reserved
		if flt(line["quantity"]) > available_qty:
			frappe.throw(
				f"Only {available_qty:g} units of {item_code} available in {line['bin']} "
				f"({on_hand:g} on hand, {already_reserved:g} already committed to other open picks) - "
				f"cannot pick {flt(line['quantity']):g}."
			)

	ordered = sorted(lines.values(), key=lambda line: (line["bin"], line["item_name"] or line["item_code"]))
	bins = list(dict.fromkeys(line["bin"] for line in ordered))
	companies = {_warehouse_company(bin_name) for bin_name in bins}
	if len(companies) > 1:
		frappe.throw("The bins in one pick task must belong to the same company.")

	if not customer:
		# DEFAULT_TEST_CUSTOMER is the same sanitized-mirror problem as DEFAULT_COMPANY -
		# infer from the warehouse's company instead, which matches on this site because
		# a 3PL tenant's Customer and Company share a name by convention (see AGENT.md).
		company = next(iter(companies), "")
		if company and frappe.db.exists("Customer", company):
			customer = company

	doc = frappe.new_doc("Pick Task")
	doc.naming_series = PICK_NAMING_SERIES
	doc.status = "Pending"
	doc.customer = _resolve_customer(customer)
	doc.warehouse = bins[0]
	doc.pick_state = "Waiting for Bin"
	doc.scan_bin = bins[0]
	doc.scan_item_barcode = ordered[0]["item_code"]
	doc.current_status = (
		f"Manually created with {len(ordered)} line(s) across {len(bins)} bins, no source order"
		if len(bins) > 1
		else f"Manually created with {len(ordered)} line(s), no source order"
	)
	for line in ordered:
		doc.append(
			"pick_items",
			{
				"item_code": line["item_code"],
				"item_name": line["item_name"],
				"uom": line["uom"],
				"required_qty": line["quantity"],
				"picked_qty": 0,
				"source_warehouse": line["bin"],
				"source_bin": line["bin"],
				"status": "Pending",
			},
		)
	_update_pick_totals(doc)
	doc.insert()
	_publish_task_update(doc)
	route = _route("Pick Task", doc.name)
	return {
		"name": doc.name,
		"route": route,
		"tasks": [{"name": doc.name, "warehouses": bins, "route": route}],
	}


@frappe.whitelist()
def confirm_pick_location(task_name: str, location_code: str) -> dict:
	"""Persist a validated bin scan on a Pick Task.

	Single-bin task: the code must be the task's bin. Multi-bin task: the code may be any of its
	bins (full name or short code); only that bin's rows are unlocked, and `scan_bin` moves on to
	the next bin still to confirm.
	"""
	doc = _writable_task("Pick Task", task_name)
	location_code = (location_code or "").strip()
	bins = _pick_bins(doc)

	if len(bins) > 1:
		match = next((b for b in bins if b.casefold() == location_code.casefold()), None)
		if not match and location_code:
			try:
				resolved = _resolve_bin(location_code, company=doc.get("customer"))
			except frappe.ValidationError:
				resolved = None
			match = resolved if resolved in bins else None
		if not match:
			frappe.throw(
				f"{location_code or 'Blank'} is not a bin on this pick task. Bins: {', '.join(bins)}."
			)
		for row in doc.get("pick_items") or []:
			if _row_bin(row) == match:
				row.bin_confirmed = 1
		pending = [b for b in bins if not all(
			cint(r.get("bin_confirmed")) for r in doc.get("pick_items") or [] if _row_bin(r) == b
		)]
		doc.scan_bin = pending[0] if pending else match
		location_code = match
	else:
		expected = doc.get("scan_bin") or doc.get("warehouse")
		if not expected or location_code.casefold() != str(expected).casefold():
			frappe.throw(
				f"Expected location {expected or 'not configured'}, received {location_code or 'blank'}."
			)
		for row in doc.get("pick_items") or []:
			row.bin_confirmed = 1

	doc.status = "Picking"
	doc.pick_state = "Waiting for Item"
	doc.last_scan_action = f"Scanned bin {location_code}"
	doc.current_status = f"Location {location_code} confirmed"
	doc.save()
	_publish_task_update(doc)
	return {"name": doc.name, "location": location_code, "status": doc.status}


@frappe.whitelist()
def pick_item(task_name: str, item_code: str, quantity: float = 1) -> dict:
	"""Persist an item scan and picked quantity on a Pick Task row.

	Stock stays put in its real storage bin through Pick and Pack - the only real
	stock move happens once, at ship time, straight out of that same bin.
	"""
	doc = _writable_task("Pick Task", task_name)
	row = _task_row(doc, item_code)
	_require_bin_confirmed(doc, row, "Confirm the pick location before scanning an item.")
	quantity = flt(quantity)
	if quantity <= 0:
		frappe.throw("Pick quantity must be greater than zero.")
	remaining = max(flt(row.required_qty) - flt(row.picked_qty), 0)
	if quantity > remaining:
		frappe.throw(f"Only {remaining:g} units remain for {row.item_code}.")

	row.picked_qty = flt(row.picked_qty) + quantity
	row.status = "Picked" if row.picked_qty >= flt(row.required_qty) else "Pending"
	doc.status = "Picking"
	doc.scan_item_barcode = item_code
	doc.last_scanned_row = row.name
	doc.last_scan_action = f"Picked {quantity:g} x {row.item_code}"
	_update_pick_totals(doc)
	doc.save()
	_log_pick_action(doc, "Picked", row.item_code, quantity)
	_sync_pack_from_pick(doc)
	_publish_task_update(doc)
	return {"name": doc.name, "item_code": row.item_code, "picked_qty": row.picked_qty}


@frappe.whitelist()
def unpick_item(task_name: str, item_code: str, quantity: float = 1) -> dict:
	"""Reduce a picked quantity on a Pick Task row."""
	doc = _writable_task("Pick Task", task_name)
	row = _task_row(doc, item_code)
	_require_bin_confirmed(doc, row, "Confirm the pick location before changing an item.")
	quantity = flt(quantity)
	if quantity <= 0:
		frappe.throw("Pick quantity must be greater than zero.")
	if flt(row.picked_qty) <= 0:
		frappe.throw(f"No picked quantity remains to remove for {row.item_code}.")

	row.picked_qty = max(flt(row.picked_qty) - quantity, 0)
	row.status = "Picked" if row.picked_qty >= flt(row.required_qty) else "Pending"
	doc.status = "Picking"
	doc.scan_item_barcode = item_code
	doc.last_scanned_row = row.name
	doc.last_scan_action = f"Removed {quantity:g} x {row.item_code}"
	_update_pick_totals(doc)
	doc.save()
	_log_pick_action(doc, "Unpicked", row.item_code, quantity)
	_sync_pack_from_pick(doc)
	_publish_task_update(doc)
	return {"name": doc.name, "item_code": row.item_code, "picked_qty": row.picked_qty}


@frappe.whitelist()
def pick_all(task_name: str) -> dict:
	"""Demo helper that persists all remaining Pick Task quantities."""
	doc = _writable_task("Pick Task", task_name)
	if doc.get("pick_state") != "Waiting for Item":
		frappe.throw("Confirm the pick location before confirming item quantities.")
	for row in doc.get("pick_items") or []:
		if frappe.db.get_value("Item", row.item_code, "disabled"):
			frappe.throw(f"Item {row.item_code} is disabled in ERPNext.")
		row.bin_confirmed = 1  # confirming every quantity implies every bin
		remaining = max(flt(row.required_qty) - flt(row.picked_qty), 0)
		if remaining <= 0:
			continue
		row.picked_qty = flt(row.required_qty)
		row.status = "Picked"
	doc.status = "Picking"
	doc.last_scan_action = "Confirmed all remaining task quantities"
	_update_pick_totals(doc)
	doc.save()
	_sync_pack_from_pick(doc)
	_publish_task_update(doc)
	return {"name": doc.name, "picked_qty": doc.total_picked_qty}


@frappe.whitelist()
def flag_pick_item(
	task_name: str,
	item_code: str,
	reason: str,
	handpick: int = 0,
	quantity: float = 0,
	note: str = "",
	image: str = "",
) -> dict:
	"""Persist a manual pick action or exception reason on a Pick Task row."""
	# Whitelisted args arrive as strings off the wire; "0" is truthy in Python, so
	# `if handpick:` on the raw value treated every reason-button flag (which sends
	# handpick=0) as a handpick - silently marking Short/Damaged/Wrong Item/No Stock
	# rows "Picked" instead of "Short". cint() is the real bool.
	handpick = cint(handpick)
	doc = _writable_task("Pick Task", task_name)
	row = _task_row(doc, item_code)
	_require_bin_confirmed(doc, row, "Confirm the pick location before updating an item.")
	reason = (reason or "").strip()
	allowed = {"Damaged", "No Stock", "Barcode Issue", "Short Picked", "Wrong Item"}
	if reason not in allowed:
		frappe.throw("Choose a valid pick exception reason.")

	quantity = flt(quantity)
	if handpick:
		quantity = quantity or 1
		remaining = max(flt(row.required_qty) - flt(row.picked_qty), 0)
		if quantity > remaining:
			frappe.throw(f"Only {remaining:g} units remain for {row.item_code}.")
		row.picked_qty = flt(row.picked_qty) + quantity
		row.status = "Picked" if row.picked_qty >= flt(row.required_qty) else "Pending"
	else:
		row.status = "Short"

	row.exception_reason = reason
	note = (note or "").strip()
	if note:
		row.exception_note = note
	if image:
		row.exception_image = image
	doc.status = "Picking"
	doc.scan_item_barcode = item_code
	doc.last_scanned_row = row.name
	doc.last_scan_action = f"{'Handpicked' if handpick else 'Flagged'} {row.item_code}: {reason}"
	_update_pick_totals(doc)
	doc.save()
	_log_pick_action(
		doc,
		"Handpicked" if handpick else "Exception",
		row.item_code,
		quantity,
		exception_reason=reason,
		note=note,
		image=image,
	)
	_sync_pack_from_pick(doc)
	_publish_task_update(doc)
	return {"name": doc.name, "item_code": row.item_code, "status": row.status, "exception_reason": reason}


def _auto_complete_downstream(pick_task) -> None:
	"""Bypass path for `skip_downstream`: the operator isn't packing/shipping through the
	WMS, but the Pack Task / Shipment Task / Delivery Note still need to exist and be
	real, completed records - not skipped entirely - so (a) stock actually decrements
	at the real point (Delivery Note) instead of silently never leaving, and (b) a future
	webhook/API integration (Medusa, etc. - see MEDUSA_INTEGRATION.md) has a completed
	template it can read fulfilment/tracking data from or patch in later, rather than a
	gap where no downstream doctype was ever created.

	No Shippo label is purchased here (that's a real paid API call) - tracking_number is
	left blank for a human or a future integration to fill in.
	"""
	_create_pack_task_from_pick(pick_task)
	pack_names = frappe.get_all(
		"Pack Task",
		filters={"warehouse": pick_task.name, "status": ["not in", ["Completed", "Cancelled"]]},
		pluck="name",
	)
	for pack_name in pack_names:
		pack_task = frappe.get_doc("Pack Task", pack_name)
		for row in pack_task.get("pick_items") or []:
			row.packed_qty = flt(row.picked_qty)
		pack_task.box_confirmed = 1
		pack_task.status = "Completed"
		pack_task.current_status = "Packing auto-completed - packing/shipping handled outside SoyPaq"
		pack_task.completed_by = frappe.session.user
		pack_task.completed_at = now_datetime()
		_update_pack_totals(pack_task)
		pack_task.save(ignore_permissions=True)
		_publish_task_update(pack_task)

		_create_shipment_task_from_pack(pack_task)
		shipment_names = frappe.get_all(
			"Shipment Task",
			filters={"warehouse": pack_task.name, "status": ["not in", ["Shipped", "Cancelled"]]},
			pluck="name",
		)
		for shipment_name in shipment_names:
			shipment = frappe.get_doc("Shipment Task", shipment_name)
			rows = shipment.get("shipment_items") or []
			ship_items = [
				{
					"item_code": row.item_code,
					"qty": flt(row.packed_qty),
					"uom": row.get("uom"),
					"warehouse": row.get("source_bin") or row.get("source_warehouse"),
				}
				for row in rows
				if flt(row.packed_qty) > 0
			]
			delivery_note = _create_delivery_note(
				customer=shipment.customer,
				items=ship_items,
				sales_order=shipment.get("sales_order"),
			)
			for row in rows:
				row.shipped_qty = flt(row.packed_qty)
				row.status = "Shipped"
			shipment.total_shipped_qty = sum(flt(row.shipped_qty) for row in rows)
			shipment.status = "Shipped"
			shipment.current_status = f"Auto-shipped (bypass mode) - Delivery Note {delivery_note.name}"
			shipment.shipped_by = frappe.session.user
			shipment.shipped_at = now_datetime()
			shipment.save(ignore_permissions=True)
			_publish_task_update(shipment)


@frappe.whitelist()
def complete_pick(task_name: str, skip_downstream: bool = False) -> dict:
	"""Complete a Pick Task after all quantities are persisted.

	`skip_downstream` is for sites still running Pack/Ship by hand outside SoyPaq
	(per BUSINESS_CONTEXT.md, the current client is picking-only today). It still pushes the order
	through real, auto-completed Pack Task / Shipment Task / Delivery Note records
	(see `_auto_complete_downstream`) instead of stopping the chain - the actual
	stock-out happens here, at the Delivery Note, exactly as it would through the
	manual Pack/Ship screens.

	The WMS UI posts this as a query-string value, so it arrives here as the literal
	string "0" (found 2026-09-13: `bool = False` in the signature does not save you -
	`if "0":` is truthy in Python, so "Send to Pack" was silently taking the bypass
	branch every time). cint() is the fix - it parses "0"/"1"/"true"/"false" correctly.
	"""
	skip_downstream = cint(skip_downstream)
	doc = _writable_task("Pick Task", task_name)
	_update_pick_totals(doc)
	if flt(doc.total_picked_qty) < flt(doc.total_required_qty):
		frappe.throw(
			f"Pick is incomplete: {doc.total_picked_qty:g} of {doc.total_required_qty:g} units picked."
		)
	doc.status = "Completed"
	doc.current_status = (
		"Pick completed - packing/shipping handled outside SoyPaq"
		if skip_downstream
		else "Pick completed and released to packing"
	)
	doc.completed_by = frappe.session.user
	doc.completed_at = now_datetime()
	doc.save()
	_log_pick_action(doc, "Completed", quantity=doc.total_picked_qty)
	bill_completed_pick(doc)
	if skip_downstream:
		_auto_complete_downstream(doc)
	else:
		_sync_pack_from_pick(doc)
	_publish_task_update(doc)
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def create_pack_task(
	customer: str = None, package_type: str = "Carton Box", tracking_number: str = None, items=None
) -> dict:
	"""Create a real, standalone Pack Task for testing when no linked Pick Task exists yet.

	The record is a genuine Pack Task row, pre-seeded as already picked so it works
	immediately with pack_item / pack_all / confirm_pack_box / complete_pack.
	"""
	rows = _parse_manual_items(items)
	warehouse = _default_warehouse("Storage")

	doc = frappe.new_doc("Pack Task")
	doc.naming_series = "PACK-MIA-.#####"
	doc.status = "Pending"
	doc.customer = _resolve_customer(customer)
	doc.assigned_to = package_type or "Carton Box"
	doc.pack_state = "Waiting for Item"
	doc.tracking_number = tracking_number or f"CARTON-{frappe.generate_hash(length=6).upper()}"
	doc.scan_item_barcode = rows[0]["item_code"]
	doc.current_status = f"Manually created with {len(rows)} line(s), no linked Pick Task"
	for row in rows:
		doc.append(
			"pick_items",
			{
				"item_code": row["item_code"],
				"item_name": row["item_name"],
				"uom": row["uom"],
				"required_qty": row["quantity"],
				"picked_qty": row["quantity"],
				"packed_qty": 0,
				"source_warehouse": warehouse,
				"source_bin": warehouse,
				"status": "Pending",
			},
		)
	_update_pack_totals(doc)
	doc.insert()
	_publish_task_update(doc)
	return {"name": doc.name, "route": _route("Pack Task", doc.name)}


@frappe.whitelist()
def pack_item(task_name: str, item_code: str, quantity: float = 1) -> dict:
	"""Persist an item scan into the active Pack Task container."""
	doc = _writable_task("Pack Task", task_name)
	if not frappe.get_meta("Pack Task Item").has_field("packed_qty"):
		frappe.throw("Run the SoyPaq migration before packing items.")
	row = _task_row(doc, item_code)
	quantity = flt(quantity)
	if quantity <= 0:
		frappe.throw("Pack quantity must be greater than zero.")
	remaining = max(flt(row.picked_qty) - flt(row.packed_qty), 0)
	if quantity > remaining:
		frappe.throw(f"Only {remaining:g} picked units remain to pack for {row.item_code}.")

	row.packed_qty = flt(row.packed_qty) + quantity
	doc.status = "Picking"
	doc.scan_item_barcode = item_code
	doc.last_scanned_row = row.name
	doc.last_scan_action = f"Packed {quantity:g} x {row.item_code}"
	_update_pack_totals(doc)
	doc.save()
	_publish_task_update(doc)
	return {"name": doc.name, "item_code": row.item_code, "packed_qty": row.packed_qty}


@frappe.whitelist()
def unpack_item(task_name: str, item_code: str, quantity: float = 1) -> dict:
	"""Reduce a packed quantity on a Pack Task row (correcting a mis-verified line)."""
	doc = _writable_task("Pack Task", task_name)
	row = _task_row(doc, item_code)
	quantity = flt(quantity)
	if quantity <= 0:
		frappe.throw("Pack quantity must be greater than zero.")
	if flt(row.packed_qty) <= 0:
		frappe.throw(f"No packed quantity remains to remove for {row.item_code}.")
	row.packed_qty = max(flt(row.packed_qty) - quantity, 0)
	doc.status = "Picking"
	doc.scan_item_barcode = item_code
	doc.last_scanned_row = row.name
	doc.last_scan_action = f"Removed {quantity:g} x {row.item_code} from the box"
	_update_pack_totals(doc)
	doc.save()
	_publish_task_update(doc)
	return {"name": doc.name, "item_code": row.item_code, "packed_qty": row.packed_qty}


@frappe.whitelist()
def pack_all(task_name: str) -> dict:
	"""Demo helper that persists every currently picked unit into the container."""
	doc = _writable_task("Pack Task", task_name)
	if not frappe.get_meta("Pack Task Item").has_field("packed_qty"):
		frappe.throw("Run the SoyPaq migration before packing items.")
	for row in doc.get("pick_items") or []:
		row.packed_qty = flt(row.picked_qty)
	doc.status = "Picking"
	doc.last_scan_action = "Packed all picked task quantities"
	_update_pack_totals(doc)
	doc.save()
	_publish_task_update(doc)
	return {"name": doc.name, "packed_qty": doc.total_packed_qty}


@frappe.whitelist()
def confirm_pack_box(task_name: str) -> dict:
	"""Seal the active Pack Task container after all required units are packed."""
	doc = _writable_task("Pack Task", task_name)
	_update_pack_totals(doc)
	if flt(doc.total_packed_qty) < flt(doc.total_required_qty):
		frappe.throw(
			f"Box is incomplete: {doc.total_packed_qty:g} of {doc.total_required_qty:g} units packed."
		)
	doc.box_confirmed = 1
	doc.current_status = f"Container {doc.get('tracking_number') or doc.name} confirmed"
	doc.save()
	_publish_task_update(doc)
	return {"name": doc.name, "box_confirmed": True}


@frappe.whitelist()
def complete_pack(task_name: str) -> dict:
	"""Seal the container and release the linked Shipment Task in one step.

	Confirming the box *is* completing the pack - an operator has nothing left to
	decide between those two states, so they are a single action.
	"""
	doc = _writable_task("Pack Task", task_name)
	_update_pack_totals(doc)
	if flt(doc.total_packed_qty) < flt(doc.total_required_qty):
		frappe.throw(
			f"Box is incomplete: {doc.total_packed_qty:g} of {doc.total_required_qty:g} units packed."
		)
	doc.box_confirmed = 1
	doc.status = "Completed"
	doc.current_status = "Packing completed and released to shipping"
	doc.completed_by = frappe.session.user
	doc.completed_at = now_datetime()
	doc.save()

	shipment_names = frappe.get_all("Shipment Task", filters={"warehouse": doc.name}, pluck="name")
	if not shipment_names:
		_create_shipment_task_from_pack(doc)
	for name in shipment_names:
		shipment = frappe.get_doc("Shipment Task", name)
		if shipment.status not in ("Shipped", "Cancelled"):
			shipment.status = "Ready to Ship"
			shipment.save(ignore_permissions=True)
			_publish_task_update(shipment)
	_publish_task_update(doc)
	return {"name": doc.name, "status": doc.status}


def _create_shipment_task_from_pack(pack_task) -> None:
	"""Give a completed Pack Task its Shipment Task - complete_pack() previously only
	ever updated a Shipment Task that already existed, same gap as Pick -> Pack."""
	rows = [row for row in pack_task.get("pick_items") or [] if flt(row.packed_qty) > 0]
	if not rows:
		return
	doc = frappe.new_doc("Shipment Task")
	doc.naming_series = "SHIP-MIA-.#####"
	doc.status = "Ready to Ship"
	doc.customer = pack_task.get("customer")
	doc.sales_order = pack_task.get("sales_order")
	doc.warehouse = pack_task.name
	doc.carrier = "UPS"
	for row in rows:
		doc.append(
			"shipment_items",
			{
				"item_code": row.item_code,
				"item_name": row.item_name,
				"uom": row.get("uom"),
				"required_qty": row.packed_qty,
				"packed_qty": row.packed_qty,
				"shipped_qty": 0,
				"source_warehouse": row.get("source_warehouse"),
				"source_bin": row.get("source_bin"),
				"status": "Ready",
			},
		)
	doc.total_items = len(rows)
	doc.total_required_qty = sum(flt(row.packed_qty) for row in rows)
	doc.total_packed_qty = doc.total_required_qty
	doc.total_shipped_qty = 0
	doc.insert(ignore_permissions=True)
	_publish_task_update(doc)


@frappe.whitelist()
def create_shipment_task(
	customer: str = None, carrier: str = "UPS", tracking_number: str = None, items=None
) -> dict:
	"""Create a real, standalone Shipment Task for testing when no linked Pack Task exists yet.

	Pre-seeded as already packed so it works immediately with generate_shipment_label
	and mark_shipment_shipped. tracking_number is left blank unless passed explicitly, so
	generate_shipment_label still buys a real label instead of skipping it.
	"""
	rows = _parse_manual_items(items)
	warehouse = _default_warehouse("Storage")

	doc = frappe.new_doc("Shipment Task")
	doc.naming_series = "SHIP-MIA-.#####"
	doc.status = "Ready to Ship"
	doc.customer = _resolve_customer(customer)
	doc.carrier = carrier or "UPS"
	doc.tracking_number = tracking_number or ""
	for row in rows:
		doc.append(
			"shipment_items",
			{
				"item_code": row["item_code"],
				"item_name": row["item_name"],
				"uom": row["uom"],
				"required_qty": row["quantity"],
				"packed_qty": row["quantity"],
				"shipped_qty": 0,
				"source_warehouse": warehouse,
				"source_bin": warehouse,
				"status": "Ready",
			},
		)
	doc.total_items = len(rows)
	doc.total_required_qty = sum(row["quantity"] for row in rows)
	doc.total_packed_qty = doc.total_required_qty
	doc.total_shipped_qty = 0
	doc.insert()
	_publish_task_update(doc)
	return {"name": doc.name, "route": _route("Shipment Task", doc.name)}


def _writable_shipment(task_name: str):
	if not task_name or not frappe.db.exists("Shipment Task", task_name):
		frappe.throw(f"Shipment Task {task_name or ''} was not found.")
	doc = frappe.get_doc("Shipment Task", task_name)
	if not doc.has_permission("write"):
		frappe.throw(
			f"You do not have permission to update Shipment Task {task_name}.", frappe.PermissionError
		)
	if doc.get("status") in ("Shipped", "Cancelled"):
		frappe.throw(f"Shipment Task {task_name} is already {doc.get('status')}.")
	return doc


_SHIP_TO_KEYS = ("name", "company", "line_1", "line_2", "city", "state", "postal_code", "country", "phone", "email")
_PARCEL_KEYS = ("weight_kg", "length_cm", "width_cm", "height_cm")


def _medusa_ship_to(shipment_task) -> dict:
	"""Ship-to the order carried in from Medusa (empty when the source sent none)."""
	pick = _origin_pick(shipment_task)
	raw = pick.get("medusa_shipping_address") if pick else None
	if not raw:
		return {}
	try:
		address = json.loads(raw)
	except ValueError:
		return {}
	name = " ".join(part for part in (address.get("first_name"), address.get("last_name")) if part)
	return {
		"name": name or address.get("name") or "",
		"company": address.get("company") or "",
		"line_1": address.get("address_1") or address.get("line_1") or "",
		"line_2": address.get("address_2") or address.get("line_2") or "",
		"city": address.get("city") or "",
		"state": address.get("province") or address.get("state") or "",
		"postal_code": address.get("postal_code") or "",
		"country": (address.get("country_code") or address.get("country") or "").upper(),
		"phone": address.get("phone") or "",
		"email": address.get("email") or "",
	}


def _saved_ship_to(shipment_task) -> dict:
	return {key: shipment_task.get(f"ship_to_{key}") or "" for key in _SHIP_TO_KEYS}


def _ship_form(shipment_task) -> dict:
	"""What the Ship screen shows: saved entry first, else the order's address, else blank."""
	saved = _saved_ship_to(shipment_task)
	from_order = _medusa_ship_to(shipment_task)
	source = "saved" if any(saved.values()) else ("order" if any(from_order.values()) else "")
	return {
		"ship_to": saved if source == "saved" else (from_order or saved),
		"ship_to_source": source,
		"parcel": {key: shipment_task.get(f"parcel_{key}") or 0 for key in _PARCEL_KEYS},
	}


def _parse_form(value) -> dict:
	if not value:
		return {}
	return value if isinstance(value, dict) else json.loads(value)


def _validated_label_inputs(ship_to: dict, parcel: dict) -> tuple[dict, dict]:
	"""A real carrier needs a deliverable address and a weighed, measured box."""
	ship_to = {key: str(ship_to.get(key) or "").strip() for key in _SHIP_TO_KEYS}
	ship_to["country"] = ship_to["country"].upper()
	missing = [
		label
		for key, label in (
			("name", "recipient name"),
			("line_1", "address line 1"),
			("city", "city"),
			("postal_code", "postal code"),
			("country", "country"),
		)
		if not ship_to[key]
	]
	if missing:
		frappe.throw(f"Enter the {', '.join(missing)} before generating a label.")
	if len(ship_to["country"]) != 2 or not ship_to["country"].isalpha():
		frappe.throw("Country must be a 2-letter code, for example US.")
	if not (ship_to["phone"] or ship_to["email"]):
		frappe.throw("Enter a phone number or email for the recipient.")
	parcel = {key: flt(parcel.get(key)) for key in _PARCEL_KEYS}
	if any(parcel[key] <= 0 for key in _PARCEL_KEYS):
		frappe.throw("Enter the parcel weight and length, width and height - all above zero.")
	return ship_to, parcel


@frappe.whitelist()
def generate_shipment_label(task_name: str, ship_to=None, parcel=None) -> dict:
	"""Reserve a tracking number/label via the site's configured shipping provider
	(site config `shipping_provider`: "manual" by default - no external call, no cost;
	"shippo" or "easyship" buy a real label). See shipping_providers.py - adding another
	carrier is a new ShippingProvider subclass there, this call site doesn't change.

	`ship_to` / `parcel` (dict or JSON) are what the worker confirmed on the Ship screen; they are
	saved on the task first, so a failed purchase keeps the entry. A real carrier refuses to
	buy without a complete address and parcel; the manual provider takes them if given.
	"""
	from soypaq import shipping_providers

	doc = _writable_shipment(task_name)
	if not doc.get("tracking_number"):
		provider = shipping_providers.get_provider()
		ship_to_form, parcel_form = _parse_form(ship_to), _parse_form(parcel)
		if ship_to_form or parcel_form:
			for key in _SHIP_TO_KEYS:
				doc.set(f"ship_to_{key}", str(ship_to_form.get(key) or "").strip())
			for key in _PARCEL_KEYS:
				doc.set(f"parcel_{key}", flt(parcel_form.get(key)))
			doc.save()
			# A refused purchase throws and rolls the request back; commit so the typed entry survives.
			frappe.db.commit()
		if provider.name == "manual":
			label = provider.buy_label()
		else:
			saved_ship_to, saved_parcel = _validated_label_inputs(
				_saved_ship_to(doc), {key: doc.get(f"parcel_{key}") for key in _PARCEL_KEYS}
			)
			saved_parcel["items"] = [
				{"description": row.get("item_name") or row.item_code, "quantity": flt(row.packed_qty) or 1}
				for row in doc.get("shipment_items") or []
			]
			label = provider.buy_label(ship_to=saved_ship_to, parcel=saved_parcel)
		doc.tracking_number = label["tracking_number"]
		doc.carrier = label["carrier"]
		doc.shipping_label_url = label["label_url"]
		doc.shippo_transaction_id = label["transaction_id"]
		doc.save()
	_publish_task_update(doc)
	return {"name": doc.name, "tracking_number": doc.tracking_number, "label_url": doc.shipping_label_url}


@frappe.whitelist()
def mark_shipment_shipped(task_name: str) -> dict:
	"""Mark a Shipment Task as shipped: post the real Delivery Note (the actual stock-out),
	then close out the task's item totals.
	"""
	doc = _writable_shipment(task_name)
	if not doc.get("tracking_number"):
		frappe.throw("Generate a shipping label before marking this shipment shipped.")

	rows = doc.get("shipment_items") or []
	ship_items = [
		{
			"item_code": row.item_code,
			"qty": flt(row.packed_qty),
			"uom": row.get("uom"),
			"warehouse": row.get("source_bin") or row.get("source_warehouse"),
		}
		for row in rows
		if flt(row.packed_qty) > 0
	]
	delivery_note = _create_delivery_note(
		customer=doc.customer,
		items=ship_items,
		sales_order=doc.get("sales_order"),
	)

	for row in rows:
		row.shipped_qty = flt(row.packed_qty)
		row.status = "Shipped"
	doc.total_shipped_qty = sum(flt(row.shipped_qty) for row in rows)
	doc.status = "Shipped"
	doc.shipped_by = frappe.session.user
	doc.shipped_at = now_datetime()
	doc.save()
	_publish_task_update(doc)
	return {"name": doc.name, "status": doc.status, "delivery_note": delivery_note.name}


def _check_medusa_secret() -> None:
	"""Auth for the Medusa->ERPNext direction: a shared secret header, not a Frappe
	user session - the caller is the Medusa backend, not a logged-in operator.
	Mirrors medusa_client._shared_secret() on the outbound side.
	"""
	expected = frappe.conf.get("medusa_erp_shared_secret")
	if not expected:
		frappe.throw("medusa_erp_shared_secret is not configured on this site.")
	got = frappe.get_request_header("X-ERP-Secret")
	if not got or got != expected:
		frappe.throw("Invalid or missing shared secret.", frappe.PermissionError)


def _bridge_user() -> str:
	"""The machine user Medusa orders run as - never Administrator. Its roles and its
	Customer/Company User Permissions are the tenant boundary (MULTI_TENANT_SECURITY.md)."""
	user = frappe.conf.get("medusa_bridge_user") or "svc-medusa-bridge@soy-ops.com"
	if not frappe.db.get_value("User", {"name": user, "enabled": 1}):
		frappe.throw(f"Medusa bridge user {user} does not exist or is disabled.")
	return user


def _medusa_tenants() -> list[str]:
	"""The Customers the bridge user may act for: its Customer User Permissions, nothing else.
	The permission list is the tenant boundary, so an order can only ever land on one of these."""
	user = _bridge_user()
	customers = frappe.get_all(
		"User Permission", filters={"user": user, "allow": "Customer"}, pluck="for_value", order_by="creation"
	)
	if not customers:
		frappe.throw(f"{user} needs at least one Customer User Permission to act as a Medusa tenant.")
	return customers


def _medusa_tenant() -> str:
	"""The bridge's tenant when it serves exactly one; several means the caller must route by SKU."""
	customers = _medusa_tenants()
	if len(customers) != 1:
		frappe.throw(f"{_bridge_user()} serves {len(customers)} tenants; route the order by its SKUs instead.")
	return customers[0]


def _sku_tenant(item_code: str, tenants: list[str]) -> str | None:
	"""Which permitted tenant owns an item: the tenant group in its item group's ancestry (Acme > Acme - Tees)."""
	group = frappe.db.get_value("Item", item_code, "item_group")
	while group and group != "All Item Groups":
		if group in tenants:
			return group
		group = frappe.db.get_value("Item Group", group, "parent_item_group")
	return tenants[0] if len(tenants) == 1 else None


def _order_tenant(skus: list[str]) -> str:
	"""One tenant per order. A SKU nobody permitted owns, or a cart that mixes tenants, is rejected."""
	tenants = _medusa_tenants()
	owners = {sku: _sku_tenant(sku, tenants) for sku in skus}
	missing = [sku for sku, owner in owners.items() if not owner]
	if missing:
		frappe.throw(f"SKU {', '.join(missing)} does not belong to a tenant this Medusa bridge serves.")
	distinct = sorted(set(owners.values()))
	if len(distinct) > 1:
		frappe.throw(f"Order mixes tenants ({', '.join(distinct)}); each tenant's items must be a separate order.")
	return distinct[0]


def _log_medusa_intake(
	order_id, outcome, reason=None, pick_task=None, customer=None, payload=None, order_number=None
):
	frappe.get_doc(
		{
			"doctype": "Medusa Intake Log",
			"medusa_order_id": order_id,
			"medusa_order_number": order_number,
			"outcome": outcome,
			"reason": reason,
			"pick_task": pick_task,
			"customer": customer,
			"acting_user": frappe.session.user,
			"payload": payload,
		}
	).insert(ignore_permissions=True)


@frappe.whitelist()
def sync_stock_to_medusa() -> dict:
	"""Push ERPNext's current available stock (per Flow B - ERPNext is the source of
	truth, Medusa only ever receives a mirror) to Medusa, keyed by Item Code == Medusa
	variant SKU (Phase 1 rule: exact 1:1 match, no fuzzy matching).

	Scoped to the Medusa tenant's own warehouses (Company == tenant Customer, the 3PL
	convention in AGENT.md) - Medusa is shared, so another client's Bins must never be
	mirrored into it.

	Prototype trigger: call this manually (Settings screen or bench) rather than on a
	schedule or a Stock Ledger Entry hook - both are real Phase-2 work, not needed to
	prove the loop end to end.
	"""
	tenants = _medusa_tenants()
	tenant = ", ".join(tenants)
	tenant_warehouses = frappe.get_all("Warehouse", filters={"company": ["in", tenants]}, pluck="name")
	if not tenant_warehouses:
		frappe.throw(f"No warehouses belong to company {tenant}; nothing to mirror.")
	bins = frappe.get_all(
		"Bin",
		fields=["item_code", "warehouse", "actual_qty", "reserved_qty"],
		filters={"actual_qty": [">", 0], "warehouse": ["in", tenant_warehouses]},
	)
	excluded_warehouses = set(
		frappe.get_all(
			"Warehouse",
			filters={"warehouse_name": ["like", "%Damaged%"]},
			pluck="name",
		)
		+ frappe.get_all(
			"Warehouse",
			filters={"warehouse_name": ["like", "%Returns%"]},
			pluck="name",
		)
	)
	available_by_item: dict[str, float] = {}
	for row in bins:
		if row.warehouse in excluded_warehouses:
			continue
		available = flt(row.actual_qty) - flt(row.reserved_qty)
		available_by_item[row.item_code] = available_by_item.get(row.item_code, 0) + available

	levels = [{"sku": item_code, "quantity": max(qty, 0)} for item_code, qty in available_by_item.items()]
	result = medusa_client.push_stock_levels(levels)
	return {"tenant": tenant, "pushed": len(levels), "medusa_response": result}


def _best_pick_bin(item_code: str, quantity: float, storage_zone: str | None) -> str | None:
	"""The Storage-zone bin with the most available stock (on hand minus open picks) that covers `quantity`."""
	if not storage_zone:
		return None
	best, best_available = None, 0.0
	for row in frappe.get_all(
		"Bin",
		filters={"item_code": item_code, "actual_qty": [">", 0]},
		fields=["warehouse", "actual_qty"],
	):
		if frappe.db.get_value("Warehouse", row.warehouse, "parent_warehouse") != storage_zone:
			continue
		available = flt(row.actual_qty) - _open_pick_reserved_qty(item_code, row.warehouse)
		if available >= flt(quantity) and available > best_available:
			best, best_available = row.warehouse, available
	return best


def _clean_shipping_address(value) -> str | None:
	"""Keep the order's shipping address as JSON on the Pick Task so the Ship screen can prefill it.
	Optional: a payload without one just means the worker types it in at label time."""
	if not value:
		return None
	try:
		address = json.loads(value) if isinstance(value, str) else value
	except ValueError:
		return None
	return json.dumps(address, default=str) if isinstance(address, dict) and address else None


@frappe.whitelist(allow_guest=True)
def create_order_from_medusa(
	order_id: str = None,
	customer_name: str = None,
	items=None,
	display_id: str = None,
	shipping_address=None,
) -> dict:
	"""Turn a Medusa order.placed payload into a real Pick Task (Flow A).

	Prototype scope, deliberately smaller than the full spec in MEDUSA_INTEGRATION.md:
	- No Sales Order in between yet - creates the Pick Task directly via create_pick_task,
	  same as the existing manual-testing path. The spec's idempotent-Sales-Order step is
	  real Phase-1 work, not required to prove Medusa->WMS->Pack->Ship end to end.
	- Single-bin only, same limit create_pick_task already has.
	items: [{sku, quantity}] - sku must equal an ERPNext Item Code exactly (Phase 1 rule:
	hard-fail on a miss, no fuzzy matching, no auto-creating items).

	Auth is the shared secret; after it passes the call runs as the scoped bridge user
	(not Administrator), so roles and Customer/Company User Permissions apply. The
	customer is always the bridge user's tenant - `customer_name` from the payload is
	ignored, since a webhook must not choose which tenant it writes to. Every attempt
	after the secret check lands in Medusa Intake Log, which also makes replays
	idempotent: an order id already Created returns its existing Pick Task.
	"""
	_check_medusa_secret()
	frappe.set_user(_bridge_user())
	order_id = (order_id or "").strip()
	order_number = str(display_id or "").strip() or None
	payload = items if isinstance(items, str) else json.dumps(items, default=str)
	customer = None
	try:
		if not order_id:
			frappe.throw("Medusa order id is required.")
		existing = frappe.db.get_value(
			"Medusa Intake Log", {"medusa_order_id": order_id, "outcome": "Created"}, "pick_task"
		)
		if existing:
			_log_medusa_intake(
				order_id,
				"Duplicate",
				"Replay of an already-created order.",
				existing,
				frappe.db.get_value("Pick Task", existing, "customer"),
				payload,
				order_number,
			)
			return {"name": existing, "route": _route("Pick Task", existing), "duplicate": True}

		parsed_items = json.loads(items) if isinstance(items, str) else items
		if not parsed_items:
			frappe.throw("Medusa order had no items.")
		parsed = []
		for line in parsed_items:
			sku = (line.get("sku") or "").strip()
			qty = flt(line.get("quantity"))
			if not sku:
				frappe.throw(f"Medusa order {order_id} sent a line with no SKU.")
			if not frappe.db.exists("Item", sku):
				frappe.throw(
					f"Medusa SKU '{sku}' has no matching ERPNext Item Code (order {order_id}). "
					"Phase 1 requires an exact 1:1 match - fix the SKU on the Medusa variant, "
					"do not auto-create the item."
				)
			if qty <= 0:
				frappe.throw(f"Medusa SKU '{sku}' had a non-positive quantity.")
			parsed.append({"item_code": sku, "quantity": qty})

		# Each line comes from the bin that actually holds it (most available first), not one fixed
		# bin: a task can span bins, and stock sits wherever it was put away.
		customer = _order_tenant([line["item_code"] for line in parsed])
		storage_zone = _storage_group(customer)
		for line in parsed:
			line["warehouse"] = _best_pick_bin(line["item_code"], line["quantity"], storage_zone) or _zone_warehouse(
				"Storage", company=customer
			)
		result = create_pick_task(customer=customer, items=json.dumps(parsed))
		frappe.db.set_value(
			"Pick Task",
			result["name"],
			{
				"medusa_order_id": order_id,
				"medusa_order_number": order_number,
				"medusa_shipping_address": _clean_shipping_address(shipping_address),
			},
			update_modified=False,
		)
		_log_medusa_intake(order_id, "Created", None, result["name"], customer, payload, order_number)
		frappe.logger("soypaq.medusa").info(f"Created {result['name']} from Medusa order {order_id}")
		return result
	except Exception as exc:
		# A throw rolls the request back, which would erase the audit row too - undo the
		# partial work first, then commit only the log entry.
		frappe.db.rollback()
		_log_medusa_intake(
			order_id or None, "Rejected", str(exc)[:1000], None, customer, payload, order_number
		)
		frappe.db.commit()
		raise


@frappe.whitelist()
def get_inventory() -> dict:
	"""Return a fresh ERPNext stock and warehouse snapshot for the WMS."""
	return _inventory_snapshot()


@frappe.whitelist()
def adjust_bin_qty(
	item_code: str, warehouse: str, quantity_delta: float, reason_code: str, notes: str = ""
) -> dict:
	"""Correct a bin's quantity via Stock Reconciliation.

	`quantity_delta` is the adjustment: positive to add stock, negative to remove.
	Posts a real Stock Reconciliation and creates an Inventory Action record linking to it.
	"""
	item_code = (item_code or "").strip()
	warehouse = (warehouse or "").strip()
	if not item_code or not warehouse:
		frappe.throw("Item code and warehouse are required.")

	if not frappe.db.exists("Item", item_code):
		frappe.throw(f"Item {item_code} was not found in ERPNext.")
	if frappe.db.get_value("Item", item_code, "disabled"):
		frappe.throw(f"Item {item_code} is disabled.")

	if not frappe.db.exists("Warehouse", warehouse):
		frappe.throw(f"Warehouse {warehouse} was not found in ERPNext.")
	if frappe.db.get_value("Warehouse", warehouse, ["is_group", "disabled"], as_dict=True) in [
		{"is_group": 1, "disabled": 0},
		{"is_group": 0, "disabled": 1},
		{"is_group": 1, "disabled": 1},
	]:
		frappe.throw(f"Warehouse {warehouse} is a zone or is disabled - choose a leaf bin.")

	quantity_delta = flt(quantity_delta)
	if quantity_delta == 0:
		frappe.throw("Quantity adjustment cannot be zero.")

	company = _warehouse_company(warehouse)
	if not company:
		frappe.throw(f"Could not determine company for warehouse {warehouse}.")

	# Get current bin state
	current_qty = flt(
		frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty") or 0
	)
	new_qty = max(current_qty + quantity_delta, 0)

	# Carry the bin's existing valuation forward; fall back to the item's own rate.
	# A1-style bins can legitimately sit at 0.0, and a bin that has never held stock
	# has no Bin row at all - in both cases ERPNext cannot infer a rate on its own.
	valuation_rate = flt(
		frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "valuation_rate")
		or frappe.db.get_value("Item", item_code, "valuation_rate")
		or 0
	)

	# Create Stock Reconciliation. `purpose`, `posting_date` and `posting_time` are all
	# mandatory - note there is no `reconciliation_date` field on this doctype.
	recon = frappe.new_doc("Stock Reconciliation")
	recon.company = company
	recon.purpose = "Stock Reconciliation"
	recon.set_posting_time = 1
	recon.posting_date = frappe.utils.today()
	recon.posting_time = frappe.utils.nowtime()
	recon.append(
		"items",
		{
			"item_code": item_code,
			"warehouse": warehouse,
			"qty": new_qty,
			"valuation_rate": valuation_rate,
			"allow_zero_valuation_rate": 1 if not valuation_rate else 0,
		},
	)
	recon.insert()
	recon.submit()

	# Create Inventory Action annotation
	action = frappe.new_doc("Inventory Action")
	action.item_code = item_code
	action.warehouse = warehouse
	action.action_type = "Adjust Quantity"
	action.reason_code = reason_code
	action.quantity_delta = quantity_delta
	action.notes = notes
	action.source_document_type = "Stock Reconciliation"
	action.source_document_name = recon.name
	action.created_by_user = frappe.session.user
	action.insert()

	return {
		"name": recon.name,
		"item_code": item_code,
		"warehouse": warehouse,
		"previous_qty": current_qty,
		"new_qty": new_qty,
		"quantity_delta": quantity_delta,
		"action_id": action.name,
	}


def _storage_group(company: str) -> str | None:
	"""The tenant's Storage zone (group warehouse) that new bins hang under."""
	return frappe.db.get_value(
		"Warehouse",
		{"company": company, "is_group": 1, "warehouse_name": ["like", "% - Storage"]},
		"name",
	)


def _next_bin_code(parent: str) -> str:
	"""Next default code under a Storage zone: keeps the highest existing letter, counts up, zero-padded (A06 -> A07)."""
	best = ("A", 0)
	for name in frappe.get_all("Warehouse", filters={"parent_warehouse": parent, "is_group": 0}, pluck="warehouse_name"):
		match = re.search(r"- ([A-Za-z]+)(\d+)$", name or "")
		if match and (match.group(1).upper(), int(match.group(2))) > best:
			best = (match.group(1).upper(), int(match.group(2)))
	return f"{best[0]}{best[1] + 1:02d}"


def _onboarded_customers() -> list[str]:
	"""Customers set up to hold stock: they have a Company and a Storage zone."""
	customers = []
	for name in frappe.get_all("Customer", filters={"disabled": 0}, pluck="name", order_by="name"):
		# 3PL convention (AGENT.md): a tenant's Customer and Company share a name.
		if frappe.db.exists("Company", name) and _storage_group(name):
			customers.append(name)
	return customers


CLIENT_CREATE_ROLES = {"Stock Manager", "System Manager"}


def _can_create_client() -> bool:
	return frappe.session.user == "Administrator" or bool(CLIENT_CREATE_ROLES & set(frappe.get_roles()))


@frappe.whitelist()
def receive_client_options() -> dict:
	"""Clients the Start receiving popup can offer, and whether this user may add a new one."""
	return {"customers": _onboarded_customers(), "can_create": _can_create_client()}


@frappe.whitelist()
def client_bins(customer: str | None = None, item_codes=None, near_warehouse: str | None = None) -> dict:
	"""A client's bins for a picker: every leaf bin under its Storage zone, with what is on hand.

	`item_codes` (JSON list) adds `held` per bin - quantity of those items already there - so a picker can
	show where an item already lives first. `near_warehouse` finds the client from a bin when the caller
	has a bin but not a client name.
	"""
	customer = (customer or "").strip()
	if not customer and near_warehouse:
		customer = _warehouse_company(near_warehouse) or ""
	zone = _storage_group(customer) if customer and frappe.db.exists("Company", customer) else None
	if not zone:
		return {"customer": customer, "bins": []}
	codes = json.loads(item_codes) if isinstance(item_codes, str) and item_codes else (item_codes or [])
	warehouses = frappe.get_all(
		"Warehouse",
		filters={"parent_warehouse": zone, "is_group": 0, "disabled": 0},
		pluck="name",
		order_by="name asc",
	)
	stock = {}
	if warehouses:
		for row in frappe.get_all(
			"Bin", filters={"warehouse": ["in", warehouses]}, fields=["warehouse", "item_code", "actual_qty"], limit_page_length=0
		):
			entry = stock.setdefault(row.warehouse, {"on_hand": 0, "held": {}})
			entry["on_hand"] += flt(row.actual_qty)
			if row.item_code in codes and flt(row.actual_qty) > 0:
				entry["held"][row.item_code] = flt(row.actual_qty)
	bins = []
	for name in warehouses:
		code = re.sub(r" - [A-Za-z0-9]+$", "", re.sub(r"^.* - Storage - ", "", name))
		entry = stock.get(name, {"on_hand": 0, "held": {}})
		bins.append({"warehouse": name, "code": code, "on_hand": entry["on_hand"], "held": entry["held"]})
	return {"customer": customer, "bins": bins}


@frappe.whitelist()
def create_client(customer_name: str) -> dict:
	"""Create a 3PL Client from the floor. Saving the Customer starts the usual background tenant
	onboarding (Company, warehouses, first bin, item group, item prefix); poll client_setup_status.
	Limited to Stock Manager and System Manager - it creates a Company and a warehouse tree."""
	if not _can_create_client():
		frappe.throw("Only a Stock Manager can add a new client.", frappe.PermissionError)
	customer_name = re.sub(r"\s+", " ", customer_name or "").strip()
	if len(customer_name) < 2:
		frappe.throw("Enter the client's name.")
	if frappe.db.exists("Customer", {"customer_name": customer_name}) or frappe.db.exists("Customer", customer_name):
		frappe.throw(f"A client named {customer_name} already exists.")
	if frappe.db.exists("Company", customer_name):
		frappe.throw(f"A company named {customer_name} already exists.")
	doc = frappe.new_doc("Customer")
	doc.customer_name = customer_name
	doc.customer_type = "Company"
	doc.customer_group = "3PL Client"
	doc.territory = frappe.db.get_single_value("Selling Settings", "territory") or "All Territories"
	doc.insert(ignore_permissions=True)
	return {"name": doc.name, "ready": False}


@frappe.whitelist()
def client_setup_status(customer: str) -> dict:
	"""Has the background onboarding finished, so the client can receive stock?"""
	return {"name": customer, "ready": customer in _onboarded_customers()}


@frappe.whitelist()
def new_bin_options(customer: str | None = None) -> dict:
	"""Customers that can own a bin, plus the default next code for the chosen one."""
	customers = _onboarded_customers()
	customer = customer if customer in customers else (customers[0] if customers else None)
	return {
		"customers": customers,
		"customer": customer,
		"code": _next_bin_code(_storage_group(customer)) if customer else "",
	}


@frappe.whitelist()
def create_bin(customer: str, code: str | None = None) -> dict:
	"""Create a storage bin (leaf Warehouse) for a customer under their Storage zone.

	Name follows the existing schema `<Customer> - Storage - <code> - <abbr>`; when no code is given
	the next free one is used (A07 after A06). Refuses a code that already exists for the tenant.
	"""
	customer = (customer or "").strip()
	if not customer or not frappe.db.exists("Customer", customer):
		frappe.throw("Choose the customer this bin belongs to.")
	parent = frappe.db.exists("Company", customer) and _storage_group(customer)
	if not parent:
		frappe.throw(f"{customer} has no Storage zone to add a bin to.")
	code = re.sub(r"\s+", "", code or "").upper() or _next_bin_code(parent)
	if not re.fullmatch(r"[A-Z]+\d{1,3}", code):
		frappe.throw("A bin code is a letter and a number, like A07.")
	code = re.sub(r"^([A-Z]+)(\d+)$", lambda m: f"{m.group(1)}{m.group(2).zfill(2)}", code)
	zone_name = frappe.db.get_value("Warehouse", parent, "warehouse_name")
	if frappe.db.exists("Warehouse", {"warehouse_name": f"{zone_name} - {code}", "company": customer}):
		frappe.throw(f"Bin {code} already exists for {customer}.")
	doc = frappe.new_doc("Warehouse")
	doc.warehouse_name = f"{zone_name} - {code}"
	doc.company = customer
	doc.parent_warehouse = parent
	doc.is_group = 0
	doc.flags.ignore_permissions = True
	doc.insert()
	return {"name": doc.name, "code": code, "customer": customer}


@frappe.whitelist()
def move_bin_stock(
	item_code: str, from_warehouse: str, to_warehouse: str, quantity: float, reason_code: str, notes: str = ""
) -> dict:
	"""Move stock between bins via Stock Entry (Material Transfer).

	Posts a real Stock Entry and creates an Inventory Action record linking to it.
	Validates adequate stock in the source bin.
	"""
	item_code = (item_code or "").strip()
	from_warehouse = (from_warehouse or "").strip()
	to_warehouse = (to_warehouse or "").strip()
	if not item_code or not from_warehouse or not to_warehouse:
		frappe.throw("Item code and both warehouses are required.")

	if from_warehouse == to_warehouse:
		frappe.throw("Source and destination bins cannot be the same.")

	if not frappe.db.exists("Item", item_code):
		frappe.throw(f"Item {item_code} was not found in ERPNext.")
	if frappe.db.get_value("Item", item_code, "disabled"):
		frappe.throw(f"Item {item_code} is disabled.")

	# Operators scan a short bin label ("A1"), not the full internal warehouse name.
	# _resolve_bin accepts either, and already rejects group warehouses.
	from_warehouse = _resolve_bin(from_warehouse)
	to_warehouse = _resolve_bin(to_warehouse, company=frappe.db.get_value("Warehouse", from_warehouse, "company"))
	if from_warehouse == to_warehouse:
		frappe.throw("Source and destination bins cannot be the same.")
	for wh in [from_warehouse, to_warehouse]:
		if frappe.db.get_value("Warehouse", wh, "disabled"):
			frappe.throw(f"Warehouse {wh} is disabled - choose an active bin.")

	quantity = flt(quantity)
	if quantity <= 0:
		frappe.throw("Quantity must be greater than zero.")

	# Verify source has sufficient stock
	available_qty = flt(
		frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": from_warehouse}, "actual_qty") or 0
	)
	if available_qty < quantity:
		frappe.throw(
			f"Only {available_qty:g} units available in {from_warehouse}, cannot move {quantity:g} units of {item_code}."
		)

	company = _warehouse_company(from_warehouse)
	if not company:
		frappe.throw(f"Could not determine company for warehouse {from_warehouse}.")

	# Create Stock Entry (Material Transfer)
	transfer = _create_stock_entry(
		"Material Transfer",
		[
			{
				"item_code": item_code,
				"qty": quantity,
				"s_warehouse": from_warehouse,
				"t_warehouse": to_warehouse,
			}
		],
		company=company,
	)

	# Create Inventory Action annotation
	action = frappe.new_doc("Inventory Action")
	action.item_code = item_code
	action.warehouse = from_warehouse
	action.action_type = "Move Stock"
	action.reason_code = reason_code
	action.from_warehouse = from_warehouse
	action.to_warehouse = to_warehouse
	action.quantity = quantity
	action.notes = notes
	action.source_document_type = "Stock Entry"
	action.source_document_name = transfer.name
	action.created_by_user = frappe.session.user
	action.insert()

	return {
		"name": transfer.name,
		"item_code": item_code,
		"from_warehouse": from_warehouse,
		"to_warehouse": to_warehouse,
		"quantity_moved": quantity,
		"action_id": action.name,
	}


@frappe.whitelist()
def get_bin_activity(item_code: str = None, warehouse: str = None, limit: int = 100) -> list[dict]:
	"""Return activity feed for an item and/or warehouse, or site-wide if neither is given.

	Joins Stock Ledger Entries with Inventory Action records to show the complete
	audit trail with reasons. If both are given, shows per-bin activity. If only
	item_code given, shows item activity across all bins. If neither is given,
	shows the most recent activity across the whole site (Inventory -> History tab).

	Returns most recent entries first, limited to `limit` (default 100).
	"""
	item_code = (item_code or "").strip()
	warehouse = (warehouse or "").strip()

	filters = {"is_cancelled": 0}
	if item_code:
		filters["item_code"] = item_code
	if warehouse:
		filters["warehouse"] = warehouse

	# Get Stock Ledger Entries
	sle_rows = frappe.get_all(
		"Stock Ledger Entry",
		filters=filters,
		fields=[
			"name",
			"item_code",
			"warehouse",
			"actual_qty",
			"qty_after_transaction",
			"voucher_type",
			"voucher_no",
			"owner",
			"posting_date",
			"posting_time",
		],
		order_by="posting_date desc, posting_time desc",
		limit_page_length=limit,
	)

	# Build a map of Inventory Action records by source document
	actions_by_source = {}
	for action in frappe.get_all(
		"Inventory Action",
		fields=[
			"name",
			"reason_code",
			"notes",
			"source_document_type",
			"source_document_name",
			"created_by_user",
		],
	):
		key = f"{action.source_document_type}:{action.source_document_name}"
		actions_by_source[key] = action

	# A Stock Reconciliation *sets* a balance rather than moving a delta: it writes
	# actual_qty = 0 and puts the result in qty_after_transaction. So `after - actual`
	# is not the previous balance for those rows, and actual_qty is not the change.
	# Derive the previous balance from the next-older entry for the same item+bin,
	# which is correct for every voucher type. The oldest row in the window has no
	# predecessor loaded, so it falls back to the arithmetic.
	previous_balance: dict[str, float] = {}
	last_seen: dict[tuple, float] = {}
	for sle in reversed(sle_rows):  # oldest -> newest
		key = (sle.item_code, sle.warehouse)
		previous_balance[sle.name] = last_seen.get(key, flt(sle.qty_after_transaction) - flt(sle.actual_qty))
		last_seen[key] = flt(sle.qty_after_transaction)

	# Merge the data
	activity = []
	for sle in sle_rows:
		action_key = f"{sle.voucher_type}:{sle.voucher_no}"
		action = actions_by_source.get(action_key)
		prior = previous_balance[sle.name]

		activity.append(
			{
				"timestamp": f"{sle.posting_date} {sle.posting_time}",
				"item_code": sle.item_code,
				"warehouse": sle.warehouse,
				"quantity_change": flt(sle.qty_after_transaction) - prior,
				"previous_qty": prior,
				"new_qty": flt(sle.qty_after_transaction),
				"user": _user(sle.owner)["name"],
				"reason": action.reason_code if action else sle.voucher_type,
				"notes": action.notes if action else "",
				"source_type": sle.voucher_type,
				"source_name": sle.voucher_no,
				"action_id": action.name if action else None,
				"route": _route(sle.voucher_type, sle.voucher_no) if sle.voucher_no else "",
			}
		)

	return activity


@frappe.whitelist()
def scan(code: str) -> dict:
	"""Resolve a barcode or tracking number to the matching SoyPaq record."""
	code = (code or "").strip()
	if not code:
		frappe.throw("Enter a barcode, tracking number, or SKU.")

	checks = [
		("Inbound Package", {"external_tracking_number": code}),
		("Inbound ASN", {"external_tracking_number": code}),
		("Pick Task", {"scan_bin": code}),
		("Pick Task", {"scan_item_barcode": code}),
	]
	for doctype, filters in checks:
		name = frappe.db.get_value(doctype, filters, "name")
		if name:
			return {"found": True, "doctype": doctype, "name": name, "route": _route(doctype, name)}

	for doctype, child_doctype in [
		("Inbound Package", "Inbound Package Item"),
		("Pick Task", "Pick Task Item"),
	]:
		parent = frappe.db.get_value(child_doctype, {"item_code": code}, "parent")
		if parent:
			return {"found": True, "doctype": doctype, "name": parent, "route": _route(doctype, parent)}

	item = frappe.db.get_value("Item", {"name": code, "disabled": 0}, ["name", "item_name"], as_dict=True)
	if item:
		return {
			"found": True,
			"doctype": "Item",
			"name": item.name,
			"label": item.item_name or item.name,
			"route": _route("Item", item.name),
		}

	warehouse = frappe.db.get_value(
		"Warehouse", {"name": code, "disabled": 0}, ["name", "warehouse_name"], as_dict=True
	)
	if warehouse:
		return {
			"found": True,
			"doctype": "Warehouse",
			"name": warehouse.name,
			"label": warehouse.warehouse_name or warehouse.name,
			"route": _route("Warehouse", warehouse.name),
		}

	return {"found": False, "code": code}
