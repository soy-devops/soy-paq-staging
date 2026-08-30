#!/usr/bin/env python3
"""Guard the doctype JSON contract that makes this app installable.

Regression guard for the class of bug that made the app un-installable on any site
but the original dev database:
  * a doctype left as custom=1 never ships with the app
  * a doctype JSON with no controller .py breaks import on a fresh install
  * a controller whose class name doesn't match Frappe's derivation fails at runtime

Frappe resolves the controller class as: doctype.replace(" ", "").replace("-", "")
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCTYPE_DIR = ROOT / "soypaq" / "soypaq" / "doctype"

errors: list[str] = []
checked = 0

if not DOCTYPE_DIR.is_dir():
	print(f"FAIL: no doctype directory at {DOCTYPE_DIR}")
	sys.exit(1)

for folder in sorted(p for p in DOCTYPE_DIR.iterdir() if p.is_dir()):
	if folder.name == "__pycache__":
		continue
	json_path = folder / f"{folder.name}.json"
	py_path = folder / f"{folder.name}.py"
	init_path = folder / "__init__.py"

	if not json_path.exists():
		errors.append(f"{folder.name}: missing {json_path.name}")
		continue

	try:
		meta = json.loads(json_path.read_text(encoding="utf-8"))
	except json.JSONDecodeError as exc:
		errors.append(f"{folder.name}: invalid JSON - {exc}")
		continue

	checked += 1
	name = meta.get("name", "")

	# 1. must not be a Custom DocType - those live only in a database
	if meta.get("custom"):
		errors.append(f"{name}: custom=1 - will NOT ship with the app")

	# 2. must declare its module
	if meta.get("module") != "SoyPaq":
		errors.append(f"{name}: module={meta.get('module')!r}, expected 'SoyPaq'")

	# 3. controller file + __init__.py must exist
	if not init_path.exists():
		errors.append(f"{name}: missing __init__.py")
	if not py_path.exists():
		errors.append(f"{name}: missing controller {py_path.name}")
	else:
		expected_cls = name.replace(" ", "").replace("-", "")
		src = py_path.read_text(encoding="utf-8")
		if not re.search(rf"^class {re.escape(expected_cls)}\(", src, re.M):
			errors.append(
				f"{name}: controller must define 'class {expected_cls}(Document)' "
				f"(Frappe derives the class name from the doctype)"
			)

	# 4. naming: if it autonames by series, the field has to exist
	if meta.get("autoname") == "naming_series:":
		fieldnames = {f.get("fieldname") for f in meta.get("fields", [])}
		if "naming_series" not in fieldnames:
			errors.append(f"{name}: autoname='naming_series:' but no naming_series field")

	# 5. duplicate fieldnames
	seen: set[str] = set()
	for f in meta.get("fields", []):
		fn = f.get("fieldname")
		if fn in seen:
			errors.append(f"{name}: duplicate fieldname {fn!r}")
		seen.add(fn)

print(f"checked {checked} doctype(s) in {DOCTYPE_DIR.relative_to(ROOT)}")
if errors:
	print("\nFAILURES:")
	for e in errors:
		print(f"  - {e}")
	sys.exit(1)
print("doctype contract OK")
