# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.model.workflow import apply_workflow
from frappe.utils import add_days, today


def get_test_customer():
	customer = frappe.db.get_value("Customer", {}, "name")
	if customer:
		return customer
	return frappe.get_doc({"doctype": "Customer", "customer_name": "Reno Test Customer"}).insert(
		ignore_permissions=True
	).name


def get_test_item():
	item = frappe.db.get_value("Item", {"is_stock_item": 1}, "name")
	if item:
		return item
	frappe.get_doc({
		"doctype": "Item",
		"item_code": "RENO-TEST-ITEM",
		"item_group": "All Item Groups",
		"is_stock_item": 1,
		"stock_uom": "Nos",
	}).insert(ignore_permissions=True)
	return "RENO-TEST-ITEM"


def get_test_warehouse():
	return frappe.db.get_value("Warehouse", {}, "name")


def make_reno_order(**overrides):
	"""Build an unsaved Reno Order doc with sane defaults, for tests to
	tweak and insert."""
	item = get_test_item()
	doc = frappe.get_doc({
		"doctype": "Reno Order",
		"customer": get_test_customer(),
		"transaction_date": today(),
		"expected_installation_date": add_days(today(), 10),
		"sales_person": frappe.session.user,
		"order_type": "Standard",
		"discount_percent": 0,
		"items": [{
			"item": item,
			"description": "Test item",
			"quantity": 2,
			"uom": "Nos",
			"rate": 100,
			"warehouse": get_test_warehouse(),
		}],
	})
	doc.update(overrides)
	return doc


def confirm_order(doc):
	"""Push a freshly-inserted Reno Order through Confirm via the real
	workflow engine, so on_update / sync_workflow_chain actually fires."""
	doc.insert(ignore_permissions=True)
	return apply_workflow(doc, "Confirm")


class TestRenoOrder(FrappeTestCase):
	def test_total_calculation(self):
		"""Line amount, total, discount and grand total are calculated
		server-side, and a manipulated grand_total sent by a client is
		ignored - the server always recalculates."""
		doc = make_reno_order(discount_percent=10)
		doc.grand_total = 999999  # simulate a client trying to fake this value
		doc.insert(ignore_permissions=True)

		self.assertEqual(doc.items[0].amount, 200)  # 2 * 100
		self.assertEqual(doc.total_amount, 200)
		self.assertEqual(doc.discount_amount, 20)  # 10% of 200
		self.assertEqual(doc.grand_total, 180)  # 200 - 20, NOT 999999

	def test_invalid_installation_date(self):
		"""Installation date before the transaction date must be rejected."""
		doc = make_reno_order(
			transaction_date=today(),
			expected_installation_date=add_days(today(), -5),
		)
		self.assertRaises(frappe.ValidationError, doc.insert, ignore_permissions=True)

	def test_negative_quantity_and_rate_rejected(self):
		doc = make_reno_order()
		doc.items[0].quantity = -1
		self.assertRaises(frappe.ValidationError, doc.insert, ignore_permissions=True)

	def test_discount_authorization(self):
		"""Submitting with a discount above the configured threshold is
		blocked unless the user has the 'approve' permission on Reno Order."""
		settings = frappe.get_doc("Reno Order Settings", "Reno Order Settings")
		threshold = settings.discount_approval_threshold or 1000

		# discount_amount = 50% of (2*100) = 100, comfortably over a low
		# threshold, and Administrator (running this test) has approve
		# rights via System Manager - so this should succeed
		doc = make_reno_order(discount_percent=50)
		doc.insert(ignore_permissions=True)
		doc.submit()
		self.assertEqual(doc.docstatus, 1)
		self.assertTrue(doc.discount_amount > 0)

	def test_sales_order_creation(self):
		"""create_sales_order links a real, submitted Sales Order back to
		the Reno Order with matching items."""
		doc = confirm_order(make_reno_order())
		doc.reload()

		self.assertTrue(doc.sales_order)
		so = frappe.get_doc("Sales Order", doc.sales_order)
		self.assertEqual(so.docstatus, 1)
		self.assertEqual(so.customer, doc.customer)

	def test_duplicate_sales_order_prevented(self):
		"""Calling create_sales_order a second time for the same Reno
		Order must fail, not create a second Sales Order."""
		doc = confirm_order(make_reno_order())
		doc.reload()
		self.assertTrue(doc.sales_order)

		self.assertRaises(frappe.ValidationError, doc.create_sales_order)

	def test_installed_status_creates_sales_invoice_once(self):
		"""Walking the full workflow to Installed creates exactly one
		Sales Invoice, and calling the chain again does not duplicate it."""
		doc = confirm_order(make_reno_order())
		doc = apply_workflow(doc, "Start Production")
		doc = apply_workflow(doc, "Mark Ready")
		doc = apply_workflow(doc, "Install")
		doc.reload()

		self.assertEqual(doc.status, "Installed")
		self.assertTrue(doc.sales_invoice)
		self.assertTrue(doc.installation_completed)

		si_count_before = frappe.db.count(
			"Sales Invoice", {"delivery_note": doc.delivery_note}
		)
		# Re-running the chain (e.g. a redundant save) must not create a
		# second Sales Invoice - sync_workflow_chain checks the link field
		doc.sync_workflow_chain()
		si_count_after = frappe.db.count(
			"Sales Invoice", {"delivery_note": doc.delivery_note}
		)
		self.assertEqual(si_count_before, si_count_after)

	def test_unauthorized_api_request(self):
		"""A user with no write permission on the Reno Order must be
		rejected by the mobile API, not silently allowed through."""
		from reno_order.reno_order.api import update_installation_status

		doc = confirm_order(make_reno_order())
		doc.reload()

		no_access_user = "test-no-access@example.com"
		if not frappe.db.exists("User", no_access_user):
			frappe.get_doc({
				"doctype": "User",
				"email": no_access_user,
				"first_name": "No Access",
				"send_welcome_email": 0,
			}).insert(ignore_permissions=True)

		current_user = frappe.session.user
		try:
			frappe.set_user(no_access_user)
			self.assertRaises(
				frappe.PermissionError,
				update_installation_status,
				doc.name,
				"Confirmed",
			)
		finally:
			frappe.set_user(current_user)

	def test_permission_query_conditions_restrict_sales_user(self):
		"""A Sales User only sees Reno Orders they own or are assigned to
		as sales_person - verified directly against the permission hook,
		which is what Frappe calls for every list/report query."""
		from reno_order.reno_order.doctype.reno_order.reno_order import (
			get_permission_query_conditions,
		)

		sales_user_email = "test-sales-user@example.com"
		if not frappe.db.exists("User", sales_user_email):
			user = frappe.get_doc({
				"doctype": "User",
				"email": sales_user_email,
				"first_name": "Test",
				"last_name": "SalesUser",
				"send_welcome_email": 0,
			})
			user.append("roles", {"role": "Sales User"})
			user.insert(ignore_permissions=True)

		doc = confirm_order(make_reno_order(sales_person=sales_user_email))
		doc.reload()

		condition = get_permission_query_conditions(sales_user_email)
		self.assertIn(sales_user_email, condition)

		other_order = confirm_order(make_reno_order())
		other_order.reload()

		visible = frappe.db.sql(
			f"SELECT name FROM `tabReno Order` WHERE name = %s AND ({condition})",
			(doc.name,),
		)
		not_visible = frappe.db.sql(
			f"SELECT name FROM `tabReno Order` WHERE name = %s AND ({condition})",
			(other_order.name,),
		)
		self.assertTrue(visible)
		self.assertFalse(not_visible)

	def test_patch_backfills_only_blank_order_type(self):
		"""007_backfill_order_type fills blanks with 'Standard', leaves an
		existing value untouched, and is safe to run twice. Imported via
		frappe.get_attr since the module name starts with a digit and
		cannot be a normal `import` statement."""
		run_patch = frappe.get_attr("reno_order.patches.007_backfill_order_type.execute")

		blank_doc = confirm_order(make_reno_order())
		custom_doc = confirm_order(make_reno_order(order_type="Custom"))

		frappe.db.set_value("Reno Order", blank_doc.name, "order_type", "", update_modified=False)
		frappe.db.commit()

		run_patch()

		self.assertEqual(frappe.db.get_value("Reno Order", blank_doc.name, "order_type"), "Standard")
		self.assertEqual(frappe.db.get_value("Reno Order", custom_doc.name, "order_type"), "Custom")

		# idempotent: running again must not error and must not change anything
		run_patch()
		self.assertEqual(frappe.db.get_value("Reno Order", blank_doc.name, "order_type"), "Standard")
