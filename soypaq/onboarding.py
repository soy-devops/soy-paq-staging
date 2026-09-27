"""Tenant onboarding: a Customer in the 3PL Client group gets its own Company, warehouse tree and item group.

Mirrors how the first tenant is laid out:

    <Customer> - <abbr>                     (root group)
      <Customer> - Receiving / PickPack / Returns / Damaged
      <Customer> - Storage                  (group)
        <Customer> - Storage - A01          (first bin; more via WMS "+ New bin")

plus an item group `<Customer>` for its product-type groups and an item-code prefix (first three consonants).
Idempotent: safe to re-run, only creates what is missing. Runs in the background after the Customer is saved.
"""

import re

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

TENANT_GROUP = "3PL Client"
ZONES = ("Receiving", "PickPack", "Returns", "Damaged")


def ensure_fields() -> None:
	create_custom_fields(
		{
			"Customer": [
				{
					"fieldname": "soy_tenant_section",
					"fieldtype": "Section Break",
					"label": "SoyPaq Tenant",
					"insert_after": "customer_group",
				},
				{
					"fieldname": "soy_item_prefix",
					"fieldtype": "Data",
					"label": "Item Code Prefix",
					"insert_after": "soy_tenant_section",
					"description": "Prefix for this tenant's item codes, e.g. HMN. Suggested from the name when onboarded.",
				},
				{
					"fieldname": "soy_onboarded",
					"fieldtype": "Check",
					"label": "Tenant Onboarded",
					"insert_after": "soy_item_prefix",
					"read_only": 1,
					"no_copy": 1,
				},
			]
		},
		update=True,
	)


def _abbr(name: str) -> str:
	"""Unique company abbreviation: initials of the words, padded from the name, numbered if taken."""
	words = re.findall(r"[A-Za-z0-9]+", name)
	base = "".join(w[0] for w in words).upper()[:3] or "T"
	if len(base) < 2:
		base = re.sub(r"[^A-Z0-9]", "", name.upper())[:3] or base
	taken = set(frappe.get_all("Company", pluck="abbr"))
	candidate, n = base, 1
	while candidate in taken:
		n += 1
		candidate = f"{base}{n}"
	return candidate


def suggest_prefix(name: str) -> str:
	"""First three consonants of the name (Example Client -> EXC style), unique among customers."""
	letters = re.sub(r"[^A-Z]", "", name.upper())
	consonants = "".join(c for c in letters if c not in "AEIOU")
	base = (consonants + letters)[:3] or "TNT"
	taken = set(frappe.get_all("Customer", filters={"soy_item_prefix": ["is", "set"]}, pluck="soy_item_prefix"))
	candidate, n = base, 1
	while candidate in taken:
		n += 1
		candidate = f"{base[:2]}{n}"
	return candidate


def _warehouse(company: str, warehouse_name: str, parent: str | None, is_group: int) -> str:
	name = frappe.db.get_value("Warehouse", {"company": company, "warehouse_name": warehouse_name})
	if name:
		return name
	doc = frappe.new_doc("Warehouse")
	doc.warehouse_name = warehouse_name
	doc.company = company
	doc.parent_warehouse = parent
	doc.is_group = is_group
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def onboard_tenant(customer: str) -> dict:
	"""Create whatever the tenant is missing and mark the Customer onboarded. Returns what exists after."""
	cust = frappe.get_doc("Customer", customer)
	made = []
	if not frappe.db.exists("Company", customer):
		reference = frappe.db.get_single_value("SoyPaq Settings", "billing_company") or frappe.db.get_value("Company", {}, "name")
		soy = (reference and frappe.db.get_value("Company", reference, ["default_currency", "country"], as_dict=True)) or {}
		company = frappe.new_doc("Company")
		company.company_name = customer
		company.abbr = _abbr(customer)
		company.default_currency = soy.get("default_currency") or "USD"
		company.country = soy.get("country") or "United States"
		company.create_chart_of_accounts_based_on = "Standard Template"
		company.chart_of_accounts = "Standard"
		company.flags.ignore_permissions = True
		company.insert()
		made.append(f"Company {customer} ({company.abbr})")

	root = _warehouse(customer, customer, None, 1)
	for zone in ZONES:
		_warehouse(customer, f"{customer} - {zone}", root, 0)
	storage = _warehouse(customer, f"{customer} - Storage", root, 1)
	if not frappe.db.exists("Warehouse", {"parent_warehouse": storage}):
		_warehouse(customer, f"{customer} - Storage - A01", storage, 0)
		made.append("Warehouses (Receiving, PickPack, Returns, Damaged, Storage, bin A01)")

	if not frappe.db.exists("Item Group", customer):
		frappe.get_doc(
			{"doctype": "Item Group", "item_group_name": customer, "parent_item_group": "All Item Groups", "is_group": 1}
		).insert(ignore_permissions=True)
		made.append("Item group")

	updates = {"soy_onboarded": 1}
	if not cust.get("soy_item_prefix"):
		updates["soy_item_prefix"] = suggest_prefix(customer)
		made.append(f"Item prefix {updates['soy_item_prefix']}")
	frappe.db.set_value("Customer", customer, updates, update_modified=False)
	cust.add_comment("Info", "SoyPaq tenant onboarded: " + "; ".join(made) if made else "SoyPaq tenant already set up.")
	return {"customer": customer, "created": made}


def _run(customer: str) -> None:
	from frappe.utils.synchronization import filelock

	try:
		# on_update fires on every save; the lock keeps two overlapping jobs from building the same tenant.
		with filelock(f"tenant_onboard_{customer}", timeout=120):
			if frappe.db.get_value("Customer", customer, "soy_onboarded"):
				return
			onboard_tenant(customer)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title=f"Tenant onboarding failed for {customer}")
		try:
			frappe.get_doc("Customer", customer).add_comment("Info", "SoyPaq tenant onboarding failed - see Error Log.")
			frappe.db.commit()
		except Exception:
			pass


def on_customer_save(doc, method=None) -> None:
	"""Customer doc_event: a 3PL Client that is not onboarded yet is set up in the background."""
	if doc.get("customer_group") != TENANT_GROUP or doc.get("soy_onboarded"):
		return
	frappe.enqueue(
		"soypaq.onboarding._run", customer=doc.name, queue="short", enqueue_after_commit=True, job_id=f"tenant-onboard-{doc.name}", deduplicate=True
	)
