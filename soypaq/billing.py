"""Interim fulfilment billing: one draft Journal Entry per completed Pick Task.

Stands in for Sales Invoices until the Medusa pick-ship flow lands. Mirrors the hand-made entries
(e.g. ACC-JV-2026-00045): Dr Accounts Receivable / Cr Fulfilment Revenue, both lines carrying the
customer as party, "Order <task>" in the cheque reference fields. Drafts, so accounting reviews and
submits. Never raises into the pick flow: a billing problem is logged, not a blocked warehouse.
"""

import frappe
from frappe.utils import flt, get_datetime, getdate


def _source_reference(pick_task) -> str:
	number, order_id = pick_task.get("medusa_order_number"), pick_task.get("medusa_order_id")
	if not (number or order_id):
		return ""
	return f"Medusa #{number} ({order_id})" if number and order_id else f"Medusa {number or order_id}"


def _log(
	pick_task, outcome: str, reason: str = "", journal_entry: str | None = None, amount: float = 0
) -> None:
	"""One Pick Billing Log row per completion attempt (logging only; never blocks the pick)."""
	frappe.get_doc(
		{
			"doctype": "Pick Billing Log",
			"pick_task": pick_task.name,
			"source_reference": _source_reference(pick_task),
			"customer": pick_task.get("customer"),
			"completed_at": pick_task.get("completed_at"),
			"outcome": outcome,
			"reason": reason,
			"journal_entry": journal_entry,
			"journal_entry_status": "Draft" if journal_entry else "",
			"amount": amount,
		}
	).insert(ignore_permissions=True)


def sync_log_status(doc, method=None) -> None:
	"""Journal Entry doc_event: keep the log's entry status in step (Submitted / Cancelled / removed)."""
	status = {"on_submit": "Submitted", "on_cancel": "Cancelled", "on_trash": "Deleted"}.get(method)
	if status:
		frappe.db.set_value(
			"Pick Billing Log",
			{"journal_entry": doc.name},
			"journal_entry_status",
			status,
			update_modified=False,
		)


def _skip(pick_task, reason: str) -> None:
	_log(pick_task, "Skipped", reason=reason)
	return None


def create_task_journal_entry(pick_task) -> str | None:
	"""Create the draft JE for a just-completed Pick Task and log the outcome; return the JE name or None."""
	settings = frappe.get_cached_doc("SoyPaq Settings")
	if not settings.enable_task_billing or not settings.billing_start:
		return _skip(pick_task, "Billing is off")
	if pick_task.get("billing_journal_entry"):
		return None  # idempotent: never bill (or log) a task twice
	completed_at = get_datetime(pick_task.completed_at) if pick_task.completed_at else None
	if not completed_at or completed_at < get_datetime(settings.billing_start):
		return _skip(pick_task, "Completed before billing started")
	fee = flt(settings.pick_fee)
	customer = pick_task.customer
	if not customer:
		return _skip(pick_task, "No customer on the task")
	if fee <= 0:
		return _skip(pick_task, "Fee per task is zero")
	receivable = settings.billing_receivable_account
	income = settings.billing_income_account
	cost_center = settings.billing_cost_center or frappe.get_cached_value(
		"Company", settings.billing_company, "cost_center"
	)
	posting_date = getdate(completed_at)
	reference = f"Order {pick_task.name}"
	source = _source_reference(pick_task)
	remark = f"Reference #{reference} dated {posting_date.strftime('%m-%d-%Y')}" + (
		f" - {source}" if source else ""
	)

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = settings.billing_company
	je.posting_date = posting_date
	je.cheque_no = reference
	je.cheque_date = posting_date
	je.user_remark = remark
	je.pay_to_recd_from = customer
	je.title = customer
	for account, debit, credit in ((receivable, fee, 0), (income, 0, fee)):
		je.append(
			"accounts",
			{
				"account": account,
				"party_type": "Customer",
				"party": customer,
				"cost_center": cost_center,
				"debit_in_account_currency": debit,
				"credit_in_account_currency": credit,
				"user_remark": f"{reference} - {source}" if source else reference,
			},
		)
	je.flags.ignore_permissions = True
	je.insert()
	frappe.db.set_value("Pick Task", pick_task.name, "billing_journal_entry", je.name, update_modified=False)
	_log(pick_task, "Created", journal_entry=je.name, amount=fee)
	return je.name


def bill_completed_pick(pick_task) -> None:
	try:
		create_task_journal_entry(pick_task)
	except Exception as error:
		frappe.log_error(title=f"Pick billing failed for {pick_task.name}")
		try:
			_log(pick_task, "Failed", reason=str(error)[:500])
		except Exception:
			pass
