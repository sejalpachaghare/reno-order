import frappe
from frappe.utils import today

def flag_overdue_installations():
    """Daily task to flag orders where installation is overdue"""

    # Find all orders that are overdue
    overdue_orders = frappe.get_list(
        "Reno Order",
        filters={
            "expected_installation_date": ["<", today()],
            "status": ["not in", ["Installed", "Closed", "Cancelled"]]
        },
        fields=["name", "customer", "expected_installation_date", "status"]
    )

    if not overdue_orders:
        return

    # Log overdue orders
    for order in overdue_orders:
        frappe.log_error(
            title="Overdue Installation Alert",
            message=(
                f"Overdue Installation: {order['name']} | Customer: {order['customer']} | "
                f"Expected: {order['expected_installation_date']} | Status: {order['status']}"
            )
        )

    # Optional: Send notification to admin
    if frappe.db.exists("User", "Administrator"):
        frappe.share.add(
            "Reno Order",
            overdue_orders[0]["name"],
            "Administrator",
            ptype="User",
            perm_level=0,
            shared=1
        )

    frappe.log_error(
        title="Daily Overdue Check",
        message=f"Found {len(overdue_orders)} overdue installations"
    )
