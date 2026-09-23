# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe

BATCH_SIZE = 1000


def execute():
    """Backfill Order Type = 'Standard' on existing Reno Orders that have a
    blank value, after Order Type became a mandatory field.

    Safety:
    - Only touches rows where order_type IS NULL or '' - never overwrites
      an existing value, so it is safe to run on a live production table.
    - Idempotent - running it again finds zero matching rows and does nothing.
    - Batched in chunks of BATCH_SIZE with a commit after each batch, instead
      of one giant UPDATE, so InnoDB does not hold row locks on the whole
      ~50,000 row table for the duration of a single long transaction. This
      keeps other concurrent reads/writes on Reno Order from being blocked
      or queued behind this migration.
    """
    if not frappe.db.exists("DocType", "Reno Order"):
        return

    total_updated = 0

    while True:
        rows = frappe.db.sql(
            """
            SELECT name FROM `tabReno Order`
            WHERE order_type IS NULL OR order_type = ''
            LIMIT %s
            """,
            (BATCH_SIZE,),
            as_dict=True,
        )

        if not rows:
            break

        names = [row.name for row in rows]

        frappe.db.sql(
            """
            UPDATE `tabReno Order`
            SET order_type = 'Standard'
            WHERE name IN %(names)s
            """,
            {"names": names},
        )

        frappe.db.commit()
        total_updated += len(names)

    frappe.logger().info(f"[reno_order] Backfilled order_type on {total_updated} Reno Order(s)")
