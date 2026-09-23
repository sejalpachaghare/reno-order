import frappe

def execute():
	"""Create Reno Order Workflow"""
	
	if frappe.db.exists("Workflow", "Reno Order"):
		print("Workflow already exists")
		return
	
	try:
		# Create workflow directly using database insert
		workflow_doc = frappe.get_doc({
			"doctype": "Workflow",
			"name": "Reno Order",
			"workflow_name": "Reno Order Workflow",
			"document_type": "Reno Order",
			"is_active": 1
		})
		
		# Define states
		states = [
			{"state": "Draft", "doc_status": 0, "allow_edit": 1},
			{"state": "Confirmed", "doc_status": 1, "allow_edit": 0},
			{"state": "In Production", "doc_status": 1, "allow_edit": 0},
			{"state": "Ready for Installation", "doc_status": 1, "allow_edit": 0},
			{"state": "Installed", "doc_status": 1, "allow_edit": 0},
			{"state": "Closed", "doc_status": 1, "allow_edit": 0},
			{"state": "Cancelled", "doc_status": 2, "allow_edit": 0},
		]
		
		for state in states:
			workflow_doc.append("states", state)
		
		# Define transitions
		transitions = [
			{"state": "Draft", "next_state": "Confirmed"},
			{"state": "Confirmed", "next_state": "In Production"},
			{"state": "In Production", "next_state": "Ready for Installation"},
			{"state": "Ready for Installation", "next_state": "Installed"},
			{"state": "Installed", "next_state": "Closed"},
			{"state": "Draft", "next_state": "Cancelled"},
			{"state": "Confirmed", "next_state": "Cancelled"},
			{"state": "In Production", "next_state": "Cancelled"},
			{"state": "Ready for Installation", "next_state": "Cancelled"},
			{"state": "Installed", "next_state": "Cancelled"},
			{"state": "Closed", "next_state": "Cancelled"},
		]
		
		for transition in transitions:
			workflow_doc.append("transitions", transition)
		
		# Save without validation
		workflow_doc.insert(ignore_permissions=True, ignore_links=True, ignore_if_duplicate=True)
		frappe.db.commit()
		print("Workflow created successfully")
	except Exception as e:
		print(f"Error: {e}")
		import traceback
		traceback.print_exc()
