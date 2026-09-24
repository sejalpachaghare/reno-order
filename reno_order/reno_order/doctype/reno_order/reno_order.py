# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from contextlib import contextmanager

import frappe
from frappe.model.document import Document


@contextmanager
def as_system_user():
    """Run downstream ERPNext document creation with full rights, regardless of
    the triggering user's own permissions. Needed because ERPNext's accounts
    module (e.g. get_party_account) does its own hard permission checks that
    ignore_permissions=True on insert() does not bypass - a Site Supervisor
    is authorized to mark an order Installed, not to read Account records.

    frappe.set_user() also overwrites frappe.session.sid with the raw
    username (see frappe/__init__.py), which is harmless in a background
    job but corrupts the real session id for a live browser request - the
    response would then set a cookie that no longer matches any session,
    logging the user out. So the real sid is saved and restored explicitly,
    independent of whatever set_user() does to it."""
    current_user = frappe.session.user
    current_sid = frappe.session.sid
    frappe.set_user("Administrator")
    frappe.flags.ignore_permissions = True
    try:
        yield
    finally:
        frappe.flags.ignore_permissions = False
        frappe.set_user(current_user)
        frappe.session.sid = current_sid


def get_permission_query_conditions(user=None):
    """Row-level visibility per role - wired via hooks.py permission_query_conditions.
    Frappe calls this to build the WHERE clause for every Reno Order list/report
    query, so it applies everywhere (list view, reports, API list calls), not
    just the desk UI."""
    if not user:
        user = frappe.session.user

    roles = frappe.get_roles(user)

    # System Manager, Sales Manager and Accounts User get unrestricted visibility -
    # Sales Managers need team-wide oversight, Accounts User needs it for financial reporting
    if "System Manager" in roles or "Sales Manager" in roles or "Accounts User" in roles:
        return ""

    if "Sales User" in roles:
        user_escaped = frappe.db.escape(user)
        return f"""(`tabReno Order`.owner = {user_escaped}
            OR `tabReno Order`.sales_person = {user_escaped})"""

    if "Site Supervisor" in roles:
        return """`tabReno Order`.status in ('Ready for Installation', 'Installed')"""

    # No recognised role - no rows visible
    return "1=0"


class RenoOrder(Document):
    
    def before_save(self):
        self.calculate_totals()
        self.validate_business_rules()

    def calculate_totals(self):
        total = 0
        for item in self.get("items", []):
            item.amount = float(item.quantity or 0) * float(item.rate or 0)
            total += item.amount
        
        self.total_amount = total
        self.discount_amount = float(total * (self.discount_percent or 0) / 100)
        self.grand_total = total - self.discount_amount

    def validate_business_rules(self):
        for item in self.get("items", []):
            if item.quantity < 0 or item.rate < 0:
                frappe.throw("Quantity and rate must be positive")
        
        if self.expected_installation_date < self.transaction_date:
            frappe.throw("Installation date must be after order date")

    def validate(self):
        """Called before saving/submitting"""
        self.calculate_totals()
        self.validate_business_rules()

    def on_submit(self):
        """Called after document is submitted"""
        self.validate_discount_approval()

        # Part 7/8: notify the external CRM that this customer's order is
        # confirmed. Queued as a background job - the external call can
        # take 10-20s and must never make this save operation slow.
        from reno_order.reno_order.integrations.crm_sync import queue_crm_sync
        queue_crm_sync(self.name)

    def on_cancel(self):
        """Cancel downstream documents in reverse order: SI -> DN -> SO"""
        if self.get("sales_invoice"):
            si = frappe.get_doc("Sales Invoice", self.sales_invoice)
            if si.docstatus == 1:
                si.cancel()

        if self.get("delivery_note"):
            dn = frappe.get_doc("Delivery Note", self.delivery_note)
            if dn.docstatus == 1:
                dn.cancel()

        if self.get("sales_order"):
            so = frappe.get_doc("Sales Order", self.sales_order)
            if so.docstatus == 1:
                so.cancel()

        frappe.msgprint("✅ Linked Sales Order, Delivery Note & Sales Invoice cancelled")

    def on_update(self):
        """Called when Draft is first submitted (docstatus 0 -> 1)"""
        self.sync_workflow_chain()

    def on_update_after_submit(self):
        """Called on every later workflow transition (doc already submitted,
        docstatus stays 1) - Frappe routes these through a different hook than on_update"""
        self.sync_workflow_chain()

    def sync_workflow_chain(self):
        """Drives the ERPNext chain based on workflow state"""
        # Sync status field with workflow_state
        workflow_state = self.get("workflow_state")
        if workflow_state and self.status != workflow_state:
            frappe.db.set_value("Reno Order", self.name, "status", workflow_state)
            self.status = workflow_state

        # Confirmed -> customer committed, reserve stock via Sales Order
        if self.status == "Confirmed" and not self.get("sales_order"):
            self.create_sales_order()

        # Ready for Installation -> materials ready, stock actually leaves via Delivery Note
        elif self.status == "Ready for Installation" and not self.get("delivery_note"):
            self.create_delivery_note()

        # Installed -> job physically done, bill the customer via Sales Invoice
        elif self.status == "Installed" and not self.get("sales_invoice"):
            self.create_sales_invoice()
            frappe.db.set_value("Reno Order", self.name, "installation_completed", 1)

    def validate_discount_approval(self):
        """Check if discount exceeds approval threshold"""
        try:
            settings = frappe.get_doc("Reno Order Settings", "Reno Order Settings")
            threshold = settings.discount_approval_threshold or 1000
        except:
            threshold = 1000

        if self.discount_amount > threshold:
            if not frappe.has_permission("Reno Order", "approve"):
                frappe.throw(
                    f"Discount of {self.discount_amount} requires approval. "
                    f"Maximum allowed: {threshold}."
                )

    @frappe.whitelist()
    def create_sales_order(self):
        if self.get("sales_order"):
            frappe.throw(f"Sales Order {self.sales_order} already created for this Reno Order")

        so = frappe.get_doc({
            "doctype": "Sales Order",
            "customer": self.customer,
            "transaction_date": self.transaction_date,
            "delivery_date": self.expected_installation_date,
            "items": []
        })

        for item in self.items:
            so.append("items", {
                "item_code": item.item,
                "qty": item.quantity,
                "uom": item.uom,
                "rate": item.rate,
                "warehouse": item.warehouse
            })

        with as_system_user():
            so.insert(ignore_permissions=True)

            frappe.db.set_value("Reno Order", self.name, "sales_order", so.name)
            self.sales_order = so.name

            so.submit()
            frappe.db.commit()

        return so

    def create_delivery_note(self):
        """Create Delivery Note from Sales Order when materials are Ready for Installation"""
        if not self.get("sales_order"):
            return

        so = frappe.get_doc("Sales Order", self.sales_order)
        if so.docstatus != 1:
            return

        try:
            dn = frappe.get_doc({
                "doctype": "Delivery Note",
                "customer": self.customer,
                "posting_date": frappe.utils.today(),
                "against_sales_order": self.sales_order,
                "items": []
            })

            for item in so.items:
                dn.append("items", {
                    "item_code": item.item_code,
                    "qty": item.qty,
                    "uom": item.uom,
                    "warehouse": item.warehouse,
                    "rate": item.rate,
                    "sales_order": so.name,
                    "sales_order_item": item.name
                })

            with as_system_user():
                dn.insert(ignore_permissions=True)
                frappe.db.set_value("Reno Order", self.name, "delivery_note", dn.name)
                dn.submit()
            frappe.msgprint(f"✅ Delivery Note {dn.name} created from Sales Order")
        except Exception:
            frappe.log_error(title="Delivery Note Creation Failed", message=frappe.get_traceback())

    def create_sales_invoice(self):
        """Create Sales Invoice from Delivery Note when job is Installed - bills the customer"""
        delivery_note = self.get("delivery_note")
        if not delivery_note:
            return

        dn = frappe.get_doc("Delivery Note", delivery_note)
        if dn.docstatus != 1:
            return

        try:
            si = frappe.get_doc({
                "doctype": "Sales Invoice",
                "customer": self.customer,
                "posting_date": frappe.utils.today(),
                "delivery_note": dn.name,
                "due_date": frappe.utils.add_days(frappe.utils.today(), 30),
                "items": []
            })

            for item in dn.items:
                si.append("items", {
                    "item_code": item.item_code,
                    "qty": item.qty,
                    "uom": item.uom,
                    "rate": item.rate,
                    "delivery_note": dn.name,
                    "dn_detail": item.name
                })

            with as_system_user():
                si.insert(ignore_permissions=True)
                si.submit()
                frappe.db.set_value("Reno Order", self.name, "sales_invoice", si.name)
            frappe.msgprint(f"✅ Sales Invoice {si.name} created from Delivery Note")
        except Exception:
            frappe.log_error(title="Sales Invoice Creation Failed", message=frappe.get_traceback())


