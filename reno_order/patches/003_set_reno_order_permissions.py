import frappe

def execute():
	"""Set permissions for Reno Order DocType by role"""
	
	doctype_name = "Reno Order"
	
	try:
		# Get the DocType document
		doctype_doc = frappe.get_doc("DocType", doctype_name)
		
		# Clear existing permissions
		doctype_doc.permissions = []
		
		# Define permissions
		permissions_data = [
			{"role": "System Manager", "permlevel": 0, "read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "amend": 1},
			{"role": "Sales Manager", "permlevel": 0, "read": 1, "write": 1, "create": 1, "submit": 1, "amend": 1},
			{"role": "Sales User", "permlevel": 0, "read": 1, "write": 1, "create": 1},
			{"role": "Production User", "permlevel": 0, "read": 1, "write": 1},
			{"role": "Site Supervisor", "permlevel": 0, "read": 1},
			{"role": "Accounts User", "permlevel": 0, "read": 1},
		]
		
		# Add permissions
		for perm_dict in permissions_data:
			perm_row = doctype_doc.append("permissions", {
				"role": perm_dict.get("role"),
				"permlevel": perm_dict.get("permlevel", 0),
				"read": perm_dict.get("read", 0),
				"write": perm_dict.get("write", 0),
				"create": perm_dict.get("create", 0),
				"delete": perm_dict.get("delete", 0),
				"submit": perm_dict.get("submit", 0),
				"amend": perm_dict.get("amend", 0),
				"report": 0,
				"export": 1,
				"print": 1,
				"email": 1,
				"share": 1,
			})
		
		# Save DocType
		doctype_doc.save(ignore_permissions=True)
		frappe.db.commit()
		print("✓ Permissions set for Reno Order DocType")
	except Exception as e:
		print(f"✗ Error setting permissions: {str(e)}")
		frappe.log_error(f"Permission setup failed: {str(e)}", "Permission Setup")
