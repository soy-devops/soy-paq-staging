#!/usr/bin/env python3
"""Guard against real client data and version drift reaching the public mirror.

Regression guard for two incidents found during a 2026-09-03 deploy-readiness
review of this repo:
  * Real client names ("Harmony") were found written into PROJECT.md/CHANGELOG.md,
    public-tracked files, contradicting this repo's own README.md hygiene rule.
  * Two different CLOUD_DEPLOYMENT.md copies disagreed on the target Frappe
    version (v15 vs v16); only luck made the correct one the one already live.

Add new client names to BANNED_TERMS as they're onboarded.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BANNED_TERMS = [
	"harmony",
]

# Public-tracked files that must never contain a banned term. Add here, not to
# .gitignore - .gitignore only keeps a file from being tracked at all
# (BUSINESS_CONTEXT.md, AGENT.md); these files ARE meant to be public.
CHECKED_FILES = [
	"PROJECT.md",
	"CHANGELOG.md",
	"README.md",
	"CLOUD_DEPLOYMENT.md",
]

errors: list[str] = []

# --- Check 1: banned client/business terms in public files ---
for filename in CHECKED_FILES:
	path = ROOT / filename
	if not path.is_file():
		continue
	text = path.read_text(encoding="utf-8")
	for term in BANNED_TERMS:
		if re.search(re.escape(term), text, re.IGNORECASE):
			line_no = next(
				(i + 1 for i, line in enumerate(text.splitlines()) if term.lower() in line.lower()),
				"?",
			)
			errors.append(f"{filename}:{line_no}: found banned term '{term}' - this file is public")

# --- Check 2: CLOUD_DEPLOYMENT.md's stated Frappe version matches pyproject.toml ---
pyproject_path = ROOT / "pyproject.toml"
deploy_doc_path = ROOT / "CLOUD_DEPLOYMENT.md"

if pyproject_path.is_file() and deploy_doc_path.is_file():
	pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
	pin = pyproject.get("tool", {}).get("bench", {}).get("frappe-dependencies", {}).get("frappe", "")
	match = re.search(r">=(\d+)\.", pin)
	if match:
		pinned_major = match.group(1)
		deploy_text = deploy_doc_path.read_text(encoding="utf-8")
		versions_mentioned = set(re.findall(r"Frappe/ERPNext v(\d+)", deploy_text))
		versions_mentioned |= set(re.findall(r"frappe = \">=(\d+)\.", deploy_text))
		wrong = versions_mentioned - {pinned_major}
		if wrong:
			errors.append(
				f"CLOUD_DEPLOYMENT.md mentions Frappe v{sorted(wrong)}, "
				f"but pyproject.toml pins v{pinned_major} - these must match"
			)

if errors:
	print("FAIL: sanitation/version check failed")
	for error in errors:
		print(f"  - {error}")
	sys.exit(1)

print("OK: no banned terms found, Frappe version references match pyproject.toml")
