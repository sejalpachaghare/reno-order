# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""Third-party integration (Part 7) + background processing (Part 8).

Simulates pushing a confirmed Reno Order's customer to an external CRM.
The external call is mocked against https://httpbin.org (a public HTTP
testing service) so this is runnable without a real CRM account, while
still exercising a real HTTP request/response cycle, real timeouts and
real failures - not a plain time.sleep() stand-in.
"""

import time

import frappe
from frappe.utils.password import get_decrypted_password
import requests

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = [2, 4, 8]
REQUEST_TIMEOUT = 20  # seconds - the brief says the external API can take 10-20s


def queue_crm_sync(reno_order_name):
    """Enqueue the CRM sync as a background job so a normal Reno Order
    save/submit never waits on the external API.

    Duplicate protection has two layers:
    1. Document-level: skip entirely if this Reno Order is already
       Queued or Synced.
    2. Queue-level: `deduplicate=True` + a job_id derived from the Reno
       Order name means RQ itself will refuse to queue a second job while
       one with that id is already queued or running.
    """
    current_status = frappe.db.get_value("Reno Order", reno_order_name, "crm_sync_status")
    if current_status in ("Queued", "Synced"):
        return

    frappe.db.set_value("Reno Order", reno_order_name, "crm_sync_status", "Queued")

    frappe.enqueue(
        "reno_order.reno_order.integrations.crm_sync.sync_customer_to_crm",
        queue="long",
        job_id=f"crm-sync-{reno_order_name}",
        deduplicate=True,
        enqueue_after_commit=True,
        reno_order_name=reno_order_name,
    )


def sync_customer_to_crm(reno_order_name):
    """Background job body - runs on the 'long' queue, not inline with any
    web request. Retries with backoff, logs every attempt, and never
    raises past the job boundary (a failed sync should not crash the
    worker or retry forever)."""
    logger = frappe.logger("reno_order.crm_sync", allow_site=True)

    # Re-check inside the job too, in case it somehow still ran twice
    if frappe.db.get_value("Reno Order", reno_order_name, "crm_sync_status") == "Synced":
        logger.info(f"{reno_order_name} already synced, skipping duplicate run")
        return

    doc = frappe.get_doc("Reno Order", reno_order_name)
    settings = frappe.get_doc("Reno Order Settings", "Reno Order Settings")
    base_url = (settings.crm_webhook_url or "https://httpbin.org").rstrip("/")

    # Credentials are stored encrypted (Password fieldtype) and only ever
    # decrypted here, in memory, for the outbound request - never logged,
    # never returned to the client.
    api_key = get_decrypted_password(
        "Reno Order Settings", "Reno Order Settings", "crm_api_key", raise_exception=False
    )
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    payload = {
        "reno_order": doc.name,
        "customer": doc.customer,
        "grand_total": doc.grand_total,
        "status": doc.status,
    }

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(f"CRM sync attempt {attempt}/{MAX_RETRIES} for {reno_order_name}")
            response = requests.post(
                f"{base_url}/post",
                json=payload,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()

            frappe.db.set_value("Reno Order", reno_order_name, "crm_sync_status", "Synced")
            frappe.db.commit()
            logger.info(f"CRM sync succeeded for {reno_order_name} on attempt {attempt}")
            return

        except requests.exceptions.Timeout as e:
            last_error = e
            logger.warning(f"CRM sync timed out (attempt {attempt}) for {reno_order_name}: {e}")
        except requests.exceptions.RequestException as e:
            last_error = e
            logger.warning(f"CRM sync request failed (attempt {attempt}) for {reno_order_name}: {e}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SECONDS[attempt - 1])

    frappe.db.set_value("Reno Order", reno_order_name, "crm_sync_status", "Failed")
    frappe.db.commit()
    frappe.log_error(
        title="CRM Sync Failed",
        message=(
            f"Reno Order {reno_order_name} failed to sync to CRM after "
            f"{MAX_RETRIES} attempts. Last error: {last_error}"
        ),
    )
