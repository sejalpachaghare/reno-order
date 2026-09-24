# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""CI-only helper: creates the small set of standard Frappe/ERPNext master
records that the setup wizard normally creates, but a headless
`bench install-app` in CI does not. Frappe's test framework auto-generates
test records by walking every Link field on every doctype it touches
(Reno Order -> Customer -> Contact -> Gender, Customer -> Territory, etc.),
so a fresh CI site is missing whatever that walk needs.

Rather than discovering these one CI run at a time, this creates the
full known set in one place, defensively (skips anything that already
exists). Run once, after `bench migrate`, before `bench run-tests`.

Not part of the app itself - only referenced from .github/workflows/ci.yml.
"""

import frappe


def _create_if_missing(doctype, name, **fields):
	if frappe.db.exists(doctype, name):
		return
	doc = frappe.get_doc({"doctype": doctype, **fields})
	doc.insert(ignore_permissions=True, ignore_if_duplicate=True)


def run():
	# Simple lookup masters used by Contact / Employee / User test records
	for gender in ("Male", "Female", "Other", "Prefer not to say"):
		_create_if_missing("Gender", gender, gender=gender)

	for salutation in ("Mr", "Ms", "Mrs", "Dr", "Prof"):
		_create_if_missing("Salutation", salutation, salutation=salutation)

	# Root tree nodes ERPNext's setup wizard normally creates
	_create_if_missing("Warehouse Type", "Transit")
	_create_if_missing(
		"Customer Group", "All Customer Groups",
		customer_group_name="All Customer Groups", is_group=1,
	)
	_create_if_missing(
		"Territory", "All Territories",
		territory_name="All Territories", is_group=1,
	)
	_create_if_missing(
		"Item Group", "All Item Groups",
		item_group_name="All Item Groups", is_group=1,
	)
	_create_if_missing(
		"Supplier Group", "All Supplier Groups",
		supplier_group_name="All Supplier Groups", is_group=1,
	)

	frappe.db.commit()
	print("[ci bootstrap] standard test master data ready")
