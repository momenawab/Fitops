# FitOps — API Specification v1.2.1

> Version 1.2.1 adds the archive/restoration endpoints (§6) and the explicit Coach-commerce
> payment statuses (§11).
> Version 1.2 adds the approved **FitOps Billing** API (§20A).
> Version 1.1 decisions remain in force and unchanged.
> The product name is **FitOps**. Earlier drafts used the working title "Coaching SaaS".

## Status

This document defines the API surface required for the Phase 1 MVP.

It is intentionally focused on the MVP core loop:

> Acquire → Order → Pay → Activate → Coach → Check-in → Progress → Renew

The API is REST-based and versioned under:

`/api/v1/`

---

# 1. API Conventions

## Request / Response

- JSON for standard requests/responses
- `multipart/form-data` for file uploads
- ISO 8601 timestamps
- UUIDs for public resource identifiers
- Decimal strings for monetary values

## Authentication

Authentication uses Django's built-in session framework with secure HttpOnly session cookies.
CSRF protection applies to all state-changing requests.

### Coach

Email + password → optional TOTP 2FA → session.

### Client

Email → OTP → session.

### Platform Admin

Authenticated user with `platform_role = ADMIN`.

## Tenant Context

The active Workspace is always resolved from the **Workspace slug in the URL/route**.

For Coach dashboard requests, the Coach dashboard routes are Workspace-scoped
(`/{workspaceSlug}/dashboard`, `/{workspaceSlug}/clients`, `/{workspaceSlug}/orders`, and so on).
The backend resolves the Workspace from that slug and must verify that the authenticated Coach has an
active Membership in that Workspace with role `OWNER` or `COACH`.

For Client portal requests, the Workspace slug in the URL identifies the requested tenant. The backend must verify that the authenticated Client has an active Membership in that Workspace.

Workspace-scoped requests carry the slug; the API resolves it to the Workspace and to the caller's
`Membership`, which is also the identity used by Workspace-scoped business records.

The frontend must never be trusted to provide an authoritative `workspace_id`. Clients must never receive or select a list of their memberships through the portal.

All tenant resources must be Workspace-scoped.

---

# 2. Standard Error Format

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Please correct the highlighted fields.",
    "fields": {
      "email": [
        "Enter a valid email address."
      ]
    }
  }
}
```

Common error codes:

- `AUTHENTICATION_REQUIRED`
- `INVALID_CREDENTIALS`
- `INVALID_OTP`
- `OTP_EXPIRED`
- `OTP_RATE_LIMITED`
- `EMAIL_NOT_VERIFIED`
- `TWO_FACTOR_REQUIRED`
- `INVALID_TWO_FACTOR_CODE`
- `PERMISSION_DENIED`
- `NOT_FOUND`
- `VALIDATION_ERROR`
- `CONFLICT`
- `RATE_LIMITED`
- `FILE_TOO_LARGE`
- `UNSUPPORTED_FILE_TYPE`
- `INTERNAL_ERROR`

---

# 3. Pagination

Collection endpoints use:

`?page=1&page_size=20`

Response:

```json
{
  "count": 120,
  "next": "...",
  "previous": null,
  "results": []
}
```

---

# 4. Authentication API

## Coach Registration

### POST `/auth/register`

Creates a Coach account.

Request:

```json
{
  "email": "coach@example.com",
  "password": "StrongPassword123!",
  "first_name": "John",
  "last_name": "Doe"
}
```

Response:

```json
{
  "message": "Account created. Please verify your email.",
  "requires_email_verification": true
}
```

Permissions: Public

---

## Email Verification

### POST `/auth/email/verify`

Request:

```json
{
  "token": "verification-token"
}
```

Permissions: Public

---

## Resend Verification Email

### POST `/auth/email/resend`

Request:

```json
{
  "email": "coach@example.com"
}
```

Permissions: Public

Must avoid account enumeration.

---

## Coach Login

### POST `/auth/login`

Request:

```json
{
  "email": "coach@example.com",
  "password": "StrongPassword123!"
}
```

Possible response:

```json
{
  "authenticated": false,
  "requires_2fa": true
}
```

If 2FA is disabled:

```json
{
  "authenticated": true
}
```

---

## Verify 2FA

### POST `/auth/2fa/verify`

Request:

```json
{
  "code": "123456"
}
```

On success, creates the authenticated session.

---

## 2FA Setup

### POST `/auth/2fa/setup`

Returns the TOTP setup information required by the authenticator app.

Coach-only.

---

## Confirm 2FA Setup

### POST `/auth/2fa/confirm`

Request:

```json
{
  "code": "123456"
}
```

Coach-only.

---

## Disable 2FA

### POST `/auth/2fa/disable`

Requires authenticated Coach and current 2FA verification.

---

## Current User

### GET `/auth/me`

Returns:

- User
- Role
- Email verification state
- 2FA state
- Platform role

Workspace context is resolved separately from the request URL/route and is not inferred as a single global "current Workspace" for multi-workspace users.

---

## Logout

### POST `/auth/logout`

Revokes the current session.

---

## Session Management

Per-session management is **not** part of the MVP.

`GET /auth/sessions` and `POST /auth/sessions/{id}/revoke` are removed from the Phase 1 API surface.
Session termination is covered by `POST /auth/logout`.

"Log out everywhere" may be introduced as a future feature.

---

## Forgot Password

### POST `/auth/password/forgot`

Request:

```json
{
  "email": "coach@example.com"
}
```

Must use a generic response to prevent account enumeration.

---

## Reset Password

### POST `/auth/password/reset`

Request:

```json
{
  "token": "reset-token",
  "password": "NewStrongPassword123!"
}
```

---

# 5. Client Authentication API

## Request Client OTP

### POST `/auth/client/request-code`

Request:

```json
{
  "email": "client@example.com",
  "workspace_slug": "coach-name"
}
```

Always return a generic success response whether or not the account exists.

---

## Verify Client OTP

### POST `/auth/client/verify-code`

Request:

```json
{
  "email": "client@example.com",
  "workspace_slug": "coach-name",
  "code": "482913"
}
```

On success:

- Creates secure Client session
- Returns authenticated state

---

# 6. Workspace API

## Create Workspace

### POST `/api/v1/workspace`

Creates the Coach's first Workspace during onboarding.

Permissions: authenticated Coach without an existing owned Workspace.

Request:

```json
{
  "name": "Bergo Coaching",
  "slug": "bergo",
  "currency": "EGP",
  "timezone": "Africa/Cairo"
}
```

Server-side behavior:

1. Validate and reserve the slug (unique across the platform)
2. Create the `Workspace`
3. Create `Membership(user=request.user, workspace=new_workspace, role=OWNER)`
4. Create the `PlatformSubscription` in `TRIALING` with a 7-day trial, and write the
   `SUBSCRIPTION_CREATED` / `TRIAL_STARTED` billing events (§20A)
5. Record an audit event

Rules:

- The Workspace and the OWNER Membership are created in a single transaction.
- The creator always becomes `OWNER`.
- The slug is the authoritative Workspace context for every Workspace-scoped route afterwards.

---

## Previous Workspace Archive

### GET `/workspace/archive`

Returns the archive summary for the authenticated Coach if a `WorkspaceArchive` with status
`AVAILABLE` exists — previous workspace name, slug and `archived_at` — otherwise an empty result.

Used during onboarding to present the explicit choice:

```text
"Previous coaching data was found."
1. Restore Previous Data
2. Start Fresh
```

Permissions: authenticated Coach. A Coach can only ever see their own archive. The archive is
metadata only — this endpoint never serves archived tenant data, and the archive is never resolvable
as an active Workspace.

---

### POST `/workspace/archive/restore`

Restores the previous Workspace according to the supported recovery rules, producing an operational
Workspace, and marks the archive `RESTORED`.

Rules:

- Restoration happens **only** on this explicit request. Nothing is ever restored automatically.
- The archive itself never becomes the active tenant.
- Audit-logged.

The precise scope of what a restore reinstates is **not yet specified** — see Database &
Authentication Architecture §22G (B25). Do not infer it.

**Start Fresh** requires no dedicated endpoint: it is the existing `POST /api/v1/workspace`, which
leaves the archive untouched.

---

## Get Current Workspace

### GET `/workspace`

Coach-only.

---

## Update Workspace

### PATCH `/workspace`

Request:

```json
{
  "name": "My Coaching",
  "description": "Online coaching",
  "brand_color": "#111111",
  "currency": "EGP",
  "whatsapp_number": "+201000000000",
  "timezone": "Africa/Cairo"
}
```

Owner-only for sensitive workspace settings.

---

## Update Branding

### PATCH `/workspace/branding`

Supports:

- Logo
- Profile image
- Brand color
- Public description

---

## Upload Logo

### POST `/workspace/logo`

`multipart/form-data`

---

## Payment Methods

### GET `/workspace/payment-methods`

Coach/Owner.

---

## Create Payment Method

### POST `/workspace/payment-methods`

Request:

```json
{
  "type": "INSTAPAY",
  "name": "InstaPay",
  "instructions": "Send payment to ...",
  "account_details": "01000000000",
  "is_active": true
}
```

Types:

```text
INSTAPAY
VODAFONE_CASH
BANK_TRANSFER
CUSTOM
```

An optional QR code or image may be attached. When an image is included the request uses
`multipart/form-data` with an `image` field; image handling follows the standard file rules in §21.

Coach/Owner. Payment methods are Workspace-scoped.

---

## Update Payment Method

### PATCH `/workspace/payment-methods/{id}`

Accepts the same fields, including `is_active`. Uses `multipart/form-data` when replacing the image.

---

## Delete Payment Method

### DELETE `/workspace/payment-methods/{id}`

---

## Check-in Schedule

### GET `/workspace/check-in-schedule`

Coach/Owner.

Returns the Workspace check-in schedule.

---

### PATCH `/workspace/check-in-schedule`

Coach/Owner.

Request:

```json
{
  "frequency": "WEEKLY",
  "day_of_week": "MONDAY"
}
```

Frequency values: `WEEKLY`, `BIWEEKLY`.

Phase 1 keeps this configuration simple and Workspace-level. Per-client schedules and custom
cadences are out of Phase 1 scope.

---

# 7. Public Coach Portal API

## Get Public Coach

### GET `/public/coaches/{slug}`

Public.

Returns:

- Coach public profile
- Workspace branding
- Public information
- Active packages

---

## Get Public Packages

### GET `/public/coaches/{slug}/packages`

Public.

---

## Create Client Application

### POST `/public/coaches/{slug}/applications`

Request:

```json
{
  "package_id": "uuid",
  "full_name": "Ahmed Ali",
  "email": "ahmed@example.com",
  "phone": "+201000000000",
  "age": 25,
  "gender": "male",
  "height": 180,
  "weight": 85,
  "goal": "Fat loss",
  "training_experience": "Intermediate",
  "notes": "..."
}
```

Permissions: Public. The endpoint does **not** require an authenticated User — a public application
may originate from an anonymous visitor, and `Application.user_id` is nullable.

Server-side behavior, in one transaction:

1. Resolve the Workspace from the `{slug}` in the URL
2. Validate the package belongs to that Workspace and is active
3. Create the `Application` (status `SUBMITTED`)
4. Create or resolve the global `User` and `ClientProfile`
5. Create the `Membership(role=CLIENT)` for this Workspace if it does not already exist
6. Associate `Application.user_id`
7. Create the **initial Order** for the selected package, with the price and currency taken from
   the Package

The Application and its initial Order must be created consistently and safely; a failure at any
step must not leave an Application without its Order or an Order without its Application.

The ClientProfile itself is not Workspace-scoped. The Order references the Client through the
`Membership` created for this Workspace.

Subsequent purchases by an already-authenticated Client use `POST /orders` (§10) instead.

---

# 8. Package API

## List Packages

### GET `/packages`

Supports:

- Pagination
- Search
- Active/inactive filter

---

## Create Package

### POST `/packages`

Request:

```json
{
  "name": "Pro Coaching",
  "description": "12-week coaching program",
  "price": "3500.00",
  "currency": "EGP",
  "duration_days": 90,
  "features": [
    "Training Plan",
    "Nutrition Plan",
    "Weekly Check-ins"
  ]
}
```

Coach/Owner.

---

## Get Package

### GET `/packages/{id}`

---

## Update Package

### PATCH `/packages/{id}`

---

## Delete/Archive Package

### DELETE `/packages/{id}`

Prefer soft deletion/archive when the package has historical orders.

---

## Activate Package

### POST `/packages/{id}/activate`

---

## Deactivate Package

### POST `/packages/{id}/deactivate`

---

## Duplicate Package

### POST `/packages/{id}/duplicate`

---

# 9. Client API

## List Clients

### GET `/clients`

Supports:

- Search
- Status filter
- Pagination
- Subscription filter

---

## Get Client

### GET `/clients/{id}`

Returns:

- Profile
- Subscription
- Orders
- Assigned plans
- Recent check-ins
- Progress summary

---

## Create Client Manually

### POST `/clients`

Coach/Owner.

Request:

```json
{
  "email": "client@example.com",
  "first_name": "Ahmed",
  "last_name": "Ali",
  "phone": "+201000000000"
}
```

The backend creates or reuses the global `User` and `ClientProfile`, then creates the
`Membership(role=CLIENT)` in the current Workspace. The `ClientProfile` is global and is never
Workspace-scoped.

---

## Update Client

### PATCH `/clients/{id}`

---

## Deactivate Client

### POST `/clients/{id}/deactivate`

---

## Reactivate Client

### POST `/clients/{id}/reactivate`

---

## Client Activity

### GET `/clients/{id}/activity`

Returns relevant client activity such as:

- Orders
- Check-ins
- Plan assignments
- Subscription changes

---

## Client Profile

### GET `/client/profile`

Client-only.

---

## Update Client Profile

### PATCH `/client/profile`

Client-only.

Only client-editable fields may be changed by the Client.

---

# 10. Order API

## List Orders

### GET `/orders`

Supports:

- Status
- Client
- Date range
- Package
- Pagination

---

## Get Order

### GET `/orders/{id}`

---

## Create Order

### POST `/orders`

Used when an **already-authenticated** Client selects a package for a **subsequent** purchase
(renewal, additional package). The initial Order is created by the public application flow (§7).

Request:

```json
{
  "package_id": "uuid"
}
```

The backend determines:

- Workspace
- Client
- Price
- Currency

The frontend cannot choose the authoritative price or Workspace.

---

## Approve Order

### POST `/orders/{id}/approve`

Coach/Owner.

Server-side transaction:

1. Validate order/payment state
2. Approve payment
3. Approve order
4. Create Client Subscription
5. Activate Client
6. Trigger notifications
7. Record audit event

This operation must be idempotent.

---

## Reject Order

### POST `/orders/{id}/reject`

Request:

```json
{
  "reason": "Payment proof is not clear."
}
```

---

## Cancel Order

### POST `/orders/{id}/cancel`

Only allowed when the order is in a cancellable state.

---

# 11. Payment API

Payments are **not** a separate MVP module. There is no payments list endpoint; payments are
represented through Orders and their payment-related states, and every payment endpoint below is
order-scoped or proof-scoped.

If the Coach dashboard shows a "Payments" navigation item, it is a filtered Orders view, not a
separate backend domain.

## Submit Payment

### POST `/orders/{id}/payment`

`multipart/form-data`

Fields:

```text
method
reference
proof_file
```

The backend validates:

- Order ownership
- Payment method
- File type
- File size
- Current order state

---

Coach-commerce `Payment.status` values (Database & Authentication Architecture §13):

```text
PENDING
SUBMITTED
APPROVED
REJECTED
CANCELLED
```

These are **Coach Commerce** statuses (Client → Coach). They are separate from the FitOps
`BillingPayment` statuses in §20A (`PENDING`, `SUBMITTED`, `APPROVED`, `REJECTED`) and must never be
shared or merged.

## Get Order Payment

### GET `/orders/{id}/payment`

Coach/Owner for workspace orders.

Client may only see their own payment.

---

## Payment Proof

Payment proof should be served through an authorized endpoint rather than exposing unrestricted storage paths.

### GET `/payments/{id}/proof`

Authorization required.

---

# 12. Subscription API

## List Subscriptions

### GET `/subscriptions`

Coach/Owner.

Supports:

- Status
- Client
- Expiry range
- Pagination

---

## Get Subscription

### GET `/subscriptions/{id}`

---

## Current Client Subscription

### GET `/client/subscription`

Client-only.

---

## Renew Subscription

### POST `/subscriptions/{id}/renew`

Phase 1 supports manual renewal.

The endpoint creates the required renewal order/subscription flow rather than silently changing dates without a commercial record.

---

## Cancel Subscription

### POST `/subscriptions/{id}/cancel`

Coach/Owner according to subscription rules.

---

# 13. Training Plan API

## List Training Plans

### GET `/training-plans`

Coach/Owner.

---

## Create Training Plan

### POST `/training-plans`

Request:

```json
{
  "name": "12 Week Beginner Program",
  "description": "Beginner training plan",
  "duration_weeks": 12
}
```

---

## Get Training Plan

### GET `/training-plans/{id}`

---

## Update Training Plan

### PATCH `/training-plans/{id}`

---

## Archive Training Plan

### DELETE `/training-plans/{id}`

Prefer archive behavior if already assigned.

---

## Create Training Week

### POST `/training-plans/{id}/weeks`

---

## Update Training Week

### PATCH `/training-weeks/{id}`

---

## Create Training Day

### POST `/training-weeks/{id}/days`

---

## Update Training Day

### PATCH `/training-days/{id}`

---

## Add Exercise

### POST `/training-days/{id}/exercises`

Request:

```json
{
  "name": "Bench Press",
  "sets": 4,
  "reps": 10,
  "rest_seconds": 90,
  "notes": "Controlled tempo",
  "order": 1
}
```

---

## Update Exercise

### PATCH `/exercises/{id}`

---

## Delete Exercise

### DELETE `/exercises/{id}`

---

# 14. Nutrition Plan API

## List Nutrition Plans

### GET `/nutrition-plans`

---

## Create Nutrition Plan

### POST `/nutrition-plans`

---

## Get Nutrition Plan

### GET `/nutrition-plans/{id}`

---

## Update Nutrition Plan

### PATCH `/nutrition-plans/{id}`

---

## Archive Nutrition Plan

### DELETE `/nutrition-plans/{id}`

---

## Add Meal

### POST `/nutrition-plans/{id}/meals`

Request:

```json
{
  "name": "Breakfast",
  "description": "Eggs, bread and fruit",
  "calories": 500,
  "notes": "",
  "order": 1
}
```

---

## Update Meal

### PATCH `/nutrition-meals/{id}`

---

## Delete Meal

### DELETE `/nutrition-meals/{id}`

---

# 15. Plan Assignment API

## Assign Plans

### POST `/clients/{id}/plans`

Request:

```json
{
  "training_plan_id": "uuid",
  "nutrition_plan_id": "uuid",
  "start_date": "2026-08-15",
  "end_date": "2026-11-15"
}
```

Coach/Owner.

---

## Update Assignment

### PATCH `/plan-assignments/{id}`

---

## End Assignment

### POST `/plan-assignments/{id}/end`

---

## Client Current Plans

### GET `/client/plans`

Client-only.

---

## Client Plan History

### GET `/client/plans/history`

Client-only.

---

# 16. Check-in API

## Get Current Check-in

### GET `/client/check-ins/current`

Client-only.

---

## Create Check-in Draft

### POST `/client/check-ins`

Client-only.

---

## Update Draft

### PATCH `/client/check-ins/{id}`

Only allowed while status is `DRAFT`.

---

## Upload Check-in Photos

### POST `/client/check-ins/{id}/photos`

`multipart/form-data`

---

## Submit Check-in

### POST `/client/check-ins/{id}/submit`

Changes:

`DRAFT → SUBMITTED`

---

## Coach Check-ins

### GET `/check-ins`

Coach/Owner.

Supports:

- Status
- Client
- Date range
- Pagination

---

## Get Check-in

### GET `/check-ins/{id}`

---

## Review Check-in

### POST `/check-ins/{id}/review`

Request:

```json
{
  "feedback": "Great progress this week. Keep your current routine."
}
```

Changes:

`SUBMITTED → REVIEWED`

---

# 17. Progress API

## Client Progress

### GET `/client/progress`

Returns:

- Weight history
- Progress photos
- Check-in history

---

## Coach Client Progress

### GET `/clients/{id}/progress`

Coach/Owner.

---

## Upload Progress Photo

### POST `/client/progress/photos`

`multipart/form-data`

Fields:

```text
photo
photo_type
```

---

## Delete Progress Photo

### DELETE `/client/progress/photos/{id}`

The Client may delete their own photo according to product rules.

Coach access should be read-only unless explicitly required.

---

# 18. Notification API

## List Notifications

### GET `/notifications`

Returns notifications for the authenticated user.

---

## Unread Count

### GET `/notifications/unread-count`

---

## Mark Notification Read

### POST `/notifications/{id}/read`

---

## Mark All Read

### POST `/notifications/read-all`

---

# 19. Dashboard API

## Coach Dashboard

### GET `/dashboard`

Returns:

- Active clients
- New orders
- Pending payments
- Pending check-ins
- Revenue
- Expiring subscriptions
- Recent activity

Example:

```json
{
  "active_clients": 42,
  "new_orders": 7,
  "pending_payments": 3,
  "pending_check_ins": 8,
  "revenue": {
    "amount": "125000.00",
    "currency": "EGP"
  },
  "expiring_subscriptions": 5
}
```

---

## Client Dashboard

### GET `/client/dashboard`

Returns:

- Current package
- Days remaining
- Current plans
- Check-in status
- Latest feedback
- Progress summary

---

# 20. Platform Admin API

Platform Admin endpoints are completely separated from normal tenant APIs.

## Admin Dashboard

### GET `/admin/dashboard`

Returns:

- Total Coaches
- Active Coaches
- Total Workspaces
- Active Platform Subscriptions
- MRR
- Total Clients
- Total Orders

---

## Coaches

### GET `/admin/coaches`

Supports:

- Search
- Status
- Subscription status
- Pagination

### GET `/admin/coaches/{id}`

### POST `/admin/coaches/{id}/suspend`

### POST `/admin/coaches/{id}/reactivate`

---

## Workspaces

### GET `/admin/workspaces`

### GET `/admin/workspaces/{id}`

### POST `/admin/workspaces/{id}/suspend`

### POST `/admin/workspaces/{id}/reactivate`

---

## Platform Subscriptions

### GET `/admin/subscriptions`

### GET `/admin/subscriptions/{id}`

---

## Audit Logs

### GET `/admin/audit-logs`

Supports:

- Admin
- Action
- Target type
- Date range
- Pagination

---

# 20A. FitOps Billing API

> **Status: APPROVED — Architecture v1.2.**
> Models, lifecycle and access rules: Database & Authentication Architecture §22–§22G.

FitOps Billing (Coach → FitOps) is a **separate domain** from Coach Commerce (Client → Coach).
It never reuses `/orders`, `/payments`, or the Coach's `PaymentMethod` records.

MVP billing is manual through InstaPay, in EGP. No payment gateway is integrated.

Internal billing state transitions are never exposed directly to the client: a Coach submits a
payment and reads status, and the server owns every transition.

## Coach Billing

All Coach billing endpoints enforce, in order:

1. Authentication
2. Workspace context resolved from the URL slug
3. **`OWNER` role** — only the Workspace OWNER may view or manage the FitOps subscription;
   non-owner Coaches receive `PERMISSION_DENIED`
4. Subscription/Workspace ownership
5. Tenant isolation

Billing endpoints remain reachable in every subscription status, so a Coach whose subscription has
lapsed can always pay to recover access. They are refused when `Workspace.status = SUSPENDED`.

### GET `/billing/plans`

Returns the active FitOps `Plan` catalogue: code, name, description, price, currency,
billing interval, features.

---

### GET `/billing/subscription`

Returns the Workspace's current FitOps subscription:

- Plan
- Status (`TRIALING`, `ACTIVE`, `PAST_DUE`, `EXPIRED`, `CANCELLED`)
- `current_period_start`, `renewal_date`
- `trial_ends_at`
- `cancel_at_period_end`
- Amount due
- InstaPay payment instructions (from `PlatformPaymentInstruction`)
- Whether a payment is currently under review

The `PlatformSubscription` itself is created automatically in `TRIALING` when the Workspace is
created (7-day trial); there is no client-facing subscription-creation endpoint.

---

### POST `/billing/subscription/cancel`

Sets `cancel_at_period_end = true`. The current paid period remains active and the subscription
enters `CANCELLED` at `renewal_date`.

No immediate cancellation, no refund and no proration in MVP.

Mid-cycle plan changes, upgrades and downgrades are out of MVP scope; any plan change applies at the
next renewal period.

---

### GET `/billing/payments`

The Workspace's FitOps billing payment history: amount, currency, period, reference, status,
submitted/reviewed timestamps, rejection reason.

---

### POST `/billing/payments`

`multipart/form-data`

Submits a manual InstaPay payment for the current period.

Fields:

```text
reference
proof_file
```

The backend determines the subscription, amount, currency and period from the server-side
subscription state. The frontend cannot choose the amount, currency or period.

Moves the period's `BillingPayment` to `SUBMITTED` (creating it if it does not already exist in
`PENDING`), writes `PAYMENT_SUBMITTED`, and notifies Platform Admins.

A Coach whose previous payment was `REJECTED` submits a corrected payment through this same
endpoint.

Rate-limited, like all upload endpoints.

---

### GET `/billing/payments/{id}/proof`

Authorized retrieval of the Coach's own payment proof. Never a raw storage path.

---

## Platform Admin Billing

Extends the existing admin surface in §20. Admin-only (`platform_role = ADMIN`), fully separated
from tenant APIs, and audit-logged.

### GET `/admin/billing/payments`

The review queue. Supports filtering by status (`SUBMITTED` for pending), workspace, plan, date
range, and pagination.

Each row exposes the related Workspace, the owning Coach, the plan, the amount, and the submission
time.

---

### GET `/admin/billing/payments/{id}`

Full payment detail including reference, proof, period, related Workspace, Coach, plan, amount, and
the Workspace's payment history.

---

### GET `/admin/billing/payments/{id}/proof`

Authorized proof retrieval for the reviewing admin.

---

### POST `/admin/billing/payments/{id}/approve`

Server-side transaction, **idempotent** (API §23):

1. Validate payment and subscription state
2. Mark the payment `APPROVED`, set `reviewed_at` / `reviewed_by`
3. Advance `current_period_start` / `renewal_date`
4. Set the subscription status to `ACTIVE`
5. Write `BillingEvent` (`PAYMENT_APPROVED` plus `SUBSCRIPTION_RENEWED` or
   `SUBSCRIPTION_REACTIVATED`)
6. Write an `AuditLog` entry
7. Notify the Coach

A repeated approve must not advance the period twice — the operation must stay consistent when
retried.

**Period anchoring:** the new period runs from the previous `renewal_date` to that date plus 30
days, never from the payment or approval date. Late payment never grants bonus days (DB §22E).

---

### POST `/admin/billing/payments/{id}/reject`

Request:

```json
{ "reason": "Payment reference could not be matched." }
```

Marks the payment `REJECTED`, records `reviewed_at` / `reviewed_by` and the reason, writes
`PAYMENT_REJECTED` plus an audit entry, and notifies the Coach. The subscription status is unchanged
and the Coach may submit a corrected payment.

---

### GET `/admin/subscriptions`, `GET /admin/subscriptions/{id}`

Already defined in §20. These now expose the `Plan` relation, the billing status enum, the current
period, `cancel_at_period_end`, and the subscription's `BillingEvent` history.

`GET /admin/dashboard`'s existing **MRR** figure derives from active `PlatformSubscription` records
and their `Plan` prices.

---

### Plan management

```text
GET    /admin/plans
POST   /admin/plans
GET    /admin/plans/{id}
PATCH  /admin/plans/{id}
POST   /admin/plans/{id}/activate
POST   /admin/plans/{id}/deactivate
```

Platform Admin creates plans, edits plans (including price), and activates/deactivates them.

**There is no destructive delete.** A Plan referenced by any existing subscription can only be
deactivated; deactivation removes it from new-subscription offers and never breaks Workspaces
already on it.

---

### Platform payment instructions

```text
GET   /admin/billing/payment-instructions
PATCH /admin/billing/payment-instructions
```

Platform Admin configures FitOps' own InstaPay identifier, account name, instructions and optional
QR image. Individual Coaches never configure these. `multipart/form-data` when an image is included.

No sensitive credentials are stored.

---

## Billing Security Rules

In addition to the general rules in §25:

1. Coach billing endpoints are Workspace-scoped and resolve the Workspace from the URL slug.
2. Coach billing endpoints require the `OWNER` role; non-owner Coaches are denied.
3. A Coach may only ever see their own Workspace's subscription, payments and proofs.
4. Approval and rejection are Platform-Admin-only and are never reachable through Coach APIs.
5. Approval runs in a transaction and is idempotent.
6. Billing proof files are served only through authorized endpoints.
7. **No payment credentials are stored** — reference and proof image only, for both
   `BillingPayment` and `PlatformPaymentInstruction`.
8. Every billing state transition writes a `BillingEvent`; every admin decision also writes an
   `AuditLog` entry.
9. Billing endpoints stay reachable regardless of subscription status, and are refused when the
   Workspace is `SUSPENDED`.
10. Internal billing state transitions are never exposed as client-drivable operations.

---

# 21. File API / Storage Rules

Uploaded files include:

- Payment proofs
- Progress photos
- Coach images
- Workspace logos

Rules:

- Validate MIME type
- Validate file size
- Process images through Pillow
- Convert images to WebP where appropriate
- Generate thumbnails where appropriate
- Store files on Hetzner
- Keep metadata in PostgreSQL
- Never expose unrestricted file-system paths

Authorized file access should go through authenticated/permission-checked endpoints.

---

# 22. Rate Limiting

Rate limiting is mandatory for:

- Login
- Password reset
- Email verification
- Client OTP requests
- Client OTP verification
- File uploads
- Public application endpoints
- Sensitive admin actions

Client OTP should have especially strict limits to control email costs and prevent abuse.

---

# 23. Idempotency

The following operations must be idempotent or protected against duplicate execution:

- Order approval
- Payment submission
- Subscription creation
- Subscription renewal
- Client activation

Example:

If the Coach double-clicks **Approve**, the backend must not create two subscriptions.

---

# 24. Webhooks

Webhooks are not required for the initial manual-payment MVP.

However, the API architecture should reserve:

`/api/v1/webhooks/...`

for future integrations such as:

- Stripe
- Other payment providers
- Email providers
- External services

---

# 25. API Security Rules

1. Never trust `workspace_id` from the client.
2. Always resolve tenant context server-side.
3. Scope all workspace resources.
4. Scope Client requests to the authenticated ClientProfile.
5. Never expose another Client's data.
6. Never expose payment proof without authorization.
7. Use secure HttpOnly cookies.
8. Protect authentication endpoints with rate limits.
9. Hash OTPs and sensitive authentication tokens.
10. Log sensitive administrative actions.
11. Use transactions for order approval and subscription creation.
12. Validate ownership before every mutation.
13. Use UUIDs for externally exposed resource identifiers.
14. Never expose raw storage paths.
15. Return consistent error responses.
16. Resolve the Workspace from the URL slug on every Workspace-scoped route, including Coach
    dashboard routes.
17. Scope Workspace business records through the caller's `Membership`, and verify that
    `Membership.workspace` matches the resolved Workspace.

---

# 26. API Module Summary

```text
/api/v1/
│
├── auth
│   ├── coach authentication
│   ├── 2FA
│   ├── password reset
│   ├── client OTP
│   └── logout
│
├── workspace
│   ├── create
│   ├── settings
│   ├── branding
│   ├── payment methods
│   └── check-in schedule
│
├── public
│   ├── coaches
│   └── applications
│
├── dashboard
│
├── packages
├── clients
├── orders
├── payments          # order-scoped payment endpoints only, not a separate domain
├── subscriptions
├── training-plans
├── nutrition-plans
├── plan-assignments
├── check-ins
├── progress
├── notifications
├── billing            # FitOps subscription billing (Coach → FitOps), OWNER only
│   ├── plans
│   ├── subscription
│   └── payments
│
└── admin
    ├── dashboard
    ├── coaches
    ├── workspaces
    ├── subscriptions
    ├── plans          # FitOps plan management
    ├── billing        # payment review queue, approve/reject, payment instructions
    └── audit-logs
```

---

# 27. Official MVP API Scope

The API is considered complete for Phase 1 when the following flow works end-to-end:

```text
Coach
 ↓
Register
 ↓
Verify Email
 ↓
Login + 2FA
 ↓
Create Workspace
 ↓
Create Package
 ↓
Get Portal Link

Client
 ↓
Open Coach Portal
 ↓
Choose Package
 ↓
Apply
 ↓
Request OTP
 ↓
Login
 ↓
Create Order
 ↓
Submit Payment Proof

Coach
 ↓
Review Order
 ↓
Approve
 ↓
Subscription Created
 ↓
Client Activated

Coach
 ↓
Assign Training/Nutrition Plan

Client
 ↓
View Plan
 ↓
Submit Check-in
 ↓
Upload Progress Photos

Coach
 ↓
Review Check-in
 ↓
Send Feedback

Client
 ↓
View Feedback
 ↓
Track Progress
```

This is the minimum complete business loop for the MVP.


---

# 28. Locked Multi-Workspace Rules

These rules are mandatory for Phase 1 and override any older wording in this document.

## Global Identity

`User` and `ClientProfile` are global identities. `ClientProfile` MUST NOT contain `workspace_id`.

## Workspace Membership

Workspace access is represented by `Membership(user_id, workspace_id, role, status)`.

A Client may belong to multiple Workspaces.

## Workspace Resolution

The active tenant is determined by the Workspace slug in the URL/route, for the Coach dashboard as
well as the public and Client portals. Examples:

```text
app.platform.com/bergo/portal          # client portal
app.platform.com/bergo/dashboard       # coach dashboard
                  ↓
             workspace_slug
                  ↓
              Workspace
                  ↓
          Membership check
```

The API must never trust a client-supplied `workspace_id` as the tenant boundary.

## Client Isolation

For every Client request, the API must validate both:

1. The Client has an active Membership in the requested Workspace.
2. The requested resource belongs to that Client and Workspace.

A Client authenticated for Workspace A must not access resources belonging to Workspace B, even when the same User has a valid Membership in Workspace B.

## Authentication

Phase 1 uses Django's built-in session framework with secure HttpOnly session cookies.
JWT is not required. No custom `UserSession` / `token_hash` system is implemented.

- Coach: email + password + optional TOTP 2FA
- Client: email + one-time OTP
- Platform Admin: authenticated User with `platform_role = ADMIN`

Email (OTP codes, verification, password reset, notifications) is sent through Django's email
backend abstraction with an SMTP provider configured via environment variables.

## Tenant-Scoped Identity References

Workspace-scoped business records reference the Client through the Client's `Membership` in that
Workspace, and the Coach through the Coach's `Membership`. A global `User` or `ClientProfile`
reference alone must not be used where it would lose Workspace context.

`Application` is the exception: it is created before a Membership can exist and therefore carries a
nullable `user_id` pointing at the global `User`.

## Application and Initial Order

The public application flow creates the `Application` and the initial `Order` together, consistently
and safely. `POST /orders` is reserved for subsequent purchases by an authenticated Client.

## Subscription Separation

`Subscription` represents a Client's coaching subscription inside a Workspace.

`PlatformSubscription` represents the Workspace's subscription to the SaaS.

**Automated** SaaS billing remains outside Phase 1 scope. Manual FitOps subscription billing through
InstaPay — plan selection, manual payment submission, Platform Admin approval, and manual renewal —
is defined in §20A and Database & Authentication Architecture §22–§22G.
