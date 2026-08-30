from __future__ import annotations

import json
from urllib.parse import quote

import frappe
from frappe.utils import flt, now_datetime

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
	"Inbound Package": ["Stored", "Consolidated", "Shipped", "Delivered"],
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
			"route": _route("Shipment Task", r.name),
		}
		for r in rows
	]


def _list_receive_packages(limit: int = 50) -> list[dict]:
	rows = frappe.get_all(
		"Inbound Package",
		filters={"status": ["!=", "Exception"]},
		fields=[
			"name",
			"external_tracking_number",
			"customer",
			"status",
			"carrier",
			"modified",
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
			bucket = counts.setdefault(child.parent, {"lines": 0, "confirmed": 0, "staged": 0})
			bucket["lines"] += 1
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
			"lines": counts.get(r.name, {}).get("lines", 0),
			"confirmed_lines": counts.get(r.name, {}).get("confirmed", 0),
			"staged_lines": counts.get(r.name, {}).get("staged", 0),
			"image": item_images.get(first_item_by_parent.get(r.name)),
			"modified": str(r.modified),
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
_DEFAULT_WAREHOUSE_EXCLUDE = ("Damaged", "Returns")


def _default_warehouse(zone: str | None = None) -> str | None:
	"""Pick a real, working leaf warehouse under the default company.

	`zone` narrows to a specific area by warehouse_name substring (e.g. "Receiving",
	"Storage"). Without it, exception zones (Damaged/Returns) are skipped - they are
	never a sensible default source or destination for a manually created task.
	"""
	filters = {"is_group": 0, "disabled": 0, "company": DEFAULT_COMPANY}
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
		doc.append(
			"items",
			{
				"item_code": item["item_code"],
				"qty": item["qty"],
				"uom": item.get("uom") or frappe.db.get_value("Item", item["item_code"], "stock_uom"),
				"s_warehouse": item.get("s_warehouse"),
				"t_warehouse": item.get("t_warehouse"),
			},
		)
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


def _resolve_bin(code: str) -> str:
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
		name = frappe.db.get_value("Warehouse", {"name": ["like", f"%- {code} -%"]}, "name")
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
	default_customer = frappe.db.get_value("Customer", {"name": DEFAULT_TEST_CUSTOMER, "disabled": 0}, "name")
	if not default_customer:
		frappe.throw(
			f"Default customer '{DEFAULT_TEST_CUSTOMER}' was not found (or is disabled). "
			"Pick a customer explicitly, or update DEFAULT_TEST_CUSTOMER."
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
		if quantity <= 0:
			frappe.throw(f"Quantity for {item_code} must be greater than zero.")
		item = frappe.db.get_value("Item", item_code, ["item_name", "stock_uom", "disabled"], as_dict=True)
		if not item:
			frappe.throw(f"Item {item_code} was not found in ERPNext.")
		if item.disabled:
			frappe.throw(f"Item {item_code} is disabled in ERPNext.")
		rows.append(
			{"item_code": item_code, "item_name": item.item_name, "uom": item.stock_uom, "quantity": quantity}
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


def _task(doc, label: str) -> dict | None:
	if not doc:
		return None

	order = (
		_purchase_order_context(doc.get("purchase_order"))
		if doc.doctype == "Inbound ASN"
		else _sales_order_context(doc.get("sales_order"))
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
			["item_name", "image", "stock_uom", "disabled", "modified"],
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
				"assigned_bin": row.get("assigned_bin") or "",
				"source_warehouse": row.get("source_warehouse") or "",
				"source_bin": row.get("source_bin") or "",
				"status": row.get("status") or row.get("condition") or "Expected",
				"exception_reason": row.get("exception_reason") or "",
			}
		)
	return rows


def _inventory_snapshot() -> dict:
	"""Build a current stock and storage snapshot from ERPNext Item/Bin data."""
	items = frappe.get_all(
		"Item",
		filters={"is_stock_item": 1, "disabled": 0},
		fields=["name", "item_name", "item_group", "stock_uom", "image", "modified"],
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
	for stock_bin in bins:
		actual = float(stock_bin.actual_qty or 0)
		reserved = float(stock_bin.reserved_qty or 0)
		location = {
			"warehouse": stock_bin.warehouse,
			"on_hand": actual,
			"reserved": reserved,
			"available": actual - reserved,
			"projected": float(stock_bin.projected_qty or 0),
			"incoming": float(stock_bin.ordered_qty or 0),
		}
		bins_by_item.setdefault(stock_bin.item_code, []).append(location)
		if stock_bin.warehouse in warehouse_totals:
			warehouse_totals[stock_bin.warehouse]["item_count"] += 1
			warehouse_totals[stock_bin.warehouse]["on_hand"] += actual
			warehouse_totals[stock_bin.warehouse]["reserved"] += reserved

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
		},
	}


CLAIM_FIELD = {
	"Pick Task": "assigned_to",
	"Pack Task": "assigned_user",
	"Shipment Task": "assigned_user",
}


def _claimable_task(doctype: str, name: str):
	if doctype not in CLAIM_FIELD:
		frappe.throw(f"{doctype} tasks cannot be claimed.")
	if not name or not frappe.db.exists(doctype, name):
		frappe.throw(f"{doctype} {name or ''} was not found.")
	doc = frappe.get_doc(doctype, name)
	if not doc.has_permission("write"):
		frappe.throw(f"You do not have permission to claim {doctype} {name}.", frappe.PermissionError)
	if doc.get("status") in ("Completed", "Cancelled", "Shipped"):
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
	]
	for doctype, field, kind, done_statuses in checks:
		rows = frappe.get_all(
			doctype,
			filters={field: user, "status": ["not in", done_statuses]},
			fields=["name", "sales_order"],
			limit_page_length=2,
		)
		for row in rows:
			if doctype == exclude_doctype and row.name == exclude_name:
				continue
			return {"kind": kind, "reference": row.sales_order or row.name, "name": row.name}
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
	"Inbound Package": ("package_items", "quantity"),
}


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
	return {"name": doc.name, "items": _item_rows(doc, fieldname, quantity_field)}


def _writable_task(doctype: str, name: str):
	if not name or not frappe.db.exists(doctype, name):
		frappe.throw(f"{doctype} {name or ''} was not found.")
	doc = frappe.get_doc(doctype, name)
	if not doc.has_permission("write"):
		frappe.throw(f"You do not have permission to update {doctype} {name}.", frappe.PermissionError)
	if doc.get("status") in ("Completed", "Cancelled", "Shipped"):
		frappe.throw(f"{doctype} {name} is already {doc.get('status')}.")
	return doc


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

	pick_order = _sales_order_context(pick_task.get("sales_order")) if pick_task else {}
	pack_order = _sales_order_context(pack_task.get("sales_order")) if pack_task else {}
	shipment_order = _sales_order_context(shipment_task.get("sales_order")) if shipment_task else {}
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
				"task_customer": pick_task.get("customer") if pick_task else "",
				"warehouse": pick_task.get("warehouse") if pick_task else "",
				"assigned_to": _user(pick_task.get("assigned_to") if pick_task else None),
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
	asn.naming_series = "ASN-.#####"
	asn.customer = customer
	asn.status = "Expected"
	asn.target_warehouse = target_warehouse
	asn.carrier = carrier
	asn.external_tracking_number = f"ASN-{frappe.generate_hash(length=6).upper()}"
	for row in rows:
		asn.append("asn_item", {"item_code": row["item_code"], "expected_qty": row["quantity"]})
	asn.insert()

	package = frappe.new_doc("Inbound Package")
	package.naming_series = "SPQ-.#####"
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


def _writable_package(name: str):
	if not name or not frappe.db.exists("Inbound Package", name):
		frappe.throw(f"Inbound Package {name or ''} was not found.")
	doc = frappe.get_doc("Inbound Package", name)
	if not doc.has_permission("write"):
		frappe.throw(f"You do not have permission to update Inbound Package {name}.", frappe.PermissionError)
	if doc.get("status") in ("Stored", "Consolidated", "Shipped", "Delivered"):
		frappe.throw(f"Inbound Package {name} is already {doc.get('status')}.")
	return doc


def _package_row(doc, item_code: str):
	item_code = (item_code or "").strip()
	if not item_code:
		frappe.throw("Scan or enter an item barcode.")
	row = next((row for row in doc.get("package_items") or [] if row.get("item_code") == item_code), None)
	if not row:
		frappe.throw(f"Item {item_code} is not expected on Inbound Package {doc.name}.")
	return row


@frappe.whitelist()
def receive_item(package_name: str, item_code: str, quantity: float = 1) -> dict:
	"""Confirm a quantity of a single expected item was physically counted."""
	doc = _writable_package(package_name)
	row = _package_row(doc, item_code)
	if row.get("assigned_bin"):
		frappe.throw(f"{row.item_code} is already staged - it can no longer be re-confirmed.")
	quantity = flt(quantity)
	if quantity <= 0:
		frappe.throw("Confirm quantity must be greater than zero.")
	remaining = max(flt(row.get("quantity")) - flt(row.get("received_qty")), 0)
	if quantity > remaining:
		frappe.throw(f"Only {remaining:g} units remain to confirm for {row.item_code}.")
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
	"""Flag an inspection exception (Damaged / Missing / Hold / Unknown SKU) on a received line."""
	allowed = {"Damaged", "Missing", "Hold", "Unknown SKU"}
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
	"""Put away a confirmed item into a real bin - this is a real, submitted stock receipt."""
	doc = _writable_package(package_name)
	row = _package_row(doc, item_code)
	if row.get("assigned_bin"):
		frappe.throw(f"{row.item_code} is already staged at {row.assigned_bin}.")
	if flt(row.get("received_qty")) <= 0:
		frappe.throw(f"Confirm {row.item_code} before staging it.")
	bin_warehouse = _resolve_bin(bin_code)

	company = _warehouse_company(bin_warehouse) or _warehouse_company(doc.get("target_warehouse"))
	_create_stock_entry(
		"Material Receipt",
		[
			{
				"item_code": row.item_code,
				"qty": flt(row.get("received_qty")),
				"uom": row.get("uom"),
				"t_warehouse": bin_warehouse,
			}
		],
		company=company,
	)

	row.assigned_bin = bin_warehouse
	doc.status = "Inspecting"
	doc.last_scan_action = f"Staged {row.item_code} to {bin_warehouse}"
	doc.save()
	_publish_task_update(doc)
	return {"name": doc.name, "item_code": row.item_code, "assigned_bin": bin_warehouse}


@frappe.whitelist()
def complete_receipt(package_name: str) -> dict:
	"""Confirm every received item has been staged into a bin, then close out the package."""
	doc = _writable_package(package_name)
	pending = [
		row.item_code
		for row in doc.get("package_items") or []
		if not row.get("assigned_bin") and row.get("condition") != "Missing"
	]
	if pending:
		frappe.throw(f"Stage every item into a bin before storing: {', '.join(pending)}")
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
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def create_pick_task(customer: str = None, warehouse: str = None, items=None) -> dict:
	"""Create a real, standalone Pick Task for testing when no Sales Order exists yet.

	The record is a genuine Pick Task row (not a mock) - it immediately works with
	confirm_pick_location / pick_item / unpick_item / flag_pick_item / complete_pick.
	"""
	rows = _parse_manual_items(items)
	warehouse = warehouse or _default_warehouse("Storage")
	if not warehouse:
		frappe.throw("No warehouse is configured in ERPNext.")

	doc = frappe.new_doc("Pick Task")
	doc.naming_series = "PICK-.#####"
	doc.status = "Pending"
	doc.customer = _resolve_customer(customer)
	doc.warehouse = warehouse
	doc.pick_state = "Waiting for Bin"
	doc.scan_bin = warehouse
	doc.scan_item_barcode = rows[0]["item_code"]
	doc.current_status = f"Manually created with {len(rows)} line(s), no source order"
	for row in rows:
		doc.append(
			"pick_items",
			{
				"item_code": row["item_code"],
				"item_name": row["item_name"],
				"uom": row["uom"],
				"required_qty": row["quantity"],
				"picked_qty": 0,
				"source_warehouse": warehouse,
				"source_bin": warehouse,
				"status": "Pending",
			},
		)
	_update_pick_totals(doc)
	doc.insert()
	_publish_task_update(doc)
	return {"name": doc.name, "route": _route("Pick Task", doc.name)}


@frappe.whitelist()
def confirm_pick_location(task_name: str, location_code: str) -> dict:
	"""Persist a validated bin scan on a Pick Task."""
	doc = _writable_task("Pick Task", task_name)
	expected = doc.get("scan_bin") or doc.get("warehouse")
	location_code = (location_code or "").strip()
	if not expected or location_code.casefold() != str(expected).casefold():
		frappe.throw(
			f"Expected location {expected or 'not configured'}, received {location_code or 'blank'}."
		)

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
	if doc.get("pick_state") != "Waiting for Item":
		frappe.throw("Confirm the pick location before scanning an item.")
	row = _task_row(doc, item_code)
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
	_sync_pack_from_pick(doc)
	_publish_task_update(doc)
	return {"name": doc.name, "item_code": row.item_code, "picked_qty": row.picked_qty}


@frappe.whitelist()
def unpick_item(task_name: str, item_code: str, quantity: float = 1) -> dict:
	"""Reduce a picked quantity on a Pick Task row."""
	doc = _writable_task("Pick Task", task_name)
	if doc.get("pick_state") != "Waiting for Item":
		frappe.throw("Confirm the pick location before changing an item.")
	row = _task_row(doc, item_code)
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
	task_name: str, item_code: str, reason: str, handpick: int = 0, quantity: float = 0
) -> dict:
	"""Persist a manual pick action or exception reason on a Pick Task row."""
	doc = _writable_task("Pick Task", task_name)
	if doc.get("pick_state") != "Waiting for Item":
		frappe.throw("Confirm the pick location before updating an item.")
	row = _task_row(doc, item_code)
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
	doc.status = "Picking"
	doc.scan_item_barcode = item_code
	doc.last_scanned_row = row.name
	doc.last_scan_action = f"{'Handpicked' if handpick else 'Flagged'} {row.item_code}: {reason}"
	_update_pick_totals(doc)
	doc.save()
	_sync_pack_from_pick(doc)
	_publish_task_update(doc)
	return {"name": doc.name, "item_code": row.item_code, "status": row.status, "exception_reason": reason}


@frappe.whitelist()
def complete_pick(task_name: str) -> dict:
	"""Complete a Pick Task after all quantities are persisted."""
	doc = _writable_task("Pick Task", task_name)
	_update_pick_totals(doc)
	if flt(doc.total_picked_qty) < flt(doc.total_required_qty):
		frappe.throw(
			f"Pick is incomplete: {doc.total_picked_qty:g} of {doc.total_required_qty:g} units picked."
		)
	doc.status = "Completed"
	doc.current_status = "Pick completed and released to packing"
	doc.completed_by = frappe.session.user
	doc.completed_at = now_datetime()
	doc.save()
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
	doc.naming_series = "PACK-.#####"
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
	for name in shipment_names:
		shipment = frappe.get_doc("Shipment Task", name)
		if shipment.status not in ("Shipped", "Cancelled"):
			shipment.status = "Ready to Ship"
			shipment.save(ignore_permissions=True)
			_publish_task_update(shipment)
	_publish_task_update(doc)
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def create_shipment_task(
	customer: str = None, carrier: str = "UPS", tracking_number: str = None, items=None
) -> dict:
	"""Create a real, standalone Shipment Task for testing when no linked Pack Task exists yet.

	Pre-seeded as already packed so it works immediately with generate_shipment_label
	and mark_shipment_shipped. tracking_number is left blank unless passed explicitly, so
	generate_shipment_label still buys a real Shippo label instead of skipping it.
	"""
	rows = _parse_manual_items(items)
	warehouse = _default_warehouse("Storage")

	doc = frappe.new_doc("Shipment Task")
	doc.naming_series = "SHIP-.#####"
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


@frappe.whitelist()
def generate_shipment_label(task_name: str) -> dict:
	"""Buy a real shipping label via Shippo and persist the tracking number / label URL."""
	from soypaq import shippo_client

	doc = _writable_shipment(task_name)
	if not doc.get("tracking_number"):
		label = shippo_client.buy_cheapest_label()
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


@frappe.whitelist()
def get_inventory() -> dict:
	"""Return a fresh ERPNext stock and warehouse snapshot for the WMS."""
	return _inventory_snapshot()


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
