import frappe

def execute():
    if not frappe.db.exists("Custom Field", {"dt": "Sales Order", "fieldname": "reno_order"}):
        frappe.get_doc({
            "doctype": "Custom Field",
            "dt": "Sales Order",
            "fieldname": "reno_order",
            "fieldtype": "Link",
            "label": "Reno Order",
            "options": "Reno Order",
            "insert_after": "name"
        }).insert()
        frappe.db.commit()
        print("✅ Added reno_order field to Sales Order")
