# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added
- **Part 1** - Reno Order DocType with header fields, `Reno Order Item` child
  table, server-side calculation of line amounts / total / discount / grand
  total, business rule validation (negative qty/rate, installation date
  before order date), and `create_sales_order` with duplicate prevention.
- **Part 2** - Workflow (Draft -> Confirmed -> In Production -> Ready for
  Installation -> Installed -> Closed, plus Cancelled), role-based access
  (Sales User, Sales Manager, Production User, Site Supervisor, Accounts
  User), discount-approval-threshold enforcement, daily scheduled job
  flagging overdue installations, and a Query Report ("Overdue
  Installations") for reporting on the same.
- **Part 3** - Full Reno Order -> Sales Order -> Delivery Note -> Sales
  Invoice integration, state-driven (each document created at the workflow
  state where it actually belongs), reference fields linking back to each
  standard document, and cascade cancellation (SI -> DN -> SO) on Reno Order
  cancel.
- **Part 4 / 5** - Manufacturing (BOM/Work Order/Job Card) and Buying
  (Material Request -> ... -> Purchase Invoice) scenarios demonstrated via
  standard ERPNext configuration, no custom code.
- **Part 6** - REST API (`reno_order/api.py`) for the Site Supervisor mobile
  app: `update_installation_status`, `add_installation_remarks`, and site
  photo attachment via Frappe's standard file upload endpoint. Token-based
  authentication, workflow-engine-driven transition validation, and
  elevated-but-scoped automation via an `as_system_user` context manager for
  the downstream Sales Invoice creation.
- **Part 9** - Idempotent, batched data-migration patch backfilling
  `order_type` to "Standard" on existing blank records.
- **Part 11** - Server-side permission enforcement: row-level via
  `permission_query_conditions`, field-level via DocType `permlevel` so
  Site Supervisor cannot modify Customer/Discount/Totals/Rate even via API.
- **Part 12** - "Mark as Installed" custom button (visible only when
  appropriate), dynamic Contact Person/Address filters by Customer, friendly
  client-side discount warning.
- **Part 7 / 8** - Third-party CRM sync (`integrations/crm_sync.py`) queued
  via `frappe.enqueue` on the `long` queue from `on_submit`, so Confirming
  a Reno Order never blocks on the external call. Bearer-token auth, 20s
  timeout, 3 retries with exponential backoff, encrypted credential storage
  (`Password` fieldtype), and duplicate-processing protection at both the
  document-status level and via `deduplicate=True` + `job_id` on the queue
  itself.
- **Part 15** - Automated tests covering total/discount calculation
  (including a manipulated `grand_total` being ignored), invalid
  installation date, negative qty/rate, discount-approval enforcement,
  Sales Order creation and duplicate-prevention, Sales Invoice creation
  exactly once at Installed, an unauthorized mobile API call being
  rejected, row-level permission visibility, and the `007_backfill_order_type`
  patch's idempotency.

### Fixed
- `on_update` only fires on the initial submit; later workflow transitions
  on an already-submitted document go through `on_update_after_submit`
  instead - added that hook so every transition (not just the first) drives
  the Sales Order/Delivery Note/Sales Invoice chain.
- `frappe.log_error(message, title=...)` was being called with a long string
  as the positional `title` argument, which exceeds Frappe's 140-character
  title limit and raised a secondary error that masked the original one.
  Fixed to pass `title=` (short) and `message=` (full traceback) explicitly.
- Reno Order's `sales_order`/`delivery_note` link fields were being set
  *after* calling `.submit()`, so the `on_submit` hook that looked the
  parent up by that field could never find it. Fixed by linking before
  submit.
- ERPNext's `account_perm_check` in the accounts module performs a hard
  permission check that `ignore_permissions=True` on `insert()` does not
  bypass. Added an `as_system_user()` context manager so downstream
  document creation triggered by a less-privileged role (e.g. Site
  Supervisor marking an order Installed) runs with full rights, without
  granting that role direct Sales Invoice/Account access.
- Journal Entry creation for a Receivable account requires `party_type`/
  `party` to be set - added to the installation accounting entry.
- Workflow was left `is_active = 0` from an earlier iteration, silently
  disabling all workflow transitions. Re-enabled and fixed an invalid
  Draft -> Cancelled transition (cannot cancel a document before it is
  submitted).
