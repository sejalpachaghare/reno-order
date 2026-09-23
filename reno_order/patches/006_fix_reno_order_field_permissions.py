import frappe

def execute():
    # Fix permissions on reno_order custom field
    if frappe.db.exists("Custom Field", {"dt": "Sales Order", "fieldname": "reno_order"}):
        frappe.db.set_value(
            "Custom Field",
            {"dt": "Sales Order", "fieldname": "reno_order"},
            {
                "read": 1,
                "write": 1,
                "insert": 1
            }
        )
        frappe.db.commit()
        print("✅ Fixed permissions on reno_order field")
