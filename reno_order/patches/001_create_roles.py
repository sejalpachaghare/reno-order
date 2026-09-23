import frappe

def execute():
	"""Create roles for Reno Order workflow"""
	roles = [
		"Sales User",
		"Sales Manager", 
		"Site Supervisor",
		"Production User",
		"Accounts User"
	]
	
	for role_name in roles:
		if not frappe.db.exists("Role", role_name):
			role = frappe.new_doc("Role")
			role.role_name = role_name
			role.insert(ignore_permissions=True)
			print(f"Created role: {role_name}")
		else:
			print(f"Role already exists: {role_name}")
