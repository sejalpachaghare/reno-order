# Written Answers - Parts 13, 14, 18

These three parts ask for analysis and explanation rather than new
application code, per the assignment brief.

---

## Part 13 - HRMS Debugging Scenario

**Symptom:** A mid-year employee receives an incorrect prorated allocation
for an event-based leave (Maternity / Paternity / Marriage), which should
be a fixed entitlement regardless of joining date.

### Root-cause analysis

Frappe HRMS grants leave through a **Leave Policy Assignment**: HR assigns a
Leave Policy (which lists each Leave Type with its annual entitlement) to an
employee for a period (`effective_from` / `effective_to`). When that
assignment is submitted, it creates one **Leave Allocation** per Leave Type
in the policy.

The proration logic lives in that allocation step, not in the individual
Leave Type. When the employee's Date of Joining falls **after** the policy
period's `effective_from`, the assignment computes:

```
new_leaves_allocated = annual_allocation * (remaining_days_in_period / total_days_in_period)
```

This formula is applied **uniformly to every Leave Type included in the
policy** - it does not distinguish between an *earned/accrual-style* leave
(Annual Leave, which genuinely should scale with how much of the year the
employee has actually worked) and a *fixed-entitlement/event-based* leave
(Maternity, Paternity, Marriage), which is a one-time benefit tied to a life
event, not to tenure within the period. So a Marriage Leave entitlement of,
say, 3 days gets silently reduced to a fraction of 3 days for a mid-year
joiner, which is incorrect - the employee is still entitled to the full 3
days if/when they get married, day one of employment.

### Relevant ERPNext / Frappe logic

- `Leave Policy Assignment` doctype and its allocation-creation logic
  (`grant_leave_alloc_for_employee` / the period-based proration
  calculation in `hrms/hr/doctype/leave_policy_assignment`).
- `Leave Type` doctype - notably it has no built-in "exempt this leave type
  from date-of-joining proration" flag; proration is a property of *how the
  allocation is created*, not of the Leave Type record itself.
- `Leave Allocation` doctype - the actual record that stores the granted
  days per employee per leave type per period.

### Proposed solution

**Preferred - configuration/process fix, no code:** split the Leave Policy
so that event-based leave types (Maternity, Paternity, Marriage) are **not**
included in the Leave Policy that goes through the prorated Leave Policy
Assignment flow. Instead, HR creates a **separate, direct Leave Allocation**
for those leave types with the full fixed entitlement, at the point the
employee joins (or when the policy requires it) - bypassing the
period-proration math entirely, since a direct Leave Allocation record is
not computed by the assignment's date-of-joining formula.

**If a code-level fix is genuinely wanted** (e.g. to keep everything under
one Leave Policy for administrative simplicity): add a `doc_events` hook in
**our own custom app** (not in HRMS core) on `Leave Policy Assignment`'s
`on_submit`, that re-corrects the `new_leaves_allocated` value on any
created `Leave Allocation` whose Leave Type is not `is_earned_leave` - i.e.
for fixed/event-based types, reset the allocated days back to the Leave
Policy's full annual figure instead of the prorated one. This is a hook,
not a core-code edit, so it respects "avoid modifying ERPNext/Frappe core
code."

### Configuration vs customization

Configuration alone (splitting the Leave Policy / allocating fixed leaves
separately) fully solves this **without any code**. A customization is only
justified if the business insists on a single unified Leave Policy
containing both types of leave - in which case the small doc_event hook
above is the minimal, core-safe fix.

### Test cases covering the fix

1. Employee joins mid-period (e.g. policy Jan-Dec, employee joins Jul 1) →
   Annual Leave allocation is prorated to ~6/12 of the annual figure.
2. Same employee, same assignment → Maternity/Paternity/Marriage Leave
   allocation equals the **full** fixed entitlement, not prorated.
3. Employee joins exactly at the policy period's start date → both leave
   categories get their full entitlement (baseline, unaffected case).
4. Employee's Leave Policy Assignment period does not align with the
   default fiscal year (custom period) → fixed-leave-type allocations are
   still full entitlement regardless of period boundaries.

---

## Part 14 - Debugging Scenario

**Symptom reported:** "Sometimes when we mark an order as Installed, the
page keeps loading and eventually shows an error. However, sometimes the
downstream transaction is still created."

This matches, almost exactly, two real bugs found and fixed while building
this submission (see `CHANGELOG.md`) - so the analysis below is grounded in
what actually happened, not hypothetical.

### How I would investigate this

1. **Reproduce first** - mark a test order Installed and watch both the
   browser network tab (does the request hang, timeout, or return a 500?)
   and the server response body.
2. **Check the Error Log doctype** (`frappe.log_error` writes here
   automatically for any unhandled exception) - filter by recent
   timestamps around when the user reported the issue.
3. **Check the actual state of the Reno Order and its linked documents**
   directly (`sales_order`, `delivery_note`, `sales_invoice` fields, and
   each linked document's own `docstatus`) to see exactly how far the
   automation chain got before it failed.
4. **Check server-side logs** - in a bench setup, `bench --site <site>
   console` plus the site's `logs/` directory (`web.log`, `worker.log`),
   or in production, `journalctl`/supervisor logs for the gunicorn workers
   and the RQ worker processes handling background jobs.

### Suspected root cause (based on what we actually hit)

The Reno Order automation chain (Sales Order -> Delivery Note -> Sales
Invoice) runs **synchronously, inside the same HTTP request** as the
workflow transition that marks the order Installed. Two concrete failure
patterns produce exactly this symptom:

1. **Partial commit, then a later step fails.** `create_sales_order()`
   calls `frappe.db.commit()` after successfully creating the Sales Order.
   If a *later* step in the same request (e.g. Sales Invoice creation)
   then raises an exception, the request as a whole returns an error to
   the browser (page "keeps loading and eventually shows an error") - but
   the Sales Order from the earlier, already-committed step **remains
   persisted**. This is exactly "sometimes the downstream transaction is
   still created" despite the user seeing an error.
2. **A bug inside the error-handling path itself.** We hit this for real:
   `frappe.log_error(message, title="...")` was being called with a long
   string as the positional `title` argument, which exceeds Frappe's
   140-character title limit and raises a *second* exception while trying
   to log the *first* one - masking the real error and making the failure
   look intermittent/mysterious rather than a clear, attributable bug.
   Similarly, ERPNext's own `account_perm_check()` in the accounts module
   raised a permission error for certain users (e.g. Site Supervisor)
   partway through Sales Invoice creation, after the Sales Order/Delivery
   Note had already been created and committed in earlier steps.

Both are consistent with "intermittent" from the user's point of view: the
failure only shows up for specific users (permission-dependent) or specific
error messages (length-dependent), not consistently.

### The fix (addresses duplicate transaction creation directly)

1. Every creation step (`create_sales_order`, `create_delivery_note`,
   `create_sales_invoice`) checks `not self.get(<link_field>)` before
   creating anything, so **retrying** the same transition (user re-clicks,
   or the doc gets saved again) never creates a second Sales
   Order/Delivery Note/Invoice for the same Reno Order - this guard was
   already in place and is what actually prevents duplicates on retry.
2. Fixed the two real bugs above (`log_error` title length, and running
   downstream creation via an `as_system_user()` context so ERPNext's
   account permission checks don't block it) so that a failure in one step
   no longer masks itself as a confusing, unattributable error - it now
   logs a clear, short-titled Error Log entry and the user sees a specific
   failure message rather than a generic hang-then-error.
3. Going forward, the state-driven design itself (SO at Confirmed, DN at
   Ready for Installation, SI at Installed - see Part 3) reduces blast
   radius: each step now happens in its own, later request (its own
   workflow transition), rather than all three chained in a single
   request, so a failure at the SI step can no longer also implicate the
   SO/DN step of the *same* request - they already succeeded and were
   committed in a prior request/transition.

---

## Part 18 - Production & Server Knowledge

### Frappe Cloud

| Aspect | How it works |
|---|---|
| Application deployment | Push to the connected git repo -> Frappe Cloud builds a new bench image with your app(s), runs it through a staging/deploy pipeline, and rolls it out to the site(s) on that bench with minimal downtime. |
| Backups | Automatic scheduled backups (database + files) are taken and stored offsite; on-demand backups can be triggered from the dashboard before risky changes. |
| Logs | Available directly in the dashboard per site - web request logs, background job logs, and error logs, without needing SSH access. |
| Scheduler / workers | Managed automatically - Frappe Cloud runs the scheduler and background workers for you as part of the bench; you don't manually configure supervisor. |
| Site configuration | Managed through the dashboard (`site_config.json`-equivalent settings, environment variables, common site config) rather than editing files directly on a server. |

### Self-hosted ERPNext - role of each component

| Component | Role |
|---|---|
| **Nginx** | Reverse proxy / web server in front of the app - serves static files directly, proxies dynamic requests to Gunicorn, handles SSL termination. |
| **Gunicorn** | WSGI application server running the actual Frappe Python web workers that handle HTTP requests. |
| **Supervisor / process manager** | Keeps Gunicorn, the RQ background workers, and the scheduler process running - restarts them if they crash, manages them as long-running services. |
| **Redis** | Two roles: `redis_cache` for caching (sessions, cached documents/queries) and `redis_queue` as the message broker for background jobs (RQ). |
| **MariaDB** | The primary relational database - stores all DocType data. |
| **Workers** | Background job processors (RQ workers) that pick up queued jobs (`frappe.enqueue()` calls, scheduled tasks, long-running processing) off Redis queues and execute them outside the web request cycle. |
| **Scheduler** | A process that periodically enqueues scheduled tasks (`hooks.py: scheduler_events`) - e.g. our daily `flag_overdue_installations` job - onto the worker queues at the configured interval. |

### Troubleshooting

| Symptom | Likely cause / first checks |
|---|---|
| **502 Bad Gateway** | Nginx can't reach Gunicorn - check if Gunicorn workers are actually running (`supervisorctl status`), check Gunicorn's own error log, restart via supervisor if it crashed. |
| **Worker queue backlog** | Too many jobs enqueued relative to worker capacity, or a slow/stuck job blocking a queue - check `bench --site <site> console` -> RQ queue length, check for a single long-running job hogging a worker, consider adding more worker processes or moving heavy jobs to a `long` queue. |
| **Scheduler not running** | Check `bench doctor` / supervisor status for the scheduler process; check if `disable_scheduler` got accidentally set in site config; check scheduler logs for a crash loop. |
| **High CPU usage** | Identify the process (web worker vs background worker vs MariaDB) via `top`/`htop`; often caused by an inefficient report/query running repeatedly, or too many concurrent Gunicorn workers for available cores. |
| **Slow MariaDB queries** | Enable/check the slow query log, run `EXPLAIN` on the offending query (as done for Part 10), look for missing indexes or a query doing a full table scan on a large table. |
| **Disk full** | Check `df -h`; common culprits are unrotated logs, accumulated old backups in the `private/backups` folder, or unpruned Redis/queue data - clean up and set up log rotation / backup retention policy. |
| **Failed migration** | Check the migration error output directly (it names the failing patch/DocType); if a patch is not idempotent and partially applied, may need to manually inspect DB state before re-running `bench migrate` - this is exactly why Part 9's patch was written to be idempotent and batched. |
