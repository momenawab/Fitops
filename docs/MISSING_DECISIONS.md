# FitOps — Missing Decisions Registry

**This file is the single centralized registry for business/architecture decisions that are
intentionally left unresolved.**

> **Binding rule:** If an implementation encounters a decision listed in this file, **stop and ask
> for an explicit decision rather than guessing.** Do not default it, do not infer it from
> surrounding rules, and do not resolve it by choosing "the reasonable option".

Nothing in this file is a decision. It is a record of what has **not** been decided, so that the gap
stays visible instead of being silently filled during implementation.

## Scope and status

- Documentation baseline: **Architecture v1.2.1**.
- These items are already marked as unresolved in the authoritative documents; this file centralizes
  them. The authoritative documents remain the source of truth for everything that *has* been
  decided.
- Decision IDs (`B24`–`B27`) are preserved from Database & Authentication Architecture §22G.
- Resolving an item means: the user makes the decision → the authoritative document is updated →
  the item is removed from this registry.

---

## B24 — Permanent archive retention duration

**Title:** Permanent archive retention duration

**Current known rule:**
When a Workspace is cleaned up after 30 days in `EXPIRED`, the data is archived rather than
destroyed. A `WorkspaceArchive` record with status `AVAILABLE` is retained so a returning Coach can
be offered restoration. The archive is not an active tenant and is not reachable through normal
application routes. (DB §22H)

**What remains undecided:**
How long an `AVAILABLE` `WorkspaceArchive` is kept, and whether it is ever purged at all. No
retention period has been specified and none may be silently chosen.

**Affects:**
`workspaces` app (`WorkspaceArchive`), the retention lifecycle job, storage/backup planning, and any
data-retention or privacy commitments made to Coaches and Clients.

**Becomes relevant:**
Blueprint Story 22.10b / 22.10c (Epic 22). The archive can be created without deciding this; the
decision is required before any purge behavior — or any promise about how long data is kept — is
implemented.

**Source:** Database & Authentication Architecture §22G (B24), §22H.

---

## B25 — Archive restoration scope

**Title:** Scope of "the supported recovery rules"

**Current known rule:**
A returning Coach with an available archive is shown an explicit choice between **Restore Previous
Data** and **Start Fresh**. Choosing restore reinstates the previous Workspace "according to the
supported recovery rules" and marks the archive `RESTORED`. Restoration never happens automatically,
and the archive is never exposed as an active Workspace. (DB §22H, API §6)

**What remains undecided:**
Precisely which records and data a restore reinstates — for example clients, memberships, orders,
subscriptions, plans, check-ins, and progress media. The phrase "supported recovery rules" is
deliberately undefined and must not be inferred.

**Affects:**
`POST /workspace/archive/restore`, the `workspaces` app restoration path, and every domain whose
records could be in scope (`accounts` memberships, `commerce`, `coaching`, `applications`, media
storage).

**Becomes relevant:**
Blueprint Story 22.10c (Epic 22), at the point the restore operation is implemented. The
archive-detection half of the flow (`GET /workspace/archive`) does not depend on it.

**Source:** Database & Authentication Architecture §22G (B25), §22H; API Specification §6.

---

## B26 — Long-expired multi-period reactivation

**Title:** Long-expired multi-period reactivation

**Current known rule — do not change it:**
Renewal anchoring is approved and stands as written: on approval, the new period runs from the
previous `renewal_date` to that date + 30 days, never from the payment or approval date. Late
payment never grants bonus days. This applies identically to renewal after `PAST_DUE` and to
reactivation from `EXPIRED`. (DB §22E)

**What remains undecided:**
The behavior when a subscription has been unpaid across **multiple** billing periods. Under the
anchoring rule a single approved payment may advance the period to an end date that is still in the
past, returning the subscription to `PAST_DUE`. Whether such a Coach pays once per elapsed period,
or the subscription re-anchors to a new date, is not decided.

**Do not invent a new reactivation rule, and do not silently change the renewal anchor.**

**Affects:**
`billing` app approval transaction, `PlatformSubscription` period advancement, the scheduled status
transition job, and the reactivation path.

**Becomes relevant:**
Blueprint Story 22.6 (approval) and Story 22.9 (status transitions). In practice the reachable
window is bounded by §22H: after 30 days in `EXPIRED` the Workspace leaves the operational system.

**Source:** Database & Authentication Architecture §22G (B26), §22E unresolved edge case.

---

## B27 — CANCELLED subscription cleanup lifecycle

**Title:** Terminal `CANCELLED` lifecycle

**Current known rule:**
Cancellation is cancel-at-period-end: `cancel_at_period_end = true`, the paid period runs to its
end, then the subscription enters `CANCELLED` and `cancelled_at` is set. While `CANCELLED`, Coach
access is restricted and the Client Portal remains accessible. The 30-day retention window,
Workspace cleanup and archiving are defined for `EXPIRED`. (DB §22E, §22F, §22H)

**What remains undecided:**
Whether a `CANCELLED` subscription ever enters the same 30-day retention, cleanup and archive
lifecycle as `EXPIRED` — and if so, when its clock starts. As documented, `CANCELLED` is terminal
with no defined cleanup path, which leaves cancelled Workspaces operational indefinitely.

**Affects:**
The retention lifecycle job, `WorkspaceArchive` creation, long-term Coach and Client access after
cancellation, and storage growth.

**Becomes relevant:**
Blueprint Story 22.10b (Epic 22), when the retention window job is implemented and must decide which
statuses it evaluates.

**Source:** Database & Authentication Architecture §22G (B27), §22H.

---

## Also open in the authoritative documentation

The following is explicitly marked open in an approved document but is **deployment configuration**,
not a business or architecture decision. It carries no `B` identifier in the source documents and is
listed here only for completeness.

### SMTP provider

**Current known rule:**
Email is sent through Django's email backend abstraction with an SMTP provider. Host, port,
credentials, TLS settings and from-address come from environment variables. Application code must
never use a provider-specific SDK.

**What remains undecided:**
Which SMTP provider is used. It is deliberately unselected.

**Affects:**
Deployment configuration only. No model, endpoint, or application code depends on the choice.

**Becomes relevant:**
At deployment. It **blocks no Story** — client OTP, email verification, password reset and
notifications are all implementable against the Django email API without it.

**Source:** Technology Stack, "Still To Decide"; CLAUDE.md §23.

---

## How to use this registry

1. **During planning:** check whether the Story you are about to start touches an item here.
   Blueprint Stories 22.6, 22.9, 22.10b and 22.10c all do.
2. **During implementation:** if you reach a point where one of these decisions would have to be
   made in order to proceed, **stop**. Report which item you hit, what is blocked, and what the
   options are. Do not choose one.
3. **Do everything that does not depend on it.** An unresolved item blocks only the behavior that
   genuinely requires it, not the whole Story.
4. **When a decision is made:** update the authoritative document in the same change, record it in
   the Development Blueprint decision log, and remove the item from this registry.
