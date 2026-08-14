# FitOps — Database & Authentication Architecture v1.2.1

> Version 1.2.1 adds the approved expiration/retention, archive and restoration lifecycle (§22H)
> and the explicit Coach-commerce `Payment.status` enum (§13).
> Version 1.2 adds the approved **FitOps Billing** domain (§22–§22H).
> Version 1.1 decisions remain in force and unchanged.
> The product name is **FitOps**. Earlier drafts used the working title "Coaching SaaS".

## 1. Authentication Architecture

The platform has two different authentication experiences.

### Coach

The Coach has a full user account:

- Email
- Password
- Email verification
- Forgot/reset password
- 2FA
- Sessions
- Login/logout
- Security settings

### Client

The Client uses passwordless authentication:

- Email
- One-time login code (OTP)
- Secure session after verification

Client login flow:

```text
Client
  ↓
Enter email
  ↓
Send OTP
  ↓
Enter code
  ↓
Verify
  ↓
Create session
  ↓
Client Portal
```

Clients do not need passwords or 2FA in Phase 1.

---

## 2. User Model

Use one central `User` model instead of separate CoachUser, ClientUser, and AdminUser models.

```text
User
----------------
id
email
password_hash
first_name
last_name
phone
is_active
email_verified_at
platform_role
created_at
updated_at
```

`platform_role`:

- NONE
- ADMIN

Coach/Client workspace roles are determined through memberships and profiles.

---

## 3. Coach Security

### CoachSecurity

```text
CoachSecurity
----------------
id
user_id
two_factor_enabled
two_factor_secret
created_at
updated_at
```

Phase 1 2FA uses **TOTP**.

Examples:

- Google Authenticator
- Microsoft Authenticator
- Other TOTP-compatible authenticator apps

No SMS-based 2FA is required for Phase 1.

---

## 4. Client OTP

Use a separate model for login codes.

### LoginOTP

```text
LoginOTP
----------------
id
user_id
email
code_hash
expires_at
attempts
used_at
created_at
```

The actual OTP must never be stored in plaintext.

Flow:

```text
Generate OTP
    ↓
Hash OTP
    ↓
Store hash
    ↓
Send actual OTP by email
    ↓
Client enters code
    ↓
Hash entered code
    ↓
Compare hashes
```

### OTP Security

- Short expiration window (around 10 minutes)
- One-time use
- Maximum verification attempts
- Rate limiting
- Invalidate previous active OTP when a new one is generated

---

## 5. User Sessions

After successful authentication, both Coaches and Clients receive a secure session.

Sessions use **Django's built-in session framework** with the database-backed session store.

A custom `UserSession` / `token_hash` model is **not** implemented in Phase 1 and must not be
introduced unless a future approved decision explicitly requires it.

Sessions are shared at the User identity level; the active Workspace is resolved separately from the requested Workspace context.

Session requirements:

- Django session framework, database-backed session store
- Secure HttpOnly session cookie
- Secure flag in production
- Appropriate SameSite configuration
- CSRF protection for state-changing requests
- Secure logout that terminates the current session
- Authentication rate limiting

Clients should not need to enter an OTP on every visit while their session remains valid.

### Session Management Scope

Per-session management is **not** part of the MVP. There is no session listing and no per-session
revocation endpoint; `POST /auth/logout` terminates the current session.

"Log out everywhere" may be introduced as a future feature.

---

## 6. Workspace

The Workspace is the core tenant of the SaaS.

### Workspace

```text
Workspace
----------------
id
name
slug
logo
profile_image
description
brand_color
currency
whatsapp_number
timezone
status
created_at
updated_at
```

Example:

```text
id: 12
name: Bergo Coaching
slug: bergo
currency: EGP
```

Portal:

`app.ourplatform.com/bergo`

Statuses:

- ACTIVE
- SUSPENDED

---

## 7. Membership

Membership defines which users have access to a Workspace.

### Membership

```text
Membership
----------------
id
workspace_id
user_id
role
status
joined_at
created_at
updated_at
```

`joined_at` is part of the authoritative Membership schema.

Constraint:

```text
UNIQUE(user_id, workspace_id)
```

Roles:

- OWNER
- COACH
- CLIENT

This allows future roles such as:

- ASSISTANT_COACH

without redesigning the authentication architecture.

---

## 8. Platform Admin

The Platform Admin is not a Workspace membership.

A platform administrator is represented by:

```text
User
platform_role = ADMIN
```

Platform Admins operate globally across the SaaS.

```text
Admin
   ↓
All Workspaces
   ↓
All Coaches
   ↓
Platform Data
```

Coach APIs must never expose platform-wide administrative access.

---

## 9. Coach Profile

Keep public/personal Coach information separate from the core User model.

### CoachProfile

```text
CoachProfile
----------------
id
user_id
bio
profile_image
website_url
instagram_url
created_at
updated_at
```

Workspace branding remains on the Workspace model.

This allows a Coach to potentially operate more than one Workspace in the future.

---

## 10. Client Profile

### ClientProfile

Client identity is global and is not owned by a single Workspace.

```text
ClientProfile
----------------
id
user_id
date_of_birth
gender
height
current_weight
goal
training_experience
notes
created_at
updated_at
```

The Client's relationship with a Workspace is represented through `Membership` with `role = CLIENT`. A Client may therefore belong to multiple Workspaces while keeping one global identity.

Example:

```text
Ahmed
 ↓
ClientProfile
 ├── Membership → Bergo Coaching
 └── Membership → Coach B
```

### Tenant-Scoped Identity References

`User` and `ClientProfile` remain global. Because of that, a global `User` or `ClientProfile`
reference alone would lose Workspace context on a workspace-specific business record.

Therefore:

- On Workspace-scoped business records, the Client reference (`client_id`) is a foreign key to
  **`Membership`** (the Client's Membership in that Workspace, `role = CLIENT`).
- On Workspace-scoped business records, the Coach reference (`coach_id`, for example on
  `CoachFeedback`) is a foreign key to **`Membership`** (`role` in `OWNER`, `COACH`).
- These records still carry an explicit `workspace_id`, which must match
  `Membership.workspace_id`.
- Global identity data (name, email, date of birth, height, goal, and similar) is read through
  `Membership → User → ClientProfile`. It is never duplicated onto Workspace-scoped records.
- `Application` is the exception: it is created before a Membership can exist, so it references
  the global `User` through a nullable `user_id` (see §11A).

Correct:

```text
Order.workspace_id  → Workspace
Order.client_id     → Membership(role=CLIENT, workspace=Order.workspace)
```

Incorrect:

```text
Order.client_id → ClientProfile      # loses Workspace context
Order.client_id → User               # loses Workspace context
```

---

## 11. Package

Each Coach creates their own coaching packages.

### Package

```text
Package
----------------
id
workspace_id
name
description
price
currency
duration_days
features
is_active
created_at
updated_at
```

Packages are Workspace-scoped.

Example:

```text
Workspace: Bergo Coaching

Package:
Fa7l
3500 EGP
90 days
```

---

## 11A. Application

The Application is the public onboarding record submitted from the Coach's public portal.
It is a first-class Workspace-scoped business record and lives in the `applications` Django app.

```text
Application
----------------
id
workspace_id
package_id
user_id            # NULLABLE
status
full_name
email
phone
age
gender
height
weight
goal
training_experience
notes
created_at
updated_at
```

Lifecycle:

```text
SUBMITTED
   ↓
REVIEWING
   ↓
APPROVED / REJECTED
```

Rules:

- `user_id` is **nullable**. A public application may originate from an anonymous visitor, so an
  authenticated User is **not** required at application creation time.
- The Workspace is resolved from the public URL slug, never from client-supplied input.
- Submitting an Application also creates the **initial Order** in the same flow. The Application
  and its initial Order must be created consistently and safely in a single transaction.
- The application flow may later create or reuse the `User`, create or reuse the `ClientProfile`,
  create the `Membership(role=CLIENT)`, and associate `Application.user_id`.

See §12 for the Order created by this flow.

---

## 12. Order

Orders represent the commercial purchase flow.

### Order

```text
Order
----------------
id
workspace_id
client_id
package_id
order_number
amount
currency
status
created_at
updated_at
```

Statuses:

- PENDING_PAYMENT
- PAYMENT_SUBMITTED
- APPROVED
- REJECTED
- CANCELLED

Flow:

```text
Client selects package
        ↓
Order created
        ↓
PENDING_PAYMENT
        ↓
Payment proof uploaded
        ↓
PAYMENT_SUBMITTED
        ↓
Coach approves
        ↓
APPROVED
```

---

## 13. Payment

Payment is separated from the Order.

### Payment

```text
Payment
----------------
id
workspace_id
order_id
method
amount
currency
reference
proof_file
status
paid_at
created_at
```

Statuses:

- PENDING
- SUBMITTED
- APPROVED
- REJECTED
- CANCELLED

This is the **Coach Commerce** payment enum (Client → Coach). It is completely separate from the
FitOps `BillingPayment` enum (Coach → FitOps, §22C) and the two must never be merged or shared.

Phase 1 payment methods:

- MANUAL_BANK
- INSTAPAY
- VODAFONE_CASH
- OTHER

Future payment integrations can be added without redesigning the Order architecture.

---

## 13A. Payment Method

Payment methods are configurable per Coach/Workspace and belong to the `workspaces` app.

```text
PaymentMethod
----------------
id
workspace_id
type
name
instructions
account_details
image
is_active
created_at
updated_at
```

Types:

- INSTAPAY
- VODAFONE_CASH
- BANK_TRANSFER
- CUSTOM

Rules:

- `account_details` holds the account/number details the Client needs in order to pay.
- `image` is an optional QR code or image, stored in media storage like any other upload
  (metadata only in PostgreSQL).
- `is_active` controls whether the method is offered in the payment step.
- Payment methods are Workspace-scoped and never shared between Workspaces.
- Automated payment gateways are **not** part of Phase 1.

---

## 14. Client Subscription

A Client Subscription represents the Client's coaching subscription with a Coach.

### Subscription

```text
Subscription
----------------
id
workspace_id
client_id
package_id
order_id
start_date
end_date
status
created_at
updated_at
```

Statuses:

- ACTIVE
- EXPIRING
- EXPIRED
- CANCELLED

Flow:

```text
Order Approved
      ↓
Subscription Created
      ↓
Client Activated
```

---

## 15. Training Plans

### TrainingPlan

```text
TrainingPlan
----------------
id
workspace_id
name
description
duration_weeks
created_at
updated_at
```

Structure:

```text
TrainingPlan
 ↓
Week
 ↓
Day
 ↓
Exercise
```

### Exercise

```text
Exercise
----------------
id
training_day_id
name
sets
reps
rest_seconds
notes
order
```

---

## 16. Nutrition Plans

### NutritionPlan

```text
NutritionPlan
----------------
id
workspace_id
name
description
calories
notes
created_at
updated_at
```

### NutritionMeal

```text
NutritionMeal
----------------
id
nutrition_plan_id
name
description
calories
notes
order
```

The Phase 1 nutrition system should remain simple and should not attempt to become a full nutrition engine.

---

## 17. Plan Assignment

Plans should not be permanently attached directly to a Client.

Use a separate assignment model.

### PlanAssignment

```text
PlanAssignment
----------------
id
workspace_id
client_id
training_plan_id
nutrition_plan_id
start_date
end_date
status
created_at
```

This preserves plan history.

Example:

```text
Plan A
Jan → Mar

Plan B
Apr → Jun
```

---

## 18. Check-ins

### CheckIn

```text
CheckIn
----------------
id
workspace_id
client_id
weight
energy
sleep
diet_adherence
training_adherence
notes
status
submitted_at
reviewed_at
created_at
```

Statuses:

- DRAFT
- SUBMITTED
- REVIEWED

`client_id` references the Client's `Membership` in the Workspace (see §10).

---

## 18A. Check-in Schedule

Phase 1 supports a simple Workspace-level check-in schedule configuration.

```text
CheckInSchedule
----------------
id
workspace_id
frequency
day_of_week
created_at
updated_at
```

Frequency:

- WEEKLY
- BIWEEKLY

Rules:

- The schedule is Workspace-scoped and configured by the Coach.
- `day_of_week` defines which day the check-in is expected.
- The MVP must not implement complex scheduling. The model should allow future expansion
  (for example per-client schedules or custom cadences) without requiring a redesign.

---

## 19. Progress Photos

Progress photos are stored on Hetzner storage, not inside PostgreSQL.

PostgreSQL stores only metadata.

### ProgressPhoto

```text
ProgressPhoto
----------------
id
workspace_id
client_id
check_in_id
photo_type
file_path
thumbnail_path
created_at
```

Photo types:

- FRONT
- SIDE
- BACK
- OTHER

Actual image files are stored in the application's Hetzner media storage.

---

## 20. Coach Feedback

### CoachFeedback

```text
CoachFeedback
----------------
id
workspace_id
client_id
check_in_id
coach_id
content
created_at
```

Flow:

```text
Check-in
 ↓
Coach reviews
 ↓
Coach Feedback
 ↓
Client sees feedback
```

---

## 21. Notifications

### Notification

```text
Notification
----------------
id
workspace_id
user_id
type
title
message
is_read
created_at
```

Examples:

- NEW_ORDER
- PAYMENT_SUBMITTED
- CHECKIN_SUBMITTED
- PLAN_ASSIGNED
- SUBSCRIPTION_EXPIRING

FitOps billing notifications (§22, addressed to the Workspace OWNER):

- PLATFORM_SUBSCRIPTION_EXPIRING
- PLATFORM_SUBSCRIPTION_PAST_DUE
- PLATFORM_SUBSCRIPTION_EXPIRED
- PLATFORM_PAYMENT_APPROVED
- PLATFORM_PAYMENT_REJECTED

These are Coach-facing subscription alerts about the Workspace's FitOps subscription and must not be
confused with `SUBSCRIPTION_EXPIRING`, which concerns a Client's coaching subscription.

---

## 22. FitOps Billing (Platform Subscription)

> **Status: APPROVED — Architecture v1.2. Locked.**
> §22–§22G are authoritative for the FitOps Billing domain.

### 22.1 Two separate payment domains

FitOps has two payment domains that must never share models:

| Domain | Direction | Models | App |
|---|---|---|---|
| **Coach Commerce** | Client → Coach | `Order`, `Payment`, `PaymentMethod`, `Subscription` | `commerce`, `workspaces` |
| **FitOps Billing** | Coach → FitOps | `Plan`, `PlatformSubscription`, `BillingPayment`, `BillingEvent`, `PlatformPaymentInstruction` | `billing` |

The Coach's client-facing `Order` model must **not** be reused for FitOps subscription billing.
The Coach's `PaymentMethod` records describe how that Coach's Clients pay the Coach; they are
unrelated to how the Coach pays FitOps.

Conceptual shape:

```text
Workspace
    ↓
PlatformSubscription
    ↓
Plan

PlatformSubscription
    ↓
BillingPayment  (amount, reference, proof)
    ↓
Platform Admin approval
    ↓
BillingEvent (audit history)
```

### 22.2 MVP payment method

MVP FitOps subscription payments are **manual, through InstaPay**. MVP billing currency is **EGP**.

No Stripe, Paymob, Paddle, Lemon Squeezy, automated card billing, or automated recurring payment
gateway is integrated at this stage. See §22F for the provider-agnostic boundary that keeps a future
provider from requiring a redesign.

---

## 22A. Plan

The FitOps subscription plan catalogue. Platform-owned — **not** Workspace-scoped.

```text
Plan
----------------
id
code                # STARTER | GROWTH | PRO
name
description
price
currency            # EGP in MVP; explicit so other currencies can be added
billing_interval    # MONTHLY (ANNUAL reserved, not implemented in MVP)
features
is_active
created_at
updated_at
```

Initial plans: **Starter**, **Growth**, **Pro**.

Rules:

- Plan pricing is configurable by the Platform Admin. No prices are specified by this architecture.
- The Platform Admin can create plans, edit plans, and activate/deactivate plans.
- **Destructive deletion of a Plan referenced by any existing subscription is forbidden.**
  Retiring a plan means `is_active = false`; deactivation must never break Workspaces already
  subscribed to it, and their subscriptions keep resolving to that Plan.
- A deactivated Plan is not offered for new subscriptions.
- `billing_interval` reserves `ANNUAL` so annual billing can be added later. Annual billing is not
  implemented in the MVP.

---

## 22A-1. PlatformPaymentInstruction

FitOps' own InstaPay payment details, configured by the **Platform Admin**. Platform-owned and
**not** Workspace-scoped — individual Coaches never configure these.

```text
PlatformPaymentInstruction
----------------
id
instapay_identifier     # InstaPay account/handle FitOps receives payment on
account_name
instructions
image                   # optional QR code / image
is_active
created_at
updated_at
```

Rules:

- These are the instructions shown to a Coach on the billing screen and in renewal alerts.
- Completely distinct from the Coach's own `PaymentMethod` records (§13A), which describe how a
  Coach's Clients pay that Coach.
- **No sensitive credentials are stored** — no banking credentials, no API keys, no provider
  secrets. Only the publicly shareable payment identifier, account name, instructions and image.
- The image follows the standard storage rules: metadata in PostgreSQL, file in media storage,
  served through an authorized endpoint.

---

## 22B. PlatformSubscription

Represents the Coach/Workspace subscription to FitOps. This is **different** from a Client's
coaching `Subscription` (§14).

```text
PlatformSubscription
----------------
id
workspace_id
plan_id                 # FK → Plan (replaces the v1.1 scalar `plan` field)
status
start_date
current_period_start
renewal_date            # end of the current period and the payment due date
trial_ends_at
cancel_at_period_end    # boolean
cancelled_at            # set when the subscription actually enters CANCELLED
created_at
updated_at
```

Statuses:

- TRIALING
- ACTIVE
- PAST_DUE
- EXPIRED
- CANCELLED

Rules:

- The **Workspace owns the subscription**. Subscription state must **not** be duplicated onto the
  `Workspace` model — `Workspace.status` is a separate concern (§22F).
- The current billing period is `[current_period_start, renewal_date]`. `renewal_date` is both the
  period end and the payment due date; there is no separate `current_period_end` field.
- The billing period is **30 days** in MVP.
- The v1.1 scalar `plan` field becomes `plan_id`, a foreign key to `Plan`.
- `SUSPENDED` is **not** a subscription status. Suspension is a Workspace state
  (`Workspace.status = SUSPENDED`, an admin enforcement action) and the two must never be
  conflated — see §22F.
- The Client coaching `Subscription` enum (`ACTIVE`, `EXPIRING`, `EXPIRED`, `CANCELLED`) is a
  separate enum and is unchanged. The two must not be merged.

---

## 22C. BillingPayment

A manual payment made by a Coach/Workspace to FitOps for a subscription period.

```text
BillingPayment
----------------
id
workspace_id            # explicit, per the tenant-scoping convention
subscription_id         # FK → PlatformSubscription
period_start            # period this payment covers
period_end
method                  # INSTAPAY in MVP; provider-agnostic field
amount
currency                # EGP in MVP; explicit so other currencies can be added
reference               # payment reference supplied by the Coach
proof_file              # payment proof image
status                  # PENDING | SUBMITTED | APPROVED | REJECTED
submitted_at
reviewed_at
reviewed_by             # FK → User (Platform Admin), nullable until reviewed
rejection_reason        # nullable
created_at
updated_at
```

Statuses:

- PENDING — the payment record exists for the period but the Coach has not submitted proof yet
- SUBMITTED — reference and proof submitted, awaiting Platform Admin review
- APPROVED — reviewed and accepted; the subscription period is advanced
- REJECTED — reviewed and refused; the Coach may submit a corrected payment

```text
PENDING → SUBMITTED → APPROVED
          SUBMITTED → REJECTED → SUBMITTED
```

This is the **FitOps Billing** enum (Coach → FitOps). It is separate from the Coach-commerce
`Payment.status` enum (§13), which additionally carries `CANCELLED`. The two enums must never be
merged, shared, or reused across domains.

Rules:

- Payment proof is modelled as fields on `BillingPayment` (`reference`, `proof_file`), matching the
  existing Coach-commerce `Payment.proof_file` convention. There is no separate proof entity.
- Proof files follow the standard storage rules: metadata in PostgreSQL, file in Hetzner media
  storage, served only through an authorized endpoint, never via a raw path.
- **No sensitive payment credentials are ever stored** — no card numbers, no bank credentials, no
  provider secrets. Only the Coach-supplied reference and proof image.
- The payment lifecycle is auditable through `reviewed_by` / `reviewed_at` plus `BillingEvent`.

---

## 22D. BillingEvent

Immutable billing history for a subscription: every state transition and every payment decision.

```text
BillingEvent
----------------
id
workspace_id
subscription_id
billing_payment_id      # nullable
event_type
actor_user_id           # nullable for system-generated events
from_status             # nullable
to_status               # nullable
metadata
created_at
```

Event types:

```text
SUBSCRIPTION_CREATED
TRIAL_STARTED
PAYMENT_CREATED
PAYMENT_SUBMITTED
PAYMENT_APPROVED
PAYMENT_REJECTED
SUBSCRIPTION_RENEWED
SUBSCRIPTION_PAST_DUE
SUBSCRIPTION_EXPIRED
SUBSCRIPTION_CANCELLED
SUBSCRIPTION_REACTIVATED
```

Relationship to `AuditLog` (§23): `AuditLog` records **security/administrative actions**;
`BillingEvent` records **business-level billing history**, including system-generated transitions
that have no admin actor. The two responsibilities must not be duplicated.

A payment approval therefore creates both:

```text
BillingEvent:  PAYMENT_APPROVED
AuditLog:      Admin X approved BillingPayment Y
```

---

## 22E. Subscription Lifecycle

### Free trial

Every Workspace starts on a **7-day free trial**. Creating a Workspace creates the
`PlatformSubscription` in `TRIALING`:

```text
Workspace created
      ↓
PlatformSubscription
      ↓
   TRIALING          trial_ends_at = start_date + 7 days
```

Trial conversion requires **no** payment gateway integration — the Coach pays manually through
InstaPay and a Platform Admin approves.

### State machine

```text
                    Workspace created
                          ↓
              ┌─── TRIALING ───┐
              │                │
     first payment        trial ends,
      approved            unpaid
              │                │
              ▼                ▼
           ACTIVE ────────► PAST_DUE ──── 7-day grace ────► EXPIRED
              ▲                │                              │
              └── renewal ─────┘                              │
                 approved                                     │
              ▲                                               │
              └──────────── reactivation payment ─────────────┘
                              approved

  TRIALING / ACTIVE  ──cancel_at_period_end──►  CANCELLED (at period end)
```

| From | To | Trigger |
|---|---|---|
| — | TRIALING | Workspace created (7-day trial) |
| TRIALING | ACTIVE | First `BillingPayment` approved |
| TRIALING | PAST_DUE | `trial_ends_at` passes with no approved payment |
| ACTIVE | PAST_DUE | `renewal_date` passes with no approved payment |
| PAST_DUE | ACTIVE | Renewal `BillingPayment` approved |
| PAST_DUE | EXPIRED | 7-day grace period ends |
| EXPIRED | ACTIVE | Reactivation `BillingPayment` approved |
| TRIALING / ACTIVE / PAST_DUE | CANCELLED | `cancel_at_period_end` takes effect at `renewal_date` |

### Cancellation

MVP cancellation is **cancel at period end**:

- Requesting cancellation sets `cancel_at_period_end = true`. The status does not change and the
  current paid period remains fully active.
- The request is recorded as a `SUBSCRIPTION_CANCELLED` billing event carrying effective-date
  metadata (the `renewal_date` on which it will take effect). No separate cancellation-request
  event type is introduced.
- At `renewal_date` the subscription enters `CANCELLED` and `cancelled_at` is set — `cancelled_at`
  records when cancellation actually took effect, not when it was requested.
- There is **no** immediate cancellation, **no** refund system, and **no** mid-cycle refund or
  proration in MVP.

### Reactivation

An `EXPIRED` subscription is reactivated by a new approved payment:

```text
EXPIRED → Coach submits payment → Admin approves → ACTIVE
```

Reactivation follows the same anchoring rule as any late payment (§22E renewal rules): one approved
payment advances the subscription by exactly one 30-day period from the previous period end. It
never grants bonus days.

> **Unresolved edge case — do not invent behavior.**
> A Workspace that has been unpaid across **multiple** billing periods cannot be made current by a
> single approved payment under the anchoring rule: the advanced period may still end in the past,
> returning the subscription to `PAST_DUE`. The anchoring rule stands as written and must not be
> silently changed. Whether a long-expired reactivation pays per elapsed period, or re-anchors to a
> new date, is **not decided**. Report it rather than choosing.
>
> In practice this interacts with §22H: after 30 days in `EXPIRED` the Workspace leaves the
> operational system, so the reachable window for this case is bounded.

### Plan changes

MVP does **not** support mid-cycle plan changes. There is no proration, no mid-cycle upgrade or
downgrade, no credit calculation and no refund calculation. Any plan change takes effect at the next
renewal period. No plan-change workflow is implemented in MVP.

### Payment lifecycle

```text
   PENDING                      period exists, proof not yet submitted
      ↓
Coach submits reference + proof
      ↓
  SUBMITTED
      ↓
Platform Admin reviews
    ┌───┴────┐
APPROVED   REJECTED ──► Coach submits a corrected payment ──► SUBMITTED
    ↓
Subscription period advanced
```

Approval is a single server-side transaction and must be **idempotent** (consistent with API §23):

```text
Validate payment + subscription state
        ↓
Mark BillingPayment APPROVED, set reviewed_at / reviewed_by
        ↓
Advance current_period_start / renewal_date
        ↓
Set PlatformSubscription status = ACTIVE
        ↓
Write BillingEvent (PAYMENT_APPROVED, SUBSCRIPTION_RENEWED)
        ↓
Write AuditLog entry
        ↓
Notify the Coach
```

A double-clicked **Approve** must never advance the period twice.

### Renewal

Renewal is **manual**. There is no automatic charge. "Recurring" means the subscription has a
recurring 30-day period and a renewal date that the Coach pays manually each cycle through InstaPay.

The system tracks the current period, tracks the renewal date, alerts the Coach before renewal,
accepts renewal payment proof, allows Admin approval, and extends the subscription on approval.

#### Period anchoring — late payment must not reset the cycle

On approval the new period is anchored to the **previous period end**, never to the payment or
approval date:

```text
new current_period_start = previous renewal_date
new renewal_date         = previous renewal_date + 30 days
```

Example:

```text
Original period:   August 1 → August 31
Coach pays late:   September 5
After approval:    August 31 → September 30      ✅

NOT:               September 5 → October 5       ❌
```

Late payment never creates free extra days. This rule applies identically to renewal after
`PAST_DUE` and to reactivation from `EXPIRED`.

---

## 22F. Workspace Access and Provider Abstraction

### Access by subscription status

| Status | Coach access | Client Portal |
|---|---|---|
| TRIALING | Normal | Accessible |
| ACTIVE | Normal | Accessible |
| PAST_DUE | **Restricted** — dashboard restricted; billing and renewal/payment actions remain accessible | Accessible |
| EXPIRED | **Restricted** | Accessible for **30 days** after the subscription became EXPIRED, then the Workspace leaves the operational system (§22H) |
| CANCELLED | **Restricted** | Accessible |

#### What "restricted" means for the Coach

A Coach whose subscription is `PAST_DUE`, `EXPIRED` or `CANCELLED` may still access:

- Billing
- Subscription information
- Renewal / payment submission actions
- Account settings
- Logout

The Coach may **not** use normal coaching-management functionality (clients, orders, packages,
plans, check-ins, progress, and equivalent workspace operations).

#### Client access rule

**A billing state never immediately removes Client access.** A Client's relationship is with the
Coach and the Coach's service, not directly with FitOps, so a Client must never lose access at the
moment the Coach's FitOps subscription becomes past due, expired or cancelled.

- `PAST_DUE` and `CANCELLED`: the Client Portal stays accessible.
- `EXPIRED`: the Client Portal does **not** become unavailable immediately. Clients keep access to
  their Portal and their existing plans and data for **30 days** after the subscription became
  `EXPIRED`. Only when that retention window ends does the Workspace leave the operational
  system (§22H).

Client data must **never** be deleted or disabled as an immediate consequence of a billing state.
Within the 30-day window it remains intact and reachable; after the window it is archived rather
than destroyed (§22H).

#### Enforcement point

Subscription-status enforcement sits immediately after the existing tenant-context resolution:
Workspace resolved from the slug → Membership verified → subscription status gates what the Coach
may do. Billing endpoints must remain reachable in every status so a Coach can always pay to recover
access.

### Workspace suspension vs subscription status

`Workspace.status` and `PlatformSubscription.status` are independent and must never be conflated.

```text
Workspace:     ACTIVE | SUSPENDED                                   (admin enforcement)
Subscription:  TRIALING | ACTIVE | PAST_DUE | EXPIRED | CANCELLED   (billing)
```

A Workspace may be `SUSPENDED` while its subscription is `ACTIVE`, and vice versa.

Suspension is a Platform Admin enforcement action, not a billing outcome. It therefore **supersedes
subscription status**: while `Workspace.status = SUSPENDED`, all Workspace-scoped access is denied
for Coaches and Clients alike, consistently with the existing authorization architecture — the
Workspace still resolves from the slug and Membership is still verified, but the request is refused
with `PERMISSION_DENIED`. Only a Platform Admin can lift a suspension
(`POST /admin/workspaces/{id}/reactivate`); paying a subscription does not.

`SUSPENDED` must never be added to the subscription status enum.

### Provider abstraction

The billing domain must stay provider-agnostic:

- No provider-specific fields on `Plan`, `PlatformSubscription`, or `BillingPayment`.
- `BillingPayment.method` carries the mechanism (`INSTAPAY` in MVP); adding a provider adds values,
  not columns on the subscription domain.
- Manual review is one implementation of a payment-confirmation boundary; a future provider
  confirms payment through its own path without changing the subscription state machine.
- `/api/v1/webhooks/...` is already reserved (API §24) for future provider callbacks.
- Never store provider credentials or card data.

```text
BillingProvider (boundary)
├── ManualInstaPayProvider   (MVP)
└── Automated providers      (future, out of scope)
```

---

## 22H. Expiration, Retention, Archive and Restoration

> **Status: APPROVED — Architecture v1.2.1.**

### Retention window

The clock starts when the subscription enters `EXPIRED` (that is, after the 7-day `PAST_DUE` grace
period ends).

```text
renewal_date passes unpaid
        ↓
     PAST_DUE            7-day grace
        ↓
      EXPIRED            ← retention window starts
        ↓
   30 days               Coach restricted · Client Portal still accessible · no data deleted
        ↓
Workspace cleanup / deactivation
        ↓
Archive only (not an active tenant)
```

During the 30-day retention window:

**Coach**

- Normal coaching functionality is restricted.
- Billing remains accessible.
- Subscription information remains accessible.
- Renewal / payment actions remain accessible.
- Account settings and logout remain accessible.

**Clients**

- The Client Portal remains accessible.
- Existing plans and data remain available.
- Client data is **not** deleted.

Paying and having a payment approved during this window reactivates the subscription (§22E) and
ends the retention window.

### Workspace cleanup

After 30 days in `EXPIRED`, the Workspace is cleaned up/deactivated according to this retention
lifecycle: the Coach's active Workspace data is removed from the **operational** system, so it is
no longer served through any normal application route — neither the Coach dashboard, nor the public
portal, nor the Client Portal.

Cleanup is a data-retention lifecycle action, not a billing status and not a `Workspace.status`
value. It must not be confused with `SUSPENDED`, which is an admin enforcement action on an
operational Workspace (§22F).

### Archive

Cleanup **must not** destroy the data. The system retains a backup/archive of the previous Workspace
data for potential restoration.

Rules:

- The archive is **not an active tenant**.
- It must **not** be reachable through normal application routes — no slug resolution, no Membership
  check against it, no tenant queries into it.
- It exists **only** for recovery/restoration purposes.
- It must be discoverable for the returning-Coach flow below, so that the system can detect that
  previous data exists for a returning Coach.

Minimum representation required to support detection and restoration:

```text
WorkspaceArchive
----------------
id
owner_user_id           # the Coach whose Workspace was archived
workspace_slug          # slug of the archived Workspace
workspace_name
archived_at
archive_reference       # pointer to the stored archive payload
status                  # AVAILABLE | RESTORED
created_at
updated_at
```

This archive is a product-level retention artifact and is distinct from the operational database and
media backups described in the Technology Stack.

> **Open decision — do not default.** The permanent retention duration of the archive (how long an
> `AVAILABLE` archive is kept before being purged, if ever) is **not specified**. Do not choose one.
> Likewise, the exact scope of "the supported recovery rules" — precisely which records a restore
> reinstates — is not specified. See §22G.

### Returning Coach / restoration flow

When a previously expired/cleaned-up Coach returns and the system detects an existing archive for
them, the Coach must be shown an **explicit choice**:

```text
"Previous coaching data was found."

1. Restore Previous Data
2. Start Fresh
```

- **Restore Previous Data** — the previous Workspace data is restored according to the supported
  recovery rules, and the archive is marked `RESTORED`.
- **Start Fresh** — a new, clean Workspace is created with no previous operational data restored.
  The archive is left untouched.

Hard rules:

- Old data is **never** restored automatically. The Coach must explicitly choose to restore.
- The archive is **never** exposed as an active Workspace. Restoration produces an operational
  Workspace; the archive itself never serves traffic.
- Choosing Start Fresh must not silently delete the archive.

---

## 22G. Approved Billing Decisions — v1.2 / v1.2.1

All seventeen previously open billing decisions are resolved. This table is the record; the
authoritative rules are the sections above.

| # | Decision | Resolution |
|---|---|---|
| B1 | Client portal access when the Coach's subscription lapses | **Clients keep access** — on `PAST_DUE` and `CANCELLED`, and for 30 days after `EXPIRED`. Refined by B18 in v1.2.1 |
| B2 | Meaning of "restricted access" | Billing, subscription info, renewal/payment, account settings and logout remain; normal coaching-management functionality is blocked |
| B3 | PAST_DUE grace period | **7 days**, then EXPIRED |
| B4 | Free trial | **7 days**, created with the Workspace, no gateway needed to convert |
| B5 | Status before the first approved payment | `TRIALING` from Workspace creation |
| B6 | Cancellation semantics | `cancel_at_period_end = true`; the paid period runs out, then CANCELLED. No immediate cancellation, no refunds, no proration |
| B7 | EXPIRED → ACTIVE | **Yes**, by a new approved payment (reactivation) |
| B8 | Late-payment anchoring | Anchored to the **previous period end**, never to the payment/approval date |
| B9 | Reminder cadence | 7 days / 3 days / 1 day before renewal, on the renewal date, and daily while PAST_DUE |
| B10 | FitOps InstaPay instructions | `PlatformPaymentInstruction` model, configured by Platform Admin (§22A-1) |
| B11 | Plan management | Platform Admin creates, edits, and activates/deactivates plans; no destructive deletion when referenced |
| B12 | Plan changes / proration | Not supported in MVP; any change applies at the next renewal period |
| B13 | `SUSPENDED` | Stays a **Workspace** state; never a subscription status |
| B14 | Payment proof | Fields on `BillingPayment`; no separate proof entity |
| B15 | BillingEvent vs AuditLog | Both written on admin decisions; `BillingEvent` = business history, `AuditLog` = security/admin actions |
| B16 | Pre-submission payment state | **Yes** — `PENDING` is part of the payment enum |
| B17 | Currency | **EGP** in MVP, held explicitly on `Plan` and `BillingPayment` so other currencies can be added |

### Added in v1.2.1

| # | Decision | Resolution |
|---|---|---|
| B18 | Client access on EXPIRED | Client Portal stays available for **30 days** after the subscription becomes EXPIRED; no immediate cut-off, no data deletion (§22H) |
| B19 | End of the retention window | The Workspace is cleaned up/deactivated and leaves the operational system after those 30 days (§22H) |
| B20 | Data destruction | Cleanup archives rather than destroys. The archive is not an active tenant and is unreachable through normal application routes (§22H) |
| B21 | Returning Coach | Explicit choice — **Restore Previous Data** or **Start Fresh**. Never restore automatically (§22H) |
| B22 | Coach-commerce `Payment.status` | `PENDING`, `SUBMITTED`, `APPROVED`, `REJECTED`, `CANCELLED` (§13) — separate from the FitOps `BillingPayment` enum (§22C) |
| B23 | Cancellation event timing | Confirmed unchanged: request sets `cancel_at_period_end` and records a `SUBSCRIPTION_CANCELLED` event with effective-date metadata; `cancelled_at` is set when the subscription actually enters CANCELLED. No separate request event type |

### Still open — do not default

| # | Item |
|---|---|
| B24 | **Permanent archive retention duration** — how long an `AVAILABLE` `WorkspaceArchive` is kept, and whether it is ever purged. Not specified; must not be silently chosen |
| B25 | **Scope of "the supported recovery rules"** — precisely which records a restore reinstates (clients, memberships, orders, subscriptions, plans, check-ins, progress media) |
| B26 | **Long-expired multi-period reactivation** — see the unresolved edge case in §22E. The renewal anchor must not be silently changed |
| B27 | **Terminal `CANCELLED` lifecycle** — the retention/cleanup lifecycle in §22H is defined for `EXPIRED`. Whether a `CANCELLED` subscription ever enters the same retention and cleanup path is not specified |

---

## 23. Audit Log

Important platform and administrative actions should be logged.

### AuditLog

```text
AuditLog
----------------
id
user_id
workspace_id
action
target_type
target_id
metadata
ip_address
created_at
```

Examples:

```text
Admin
 ↓
suspended
 ↓
Workspace #12
```

or:

```text
Coach
 ↓
approved
 ↓
Order #1092
```

---

## 24. Core Relationships

```text
User
 │
 ├── CoachSecurity
 │
 ├── CoachProfile
 │
 ├── Membership
 │      │
 │      └── Workspace
 │              │
 │              ├── Packages
 │              ├── Clients
 │              │      │
 │              │      ├── Orders
 │              │      ├── Subscriptions
 │              │      ├── CheckIns
 │              │      ├── ProgressPhotos
 │              │      └── PlanAssignments
 │              │
 │              ├── Applications
 │              ├── PaymentMethods
 │              ├── CheckInSchedule
 │              ├── TrainingPlans
 │              ├── NutritionPlans
 │              └── Notifications
 │
 └── LoginOTP
```

Sessions are handled by Django's session framework and are not modelled as an application model.

---

## 25. Multi-Tenancy Security

Every business object that belongs to a Coach must be Workspace-scoped.

The general authorization flow is:

```text
request.user
    ↓
Membership
    ↓
Workspace
    ↓
workspace-scoped query
    ↓
Object
```

### Critical Rule

Never trust a `workspace_id` supplied directly by the frontend.

The active Workspace must be resolved from the Workspace slug in the requested URL. This applies to
**all** Workspace contexts:

- Public coach portal — `/{workspaceSlug}`
- Client portal — `/{workspaceSlug}/portal`
- Coach dashboard — `/{workspaceSlug}/dashboard`, `/{workspaceSlug}/clients`, `/{workspaceSlug}/orders`, and so on

The backend then verifies that the authenticated User has an active Membership for that Workspace,
with a role appropriate to the requested area. Never trust a raw `workspace_id` supplied by the frontend.

---

## 26. Tenant Isolation

Example:

```text
Coach A
workspace_id = 10
```

tries to access an object belonging to:

```text
workspace_id = 20
```

The API must not expose the object.

For object lookup, a tenant-scoped query should return no result for unauthorized objects rather than revealing that the object exists.

---

## 27. Client Isolation

Client access requires two levels of authorization:

1. The Client must belong to the correct Workspace.
2. The Client must only access their own resources.

Flow:

```text
Client
 ↓
Membership
 ↓
Workspace
 ↓
ClientProfile
 ↓
Own Orders / Plans / Check-ins / Progress
```

A Client must never be able to access another Client's resources by changing an ID in the request.

---

## 28. Authentication Model

```text
                    USER
                     │
          ┌──────────┴──────────┐
          │                     │
       COACH                  CLIENT
          │                     │
 Email + Password             Email
 Email Verify                   │
 2FA / TOTP                     ▼
 Sessions                    OTP Code
          │                     │
          ▼                     ▼
 Coach Dashboard           Client Portal
```

Platform Admin:

```text
USER
 ↓
platform_role = ADMIN
 ↓
Platform Admin Panel
```

---

## 29. Security Requirements

The Phase 1 authentication system must include:

### Coach

- Password hashing
- Email verification
- Secure password reset
- TOTP 2FA
- Secure sessions
- Secure logout
- Login rate limiting

### Client

- OTP hashing
- OTP expiration
- OTP attempt limits
- OTP rate limiting
- Previous OTP invalidation
- Secure sessions
- Secure logout

### Platform

- Strict Admin permissions
- Workspace isolation
- Client isolation
- Audit logs
- Secure cookies
- HTTPS
- CSRF protection where applicable

---

## 30. Architecture Decision Summary

### Authentication

- Coach: full account with password + TOTP 2FA
- Client: passwordless email OTP
- Platform Admin: full authenticated user with platform-level role
- Sessions: Django built-in session framework with secure HttpOnly cookies
- Email: Django email backend abstraction + SMTP, configured via environment variables

### Tenant Model

- Shared PostgreSQL database
- Shared schema
- Workspace-based tenant isolation
- Business data scoped by `workspace_id`
- Global User and ClientProfile identity
- Workspace access through Membership
- Active Workspace resolved from the URL Workspace slug and verified through Membership
- Workspace-scoped business records reference the Client/Coach through `Membership`, not through
  a global `User` or `ClientProfile` reference alone

### Storage

- PostgreSQL stores metadata
- Hetzner stores uploaded media
- Images are compressed/resized before storage

### Core Hierarchy

```text
Platform
  ↓
Platform Admin
  ↓
Workspaces
  ↓
Coaches
  ↓
Clients
  ↓
Orders / Subscriptions / Plans / Check-ins / Progress
```

---

## 31. Architecture Decisions Locked

The Phase 1 architecture is locked around the following decisions:

- User is a global identity.
- ClientProfile is global and does not contain `workspace_id`.
- Workspace is the tenant boundary.
- Membership connects Users to Workspaces.
- A Client may belong to multiple Workspaces.
- The Client does not see other memberships inside a Workspace portal.
- The active Workspace is determined by the requested portal context/slug.
- The backend verifies Membership before granting Workspace access.
- Coach authentication uses email + password + TOTP 2FA.
- Client authentication uses passwordless email OTP.
- Authentication uses Django's session framework with secure HttpOnly session cookies; JWT is not required for Phase 1.
- Platform Admin is represented by `platform_role = ADMIN` and is outside normal Workspace membership.

### Added in v1.2

- FitOps Billing is a separate domain from Coach Commerce, owned by the `billing` app (§22).
- `Plan`, `PlatformPaymentInstruction`, `BillingPayment` and `BillingEvent` are added;
  `PlatformSubscription` moves to `billing` and gains `plan_id`, `current_period_start`,
  `cancel_at_period_end` and `cancelled_at`.
- Subscription statuses: `TRIALING`, `ACTIVE`, `PAST_DUE`, `EXPIRED`, `CANCELLED`.
  `SUSPENDED` remains a Workspace state only.
- 7-day free trial, 30-day billing period, 7-day PAST_DUE grace, manual InstaPay payment in EGP.
- Late payment is anchored to the previous period end and never resets the cycle.
- Only the Workspace `OWNER` manages the FitOps subscription.

### Added in v1.2.1

- Clients keep Portal access on `PAST_DUE` and `CANCELLED`, and for **30 days** after `EXPIRED`.
- After that window the Workspace is cleaned up/deactivated and retained only as a
  `WorkspaceArchive`, which is never an active tenant (§22H).
- A returning Coach with an archive is given an explicit **Restore Previous Data** / **Start Fresh**
  choice; data is never restored automatically.
- Coach-commerce `Payment.status` is explicitly `PENDING`, `SUBMITTED`, `APPROVED`, `REJECTED`,
  `CANCELLED` (§13), separate from the FitOps `BillingPayment` enum (§22C).

### Added in v1.1

- Sessions use Django's built-in session framework. No custom `UserSession` / `token_hash` model.
- Per-session listing/revocation is out of MVP scope; `POST /auth/logout` is the only session
  termination endpoint.
- Payments are represented through Orders and their payment states; there is no separate Payments
  domain in the MVP.
- Email uses Django's email backend abstraction with an SMTP provider configured through
  environment variables.
- `Membership.joined_at` is part of the authoritative Membership schema.
- Workspace-scoped business records reference the Client/Coach through `Membership`.
- `Application` is a first-class model with a **nullable** `user_id`, and its submission creates
  the initial Order in the same transaction.
- `PaymentMethod` is a Workspace-scoped model with types INSTAPAY, VODAFONE_CASH, BANK_TRANSFER,
  CUSTOM.
- `CheckInSchedule` is a Workspace-scoped model supporting WEEKLY / BIWEEKLY plus day of week.
- The Workspace slug in the URL is the authoritative Workspace context for the Coach dashboard as
  well as the public and Client portals.

---

## 32. Next Step

The database and authentication architecture now provide the foundation for the MVP.

The next stage is:

**API Design**

The API specification should define:

- Endpoints
- HTTP methods
- Authentication requirements
- Permissions
- Request schemas
- Response schemas
- Validation
- Error responses
- Tenant scoping
- Client ownership checks

Initial API groups:

```text
/auth
/workspace
/packages
/clients
/orders
/payments
/subscriptions
/coaching
/check-ins
/progress
/notifications
/admin
```

The API specification should be completed before implementation begins.
