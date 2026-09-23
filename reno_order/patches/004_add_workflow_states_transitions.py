import frappe

def execute():
	"""Add Workflow States and Transitions to Reno Order Workflow"""
	
	try:
		# Get the workflow document
		workflow = frappe.get_doc("Workflow", "Reno Order")
		
		# Clear existing states and transitions
		workflow.states = []
		workflow.transitions = []
		
		# Define states with their properties
		states = [
			{"state": "Draft", "doc_status": 0, "allow_edit": 1},
			{"state": "Confirmed", "doc_status": 1, "allow_edit": 0},
			{"state": "In Production", "doc_status": 1, "allow_edit": 0},
			{"state": "Ready for Installation", "doc_status": 1, "allow_edit": 0},
			{"state": "Installed", "doc_status": 1, "allow_edit": 0},
			{"state": "Closed", "doc_status": 1, "allow_edit": 0},
			{"state": "Cancelled", "doc_status": 2, "allow_edit": 0},
		]
		
		# Add states to workflow
		print("Adding Workflow States:")
		for idx, state_data in enumerate(states, 1):
			workflow.append("states", {
				"state": state_data["state"],
				"doc_status": state_data["doc_status"],
				"allow_edit": state_data["allow_edit"]
			})
			print(f"  {idx}. {state_data['state']} (Doc Status: {state_data['doc_status']}, Allow Edit: {state_data['allow_edit']})")
		
		# Define transitions
		transitions = [
			("Draft", "Confirmed"),
			("Confirmed", "In Production"),
			("In Production", "Ready for Installation"),
			("Ready for Installation", "Installed"),
			("Installed", "Closed"),
			# Allow Cancelled from any state
			("Draft", "Cancelled"),
			("Confirmed", "Cancelled"),
			("In Production", "Cancelled"),
			("Ready for Installation", "Cancelled"),
			("Installed", "Cancelled"),
			("Closed", "Cancelled"),
		]
		
		# Add transitions to workflow
		print("\nAdding Workflow Transitions:")
		for idx, (from_state, to_state) in enumerate(transitions, 1):
			workflow.append("transitions", {
				"state": from_state,
				"next_state": to_state
			})
			print(f"  {idx}. {from_state} → {to_state}")
		
		# Save workflow
		workflow.save(ignore_permissions=True)
		frappe.db.commit()
		print("\n✓ Workflow States and Transitions added successfully!")
		print(f"✓ Total States: {len(states)}")
		print(f"✓ Total Transitions: {len(transitions)}")
		
	except Exception as e:
		print(f"✗ Error: {str(e)}")
		frappe.log_error(f"Workflow setup failed: {str(e)}", "Workflow Setup")
