# Reno Order

Custom Frappe application for a kitchen renovation platform. Manages the
renovation-specific order lifecycle (Reno Order) while reusing standard
ERPNext transactions (Sales Order, Delivery Note, Sales Invoice, Journal
Entry, Work Order, Purchase flow) wherever possible.

Built for the Savyant Systems Senior ERPNext/Frappe Developer technical
assignment.

## Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app reno_order $URL_OF_THIS_REPO
bench --site your-site install-app reno_order
bench --site your-site migrate
```

`bench migrate` also runs the app's one-time setup patches (roles, workflow,
permissions - see `reno_order/patches.txt`) and the `007_backfill_order_type`
data patch.

## Architecture overview

- **Reno Order** (`reno_order/doctype/reno_order`) is the custom DocType that
  owns the renovation-specific lifecycle: header fields, `Reno Order Item`
  child table, server-side total calculation, discount-approval validation,
  and the workflow state machine (Draft -> Confirmed -> In Production ->
  Ready for Installation -> Installed -> Closed, plus Cancelled).
- **State-driven ERPNext integration**: `on_update` / `on_update_after_submit`
  on Reno Order call `sync_workflow_chain()`, which creates the matching
  standard ERPNext document at the point in the lifecycle where that
  transaction actually belongs:
  - `Confirmed` -> Sales Order (stock reserved)
  - `Ready for Installation` -> Delivery Note (stock actually reduced)
  - `Installed` -> Sales Invoice (accounting entries created)
  Each step links back via `sales_order` / `delivery_note` / `sales_invoice`
  fields on Reno Order, which double as idempotency guards against duplicate
  creation.
- **`on_cancel`** cascades cancellation through Sales Invoice -> Delivery
  Note -> Sales Order in that order, matching ERPNext's own dependency
  direction.
- **`reno_order/api.py`** exposes the whitelisted REST endpoints used by the
  Site Supervisor mobile app (`update_installation_status`,
  `add_installation_remarks`). Site photos reuse Frappe's standard
  `/api/method/upload_file` endpoint - no custom code needed there.
- **`reno_order/tasks.py`** is a daily scheduled job flagging orders whose
  Expected Installation Date has passed without reaching Installed/Closed/
  Cancelled.
- **Permissions** are enforced server-side two ways: row-level visibility via
  a `permission_query_conditions` hook (role-based), and field-level via
  DocType `permlevel` (Site Supervisor's role has no permlevel-1 grant, so
  Customer/Discount/Totals/Rate silently cannot be changed by that role even
  through the API).

## Configuration

- **Discount approval threshold**: `Reno Order Settings` singleton doctype,
  field `discount_approval_threshold` (default 1000). Submission is blocked
  if `discount_amount` exceeds this unless the user has the `approve`
  permission on Reno Order.
- **Company / accounts**: the automation picks the first `Company` record's
  default receivable/income accounts for the installation Journal Entry and
  the auto-generated Sales Invoice.
- **Scheduler**: `flag_overdue_installations` runs daily via
  `hooks.py:scheduler_events`.

## Assumptions

- A single-company setup is assumed for account resolution; a multi-company
  deployment would need Reno Order to carry its own `company` field.
- "Team" for Sales Manager visibility is interpreted as full visibility
  across all Reno Orders (no formal manager-report hierarchy exists in this
  app), consistent with the assignment's "Sales Managers may require broader
  visibility."
- Manufacturing (Part 4) and Buying (Part 5) scenarios are demonstrated using
  100% standard ERPNext functionality (BOM/Work Order/Job Card, and the
  Material Request -> ... -> Purchase Invoice chain) with no custom code, per
  the assignment's explicit instruction not to customize those unnecessarily.

## Testing

Run the app's test suite:

```bash
bench --site your-site run-tests --app reno_order
```

Manual verification steps for the core flow are in the demo video and in
each part's notes below. Key things to check by hand:
- Creating a Reno Order and confirming totals recalculate server-side even
  if a client sends a manipulated `grand_total`.
- Moving a Reno Order through the workflow and watching Sales Order ->
  Delivery Note -> Sales Invoice appear automatically at the right states.
- Cancelling an Installed Reno Order and confirming SI/DN/SO cancel in
  reverse order.
- Calling the mobile API with/without a valid token to see auth enforced.

## Known limitations

Given the assignment's time constraints, the following parts are
intentionally lighter or not yet implemented, in order of priority given to
the core flow (Parts 1-3, 6, 9, 11, 12) over the remaining parts:

- Part 7 (Third-Party Integration) and Part 8 (Background Processing) - not
  yet implemented. Approach would be: a mock external API called via
  `frappe.enqueue()` on a short queue, with retry via `frappe.enqueue(...,
  retry=...)` or manual retry bookkeeping, and a `Reno Order` child log
  table to prevent duplicate processing.
- Part 10 (DB & Performance report) - not yet implemented in this submission.
- Part 13/14 (Debugging scenarios) - answered as written analysis, not code.
- Part 17/18 (CI/CD, Production knowledge) - answered as written explanation.
- Part 15 (automated test coverage) is partial - core calculation and
  permission logic covered, API and patch tests not yet added.

These are documented here rather than silently skipped, per the assignment's
own instruction to "clearly document assumptions."
