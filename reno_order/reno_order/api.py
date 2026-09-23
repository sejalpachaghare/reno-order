# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.workflow import get_transitions, apply_workflow


def get_reno_order_for_update(reno_order):
    """Load a Reno Order and confirm the logged-in user may write to it.
    Used by every mobile API below so permission checks live in one place."""
    if not frappe.db.exists("Reno Order", reno_order):
        frappe.throw(_("Reno Order {0} not found").format(reno_order), frappe.DoesNotExistError)

    doc = frappe.get_doc("Reno Order", reno_order)

    if not frappe.has_permission("Reno Order", "write", doc=doc):
        frappe.throw(
            _("You do not have permission to update {0}").format(reno_order),
            frappe.PermissionError
        )

    return doc


@frappe.whitelist()
def update_installation_status(reno_order: str, status: str):
    """Move a Reno Order to a new workflow status.

    Only transitions allowed by the Workflow for the current user's role
    are accepted - e.g. a Site Supervisor can only move
    'Ready for Installation' -> 'Installed', because that is the only
    transition the Workflow grants to their role.
    """
    doc = get_reno_order_for_update(reno_order)

    transitions = get_transitions(doc)
    action = next((t.action for t in transitions if t.next_state == status), None)

    if not action:
        allowed = [t.next_state for t in transitions]
        frappe.throw(
            _("Cannot move Reno Order from '{0}' to '{1}'. Allowed next status: {2}").format(
                doc.status, status, ", ".join(allowed) or "none for your role"
            ),
            frappe.ValidationError
        )

    apply_workflow(doc, action)
    return {"reno_order": reno_order, "status": status}


@frappe.whitelist()
def add_installation_remarks(reno_order: str, remarks: str):
    """Add a timestamped remark to a Reno Order's activity timeline."""
    doc = get_reno_order_for_update(reno_order)

    if not remarks or not remarks.strip():
        frappe.throw(_("Remarks cannot be empty"), frappe.ValidationError)

    doc.add_comment("Comment", remarks.strip())
    return {"reno_order": reno_order, "remarks": remarks.strip()}
