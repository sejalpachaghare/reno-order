# Copyright (c) 2026, Sejal Pachaghare and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class RenoOrderSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		discount_approval_threshold: DF.Currency
	# end: auto-generated types

	_DOCTYPE_NAME = "Reno Order Settings"
