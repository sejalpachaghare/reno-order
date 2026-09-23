# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe

REPORT_NAME = "Monthly Reno Order Value"

QUERY = """
    SELECT
        DATE_FORMAT(transaction_date, '%Y-%m') as 'Month',
        status as 'Status',
        SUM(grand_total) as 'Total Value:Currency'
    FROM `tabReno Order`
    WHERE transaction_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
    GROUP BY DATE_FORMAT(transaction_date, '%Y-%m'), status
    ORDER BY Month DESC, Status
"""


def execute():
    """Create the Part 10 'Monthly Reno Order Value' Query Report if it
    does not already exist. Idempotent - safe to re-run."""
    if frappe.db.exists("Report", REPORT_NAME):
        return

    report = frappe.get_doc({
        "doctype": "Report",
        "report_name": REPORT_NAME,
        "ref_doctype": "Reno Order",
        "report_type": "Query Report",
        "is_standard": "No",
        "module": "Reno Order",
        "query": QUERY,
    })
    report.insert(ignore_permissions=True)
    frappe.db.commit()
