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

## Database & Performance (Part 10)

**Report:** Monthly Reno Order Value grouped by Status, last 12 months.

```sql
SELECT
    DATE_FORMAT(transaction_date, '%Y-%m') as month,
    status,
    SUM(grand_total) as total_value
FROM `tabReno Order`
WHERE transaction_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
GROUP BY DATE_FORMAT(transaction_date, '%Y-%m'), status
ORDER BY month DESC, status
```

Tested against 100,033 real rows (generated for this test).

**EXPLAIN before any index:**
```
type: ALL | possible_keys: None | key: None | rows: 99244
Extra: Using where; Using temporary; Using filesort
```
Full table scan - every row is read to evaluate the WHERE clause.

**Optimization:** added a composite index via
`reno_order/patches/008_add_reno_order_perf_index.py`:
```python
frappe.db.add_index("Reno Order", ["transaction_date", "status"],
                     index_name="transaction_date_status_index")
```

**EXPLAIN after the index, same 12-month query:**
```
type: ALL | possible_keys: transaction_date_status_index | key: None | rows: 99060
```
The optimizer saw the index but chose **not** to use it - because a 12-month
window against ~18 months of data still matches roughly two-thirds of the
table, and for MariaDB a full sequential scan is cheaper than an index
range-scan plus row lookups when that large a fraction of rows will be
read anyway.

**EXPLAIN for a narrower, more selective query** (last 30 days instead of
12 months) against the same table/index:
```
type: range | key: transaction_date_status_index | rows: 11480
Extra: Using index condition; Using temporary; Using filesort
```
Here the index **is** used - rows scanned drops from ~99k to ~11.5k.

**Why this matters / what I'd explain in the interview:**
- **Why this index:** `transaction_date` is the WHERE-clause filter column
  and the natural date-range predicate; `status` is appended because it is
  the GROUP BY column, letting a covering-ish scan avoid extra lookups for
  the status value.
- **When an index helps:** when the query is *selective* - it will only
  touch a small fraction of the table (as shown by the 30-day query above).
- **When an index can hurt:** write overhead (every INSERT/UPDATE must also
  maintain the index) and disk/memory usage, and - as seen directly above -
  a low-selectivity query gets *no* benefit from it, so indexing every
  column "just in case" is a real cost with no guaranteed payoff.
- **How to safely introduce an index on production:** use
  `frappe.db.add_index()` in a patch (idempotent - re-running is a no-op)
  rather than a raw `ALTER TABLE`, run it during a low-traffic window,
  and prefer InnoDB's online DDL (`ALGORITHM=INPLACE, LOCK=NONE`, which
  MariaDB uses by default for secondary index creation) so the table is not
  locked for writes while the index builds. On a very large table, monitor
  replica lag if using replication, since the index build also has to
  replay on replicas.

## CI/CD

`.github/workflows/ci.yml` runs on every push/PR to `main`/`develop`:
Code Push -> spins up MariaDB + Redis service containers -> builds a fresh
bench and installs Frappe/ERPNext/Reno Order -> creates a test site ->
`bench run-tests --app reno_order` -> reports pass/fail.

**Extending to Development -> Staging -> Production:**
- Add environment-scoped jobs that only run on specific branches/tags:
  `develop` push -> auto-deploy to a Development server; a tag like `v*` or
  merge to a `staging` branch -> deploy to Staging after CI passes; a manual
  `workflow_dispatch` approval gate (GitHub Environments with required
  reviewers) -> deploy to Production. Each environment gets its own secrets
  (`STAGING_SSH_KEY`, `PROD_SSH_KEY`, etc.) stored in GitHub Environment
  secrets, never in the workflow file itself.
- The deploy step itself would SSH into the target bench and run
  `bench get-app`/`git pull` + `bench --site <site> migrate` +
  `bench build`, then restart supervisor/gunicorn - the same commands used
  manually today, just automated and gated by environment approval.

**Rollback strategy if a production deployment fails:**
- Because Frappe migrations are mostly additive (new fields/doctypes) and
  patches are idempotent (see Part 9), the safest rollback is: redeploy the
  previous known-good git commit/tag and run `bench migrate` again - Frappe
  does not require an explicit "down" migration for additive schema changes.
- For a schema change that genuinely cannot roll forward safely, restore
  the pre-deployment database backup (`bench --site <site> backup` should
  always run immediately before any production migration) and redeploy the
  previous release tag.
- Keep deployments tagged (`v1.2.0`, etc.) so "rollback" is simply
  "redeploy tag N-1" rather than trying to hand-reverse specific commits.

## Status by part

| Part | Status |
|---|---|
| 1. Custom App & Reno Order | ✅ Implemented & tested |
| 2. Workflow, Permissions & Automation | ✅ Implemented & tested |
| 3. ERPNext Integration | ✅ Implemented & tested |
| 4. Manufacturing Scenario | ✅ Demonstrated via standard ERPNext config |
| 5. Buying Scenario | ✅ Demonstrated via standard ERPNext config |
| 6. REST API / Mobile Integration | ✅ Implemented & tested |
| 7. Third-Party Integration | ❌ Not implemented - see Known Limitations |
| 8. Background Processing | ❌ Not implemented - see Known Limitations |
| 9. Data Migration / Patch | ✅ Implemented & tested |
| 10. Database & Performance | ✅ Implemented & tested |
| 11. Permissions | ✅ Implemented & tested |
| 12. Client-Side Development | ✅ Implemented & tested |
| 13. HRMS Debugging Scenario | ✅ Written analysis - `docs/written-answers.md` |
| 14. Debugging Scenario | ✅ Written analysis - `docs/written-answers.md` |
| 15. Testing | ⚠️ Partial - core logic covered, not exhaustive |
| 16. Git & Code Quality | ✅ Implemented |
| 17. CI/CD | ✅ Implemented - `.github/workflows/ci.yml` |
| 18. Production & Server Knowledge | ✅ Written answers - `docs/written-answers.md` |

## Known limitations

Given the assignment's time constraints, the following are intentionally
not implemented in this submission, in order of priority given to the core
flow (Parts 1-3, 6, 9, 11, 12) over the remaining parts:

- **Part 7 (Third-Party Integration) & Part 8 (Background Processing)** -
  not implemented. Approach would be: a mock external API called via
  `frappe.enqueue()` on a short queue, with retry via `frappe.enqueue(...,
  retry=...)` or manual retry bookkeeping, and a `Reno Order` child log
  table to prevent duplicate processing.
- **Part 15 (automated test coverage)** is partial - core calculation and
  permission logic covered, API and patch tests not yet added.

These are documented here rather than silently skipped, per the assignment's
own instruction to "clearly document assumptions."
