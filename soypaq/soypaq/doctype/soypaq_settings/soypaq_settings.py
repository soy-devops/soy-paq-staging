import re
from pathlib import Path

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

import soypaq


def _recent_changes(limit: int = 3) -> str:
	"""Top `limit` version headings from CHANGELOG.md; empty if the file is not shipped."""
	path = Path(soypaq.__file__).resolve().parent.parent / "CHANGELOG.md"
	try:
		text = path.read_text(encoding="utf-8")
	except OSError:
		return ""
	return "\n".join(re.findall(r"^## .+$", text, re.M)[:limit])


class SoyPaqSettings(Document):
	def onload(self):
		# Display only; the fields are read-only and never stored.
		self.app_version = soypaq.__version__
		self.recent_changes = _recent_changes()

	def validate(self):
		# "Only future orders": stamp the moment billing is switched on, and never move it back
		# just because someone toggles it off and on again without a gap in billing intent.
		if self.enable_task_billing:
			if not (self.billing_company and self.billing_receivable_account and self.billing_income_account):
				frappe.throw("Set the billing company, receivable account and revenue account before enabling billing.")
			if not self.billing_start:
				self.billing_start = now_datetime()
		else:
			self.billing_start = None
