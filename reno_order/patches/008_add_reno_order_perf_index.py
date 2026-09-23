# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe


def execute():
    """Add a composite index on (transaction_date, status) to support the
    Monthly Reno Order Value report, which filters on transaction_date and
    groups by status. Without this index MariaDB does a full table scan
    (type=ALL) on every run of that report.

    frappe.db.add_index() is idempotent - if the index already exists it is
    a no-op, so this patch is safe to re-run."""
    frappe.db.add_index(
        "Reno Order",
        ["transaction_date", "status"],
        index_name="transaction_date_status_index",
    )
